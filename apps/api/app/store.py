import hashlib
import json
import sqlite3
import time
from collections.abc import Iterable
from contextlib import contextmanager
from pathlib import Path
from typing import cast
from uuid import uuid4

from .catalog_presets import PresetRevision, PresetRevisionReport, SeedCase
from .contracts import Intent
from .execution import StopReason
from .evaluation_types import EvaluationCheckpoint, EvaluationTerminalStatus
from .importer import CaseSplit, ImportedCaseData, ImportReportData
from .transcript_data import ConversationSplitData, StoredCaseData, StoredImportReportData, same_imported_turn


def fingerprint(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]


class Store:
    def __init__(self, directory: Path):
        if directory.is_symlink():
            raise OSError("Private data directory must not be a symbolic link.")
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        directory.chmod(0o700)
        self.path = directory / "studio.db"
        for path in (self.path, directory / "studio.db-wal", directory / "studio.db-shm"):
            if path.is_symlink():
                raise OSError("Private database files must not be symbolic links.")
            if path.exists():
                path.chmod(0o600)
        with self.connect() as db:
            self.path.chmod(0o600)
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS model_registrations(workspace TEXT, model_id TEXT, payload TEXT,
                    PRIMARY KEY(workspace,model_id));
                CREATE TABLE IF NOT EXISTS catalogs(workspace TEXT, version TEXT, created REAL, payload TEXT,
                    PRIMARY KEY(workspace,version));
                CREATE TABLE IF NOT EXISTS cases(workspace TEXT, case_id TEXT, source TEXT, dataset TEXT,
                    reviewed INTEGER, split TEXT, payload TEXT, PRIMARY KEY(workspace,case_id));
                CREATE TABLE IF NOT EXISTS sessions(workspace TEXT, session_id TEXT, revision INTEGER,
                    payload TEXT, PRIMARY KEY(workspace,session_id));
                CREATE TABLE IF NOT EXISTS jobs(workspace TEXT, job_id TEXT, kind TEXT, created REAL,
                    status TEXT, payload TEXT, PRIMARY KEY(workspace,job_id));
                CREATE TABLE IF NOT EXISTS imports(workspace TEXT, import_id TEXT, created REAL, payload TEXT,
                    PRIMARY KEY(workspace,import_id));
                CREATE TABLE IF NOT EXISTS calibrations(workspace TEXT, calibration_id TEXT, identity TEXT,
                    created REAL, payload TEXT, PRIMARY KEY(workspace,calibration_id));
                CREATE INDEX IF NOT EXISTS calibrations_lookup ON calibrations(workspace,identity,created DESC);
                CREATE TABLE IF NOT EXISTS catalog_snapshots(workspace TEXT, version TEXT, payload TEXT,
                    PRIMARY KEY(workspace,version));
                CREATE TABLE IF NOT EXISTS seed_migrations(workspace TEXT, migration TEXT,
                    PRIMARY KEY(workspace,migration));
                CREATE TABLE IF NOT EXISTS seed_migration_reports(workspace TEXT, migration TEXT, payload TEXT,
                    PRIMARY KEY(workspace,migration));
                CREATE TABLE IF NOT EXISTS case_revisions(workspace TEXT, case_id TEXT, version TEXT,
                    created REAL, reason TEXT, payload TEXT, PRIMARY KEY(workspace,case_id,version));
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def catalog(self, workspace: str, version: str | None = None):
        with self.connect() as db:
            if version:
                row = db.execute("SELECT * FROM catalogs WHERE workspace=? AND version=?", (workspace, version)).fetchone()
                if row is None:
                    row = db.execute("SELECT * FROM catalog_snapshots WHERE workspace=? AND version=?", (workspace, version)).fetchone()
            else:
                row = db.execute("SELECT * FROM catalogs WHERE workspace=? ORDER BY created DESC LIMIT 1", (workspace,)).fetchone()
        return {"version": row["version"], "intents": json.loads(row["payload"])} if row else None

    def model_registrations(self, workspace):
        with self.connect() as db:
            return [json.loads(row[0]) for row in db.execute("SELECT payload FROM model_registrations WHERE workspace=? ORDER BY rowid", (workspace,))]

    def model_registration(self, workspace, model_id):
        with self.connect() as db:
            row = db.execute("SELECT payload FROM model_registrations WHERE workspace=? AND model_id=?", (workspace, model_id)).fetchone()
            return json.loads(row[0]) if row else None

    def save_model_registration(self, workspace, payload, update=False):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            exists = db.execute("SELECT 1 FROM model_registrations WHERE workspace=? AND model_id=?", (workspace, payload["id"])).fetchone()
            if update and not exists:
                raise KeyError("Model registration not found.")
            if not exists and db.execute("SELECT COUNT(*) FROM model_registrations WHERE workspace=?", (workspace,)).fetchone()[0] >= 200:
                raise ValueError("A workspace can contain at most 200 model registrations.")
            db.execute("INSERT INTO model_registrations VALUES(?,?,?) ON CONFLICT(workspace,model_id) DO UPDATE SET payload=excluded.payload", (workspace, payload["id"], json.dumps(payload, ensure_ascii=False)))

    def bootstrap_workspace(self, workspace: str, intents: list[Intent], cases: list[SeedCase]) -> bool:
        """Publish an initial catalog and its cases together, or preserve an existing workspace."""
        payload = [intent.model_dump() for intent in intents]
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM catalogs WHERE workspace=? LIMIT 1", (workspace,)).fetchone():
                return False
            db.execute("INSERT INTO catalogs VALUES(?,?,?,?)",
                       (workspace, fingerprint(payload), time.time(), json.dumps(payload, ensure_ascii=False)))
            for case in cases:
                db.execute("INSERT OR IGNORE INTO cases VALUES(?,?,?,?,?,?,?)",
                           (workspace, case.case_id, case.source, case.dataset_version, int(case.reviewed),
                            case.split, case.payload))
        return True

    def save_catalog(self, workspace: str, intents: list[dict], expected_version=None) -> str:
        version = fingerprint(intents)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if expected_version is not None:
                current = db.execute("SELECT version FROM catalogs WHERE workspace=? ORDER BY created DESC LIMIT 1", (workspace,)).fetchone()
                if not current or current[0] != expected_version:
                    raise ValueError("The catalog changed. Reload the current version and apply your edit again.")
            db.execute("INSERT INTO catalogs VALUES(?,?,?,?) ON CONFLICT(workspace, version) DO UPDATE SET created=excluded.created", (workspace, version, time.time(), json.dumps(intents, ensure_ascii=False)))
        return version

    def save_catalog_snapshot(self, workspace, catalog):
        """Experiment snapshots never become the active routing catalog."""
        with self.connect() as db:
            db.execute("INSERT OR IGNORE INTO catalog_snapshots VALUES(?,?,?)", (workspace, catalog["version"], json.dumps(catalog["intents"], ensure_ascii=False)))

    def expand_demo_catalog(self, workspace, core_ids, expanded):
        """One-time additive migration; preserve edits, custom catalogs and human labels."""
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM seed_migrations WHERE workspace=? AND migration='demo-800-v1'", (workspace,)).fetchone():
                return
            row = db.execute("SELECT payload FROM catalogs WHERE workspace=? ORDER BY created DESC LIMIT 1", (workspace,)).fetchone()
            if row:
                current = json.loads(row["payload"])
                ids = {i["intent_id"] for i in current}
                if core_ids <= ids:
                    additions = [i for i in expanded if i["intent_id"] not in ids]
                    if additions:
                        merged = current + additions
                        db.execute("INSERT OR IGNORE INTO catalogs VALUES(?,?,?,?)", (workspace, fingerprint(merged), time.time(), json.dumps(merged, ensure_ascii=False)))
            db.execute("INSERT INTO seed_migrations VALUES(?,?)", (workspace, "demo-800-v1"))

    def catalog_versions(self, workspace: str):
        with self.connect() as db:
            return [{"version": r["version"], "created": r["created"], "intent_count": len(json.loads(r["payload"]))} for r in db.execute("SELECT * FROM catalogs WHERE workspace=? ORDER BY created DESC", (workspace,))]

    @staticmethod
    def _archive_case(db, workspace, case, reason):
        db.execute("INSERT OR IGNORE INTO case_revisions VALUES(?,?,?,?,?,?)",
                   (workspace, case["case_id"], fingerprint(case), time.time(), reason, json.dumps(case, ensure_ascii=False)))

    def revise_demo(self, workspace, manifest, target_catalog, target_cases, core_ids):
        """Atomically upgrade untouched seed records; archive labels and preserve user edits."""
        from .contracts import Intent

        migration = manifest["id"]
        targets = {i["intent_id"]: i for i in target_catalog}
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM seed_migrations WHERE workspace=? AND migration=?", (workspace, migration)).fetchone():
                return
            row = db.execute("SELECT version,payload FROM catalogs WHERE workspace=? ORDER BY created DESC LIMIT 1", (workspace,)).fetchone()
            current = json.loads(row["payload"]) if row else []
            recognized = core_ids <= {i["intent_id"] for i in current}
            report = {"id": migration, "created": time.time(), "applicable": recognized,
                      "from_catalog_version": row["version"] if row else None,
                      "to_catalog_version": row["version"] if row else None,
                      "updated_intents": [], "preserved_intents": [], "updated_cases": [],
                      "relabeled_cases": [], "preserved_cases": [],
                      "case_changes": [{"case_id": cid, **change} for cid, change in manifest.get("case_changes", {}).items()]}
            if recognized:
                revised = []
                safe_ids = set()
                for intent in current:
                    iid = intent["intent_id"]
                    normalized = Intent.model_validate(intent).model_dump()
                    target = targets.get(iid)
                    if target and normalized == target:
                        safe_ids.add(iid)
                    elif target and fingerprint(normalized) == manifest["previous_catalog_hashes"].get(iid):
                        intent = target
                        safe_ids.add(iid)
                        report["updated_intents"].append(iid)
                    elif target:
                        report["preserved_intents"].append(iid)
                    revised.append(intent)
                if report["updated_intents"]:
                    version = fingerprint(revised)
                    db.execute("INSERT INTO catalogs VALUES(?,?,?,?) ON CONFLICT(workspace,version) DO UPDATE SET created=excluded.created",
                               (workspace, version, time.time(), json.dumps(revised, ensure_ascii=False)))
                    report["to_catalog_version"] = version
                for target in target_cases:
                    cid = target["case_id"]
                    row = db.execute("SELECT payload FROM cases WHERE workspace=? AND case_id=?", (workspace, cid)).fetchone()
                    # Deleted/missing cases are not silently restored by a revision.
                    if not row:
                        continue
                    case = json.loads(row[0])
                    if case == target:
                        continue
                    expected = target.get("expected_intent_id")
                    if (case.get("source") != "seed" or case.get("reviewed_at") is not None
                            or fingerprint(case) != manifest["previous_case_hashes"].get(cid)
                            or (case.get("expected_intent_id") and case["expected_intent_id"] not in safe_ids)
                            or (expected and expected not in safe_ids)):
                        report["preserved_cases"].append(cid)
                        continue
                    self._archive_case(db, workspace, case, migration + ":before")
                    db.execute("UPDATE cases SET source=?,dataset=?,reviewed=?,split=?,payload=? WHERE workspace=? AND case_id=?",
                               (target["source"], target["dataset_version"], int(target["reviewed"]), target["split"], json.dumps(target, ensure_ascii=False), workspace, cid))
                    self._archive_case(db, workspace, target, migration + ":after")
                    report["updated_cases"].append(cid)
                    if case.get("expected_intent_id") != expected:
                        report["relabeled_cases"].append(cid)
            db.execute("INSERT INTO seed_migration_reports VALUES(?,?,?)", (workspace, migration, json.dumps(report, ensure_ascii=False)))
            db.execute("INSERT INTO seed_migrations VALUES(?,?)", (workspace, migration))

    def migration_reports(self, workspace):
        with self.connect() as db:
            return [json.loads(row[0]) for row in db.execute("SELECT payload FROM seed_migration_reports WHERE workspace=? ORDER BY rowid", (workspace,))]

    def expand_preset(self, workspace: str, revision: PresetRevision,
                      intents: list[Intent], cases: list[SeedCase]) -> None:
        """Publish an additive preset revision and its report in one transaction."""
        targets = {intent.intent_id: intent.model_dump() for intent in intents}
        previous_ids = set(revision.previous_catalog_hashes)
        previous_case_ids = set(revision.previous_case_ids)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM seed_migrations WHERE workspace=? AND migration=?",
                          (workspace, revision.id)).fetchone():
                return
            row = db.execute("SELECT version,payload FROM catalogs WHERE workspace=? ORDER BY created DESC LIMIT 1",
                             (workspace,)).fetchone()
            current = json.loads(row["payload"]) if row else []
            normalized = {item["intent_id"]: Intent.model_validate(item).model_dump() for item in current}
            # The shared human intent alone cannot establish sector provenance.
            pristine_previous = any(iid != "service.human" and fingerprint(item) == revision.previous_catalog_hashes.get(iid)
                                    for iid, item in normalized.items())
            already_current = all(normalized.get(iid) == item for iid, item in targets.items())
            recognized = previous_ids <= normalized.keys() and (pristine_previous or already_current)
            report = PresetRevisionReport(id=revision.id, created=time.time(), applicable=recognized,
                                          from_catalog_version=row["version"] if row else None,
                                          to_catalog_version=row["version"] if row else None)
            additions = [item for iid, item in targets.items() if iid not in previous_ids and iid not in normalized]
            if not recognized:
                report.skipped_reason = "unrecognized_catalog"
            elif len(current) + len(additions) > 2000:
                report.skipped_reason = "capacity_exceeded"
            else:
                revised = []
                safe_ids = set()
                for item in current:
                    iid = item["intent_id"]
                    target = targets.get(iid)
                    if target == normalized[iid]:
                        safe_ids.add(iid)
                    elif target is not None and fingerprint(normalized[iid]) == revision.previous_catalog_hashes.get(iid):
                        item = target
                        safe_ids.add(iid)
                        report.updated_intents.append(iid)
                    elif target is not None:
                        report.preserved_intents.append(iid)
                    revised.append(item)
                for item in additions:
                    revised.append(item)
                    safe_ids.add(item["intent_id"])
                    report.updated_intents.append(item["intent_id"])
                if report.updated_intents:
                    version = fingerprint(revised)
                    db.execute("INSERT INTO catalogs VALUES(?,?,?,?) ON CONFLICT(workspace,version) DO UPDATE SET created=excluded.created",
                               (workspace, version, time.time(), json.dumps(revised, ensure_ascii=False)))
                    report.to_catalog_version = version
                for case in cases:
                    existing = db.execute("SELECT payload FROM cases WHERE workspace=? AND case_id=?",
                                          (workspace, case.case_id)).fetchone()
                    if existing:
                        if json.loads(existing[0]) != json.loads(case.payload):
                            report.preserved_cases.append(case.case_id)
                        continue
                    # A prior ID may have been intentionally deleted; never recreate it.
                    if case.case_id in previous_case_ids:
                        continue
                    references = case.references()
                    if not references.intent_ids() <= safe_ids:
                        report.skipped_cases.append(case.case_id)
                        continue
                    db.execute("INSERT INTO cases VALUES(?,?,?,?,?,?,?)",
                               (workspace, case.case_id, case.source, case.dataset_version,
                                int(case.reviewed), case.split, case.payload))
                    report.updated_cases.append(case.case_id)
            db.execute("INSERT INTO seed_migration_reports VALUES(?,?,?)",
                       (workspace, revision.id, report.model_dump_json()))
            db.execute("INSERT INTO seed_migrations VALUES(?,?)", (workspace, revision.id))

    def case_versions(self, workspace, case_id):
        with self.connect() as db:
            current = db.execute("SELECT payload FROM cases WHERE workspace=? AND case_id=?", (workspace, case_id)).fetchone()
            if not current:
                raise KeyError(case_id)
            versions = [{"version": row["version"], "created": row["created"], "reason": row["reason"], "case": json.loads(row["payload"])}
                        for row in db.execute("SELECT * FROM case_revisions WHERE workspace=? AND case_id=? ORDER BY created", (workspace, case_id))]
            return {"case_id": case_id, "current": json.loads(current[0]), "versions": versions}

    def save_cases(self, workspace: str, cases: list[dict]):
        with self.connect() as db:
            for case in cases:
                # Reimporting the same source must not erase human review.
                self._insert_case(db, workspace, cast(StoredCaseData, case))

    @staticmethod
    def _insert_case(db: sqlite3.Connection, workspace: str, case: StoredCaseData) -> None:
        db.execute("INSERT OR IGNORE INTO cases VALUES(?,?,?,?,?,?,?)",
                   (workspace, case["case_id"], case["source"], case["dataset_version"],
                    int(case["reviewed"]), case["split"], json.dumps(case, ensure_ascii=False)))

    def import_cases(self, workspace: str, cases: list[ImportedCaseData],
                     report: ImportReportData) -> StoredImportReportData:
        """Persist parsed cases and their actual insertion counts together."""
        result: StoredImportReportData = {**report, "inserted": 0, "already_present": 0}
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            current_splits = self._conversation_splits(db, workspace, {case["conversation_id"] for case in cases})
            for splits in current_splits.values():
                if len(splits) > 1:
                    raise ValueError("The conversation spans multiple splits. Use the whole-conversation split action.")
            pending: list[ImportedCaseData] = []
            for case in cases:
                existing = db.execute("SELECT payload FROM cases WHERE workspace=? AND case_id=?",
                                      (workspace, case["case_id"])).fetchone()
                if existing:
                    stored = cast(StoredCaseData, json.loads(existing[0]))
                    if not same_imported_turn(stored, case):
                        raise ValueError("Conflicting source turn identity or immutable transcript content.")
                    result["already_present"] += 1
                else:
                    pending.append(case)
            resolved = {conversation_id: next(iter(splits)) for conversation_id, splits in current_splits.items()}
            for case in pending:
                if case["split_explicit"]:
                    previous = resolved.get(case["conversation_id"])
                    if previous is not None and previous != case["split"]:
                        raise ValueError("The conversation has a conflicting explicit split. Use the whole-conversation split action.")
                    resolved[case["conversation_id"]] = case["split"]
            for case in pending:
                stored_case = cast(StoredCaseData, {**case, "split": resolved.get(case["conversation_id"], "test")})
                self._insert_case(db, workspace, stored_case)
            result["inserted"] = len(pending)
            db.execute("INSERT OR REPLACE INTO imports VALUES(?,?,?,?)",
                       (workspace, report["dataset_version"], time.time(), json.dumps(result, ensure_ascii=False)))
        return result

    @staticmethod
    def _conversation_cases(db: sqlite3.Connection, workspace: str,
                            conversation_ids: set[str]) -> list[StoredCaseData]:
        cases: list[StoredCaseData] = []
        for row in db.execute("SELECT payload FROM cases WHERE workspace=?", (workspace,)):
            case = cast(StoredCaseData, json.loads(row[0]))
            conversation_id = case.get("conversation_id")
            if conversation_id and conversation_id in conversation_ids:
                cases.append(case)
        return cases

    @classmethod
    def _conversation_splits(cls, db: sqlite3.Connection, workspace: str,
                             conversation_ids: set[str]) -> dict[str, set[CaseSplit]]:
        splits: dict[str, set[CaseSplit]] = {}
        for case in cls._conversation_cases(db, workspace, conversation_ids):
            conversation_id = case.get("conversation_id")
            if conversation_id:
                splits.setdefault(conversation_id, set()).add(case["split"])
        return splits

    def update_conversation_split(self, workspace: str, conversation_id: str,
                                  split: CaseSplit) -> ConversationSplitData:
        """Move every conversation turn together without changing human labels."""
        if split not in ("dev", "calibration", "test"):
            raise ValueError("The conversation split must be dev, calibration or test.")
        updated_count = 0
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            cases = self._conversation_cases(db, workspace, {conversation_id})
            if not cases:
                raise KeyError(conversation_id)
            for case in cases:
                if case["split"] == split:
                    continue
                self._archive_case(db, workspace, case, "conversation_split:before")
                case["split"] = split
                db.execute("UPDATE cases SET split=?,payload=? WHERE workspace=? AND case_id=?",
                           (split, json.dumps(case, ensure_ascii=False), workspace, case["case_id"]))
                self._archive_case(db, workspace, case, "conversation_split:after")
                updated_count += 1
        return {"conversation_id": conversation_id, "split": split, "updated_count": updated_count}

    def validate_conversation_separation(self, workspace: str,
                                         conversation_ids: Iterable[str | None]) -> None:
        """Reject leakage for a selected cohort, including manually saved older rows."""
        selected = {conversation_id for conversation_id in conversation_ids if conversation_id}
        if not selected:
            return
        with self.connect() as db:
            splits = self._conversation_splits(db, workspace, selected)
        if any(len(values) > 1 for values in splits.values()):
            raise ValueError("A selected conversation spans multiple splits. Use the whole-conversation split action.")

    def cases(self, workspace: str, source="all", reviewed: bool | None = None, split: str | None = None):
        query, values = "SELECT payload FROM cases WHERE workspace=?", [workspace]
        for column, value in [("source", source if source != "all" else None), ("reviewed", None if reviewed is None else int(reviewed)), ("split", split)]:
            if value is not None:
                query += f" AND {column}=?"
                values.append(value)
        with self.connect() as db:
            return [json.loads(r[0]) for r in db.execute(query + " ORDER BY rowid", values)]

    def review_case(self, workspace: str, case_id: str, review: dict):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT payload FROM cases WHERE workspace=? AND case_id=?", (workspace, case_id)).fetchone()
            if not row:
                raise KeyError(case_id)
            case = json.loads(row[0])
            conversation_id = case.get("conversation_id")
            if conversation_id:
                split = review.get("split", case["split"])
                siblings = self._conversation_cases(db, workspace, {conversation_id})
                if any(sibling["case_id"] != case_id and sibling["split"] != split for sibling in siblings):
                    raise ValueError("This review would split a conversation. Use the whole-conversation split action first.")
            self._archive_case(db, workspace, case, "human_review:before")
            case.update(review, reviewed=True, reviewed_at=time.time())
            db.execute("UPDATE cases SET reviewed=1,split=?,payload=? WHERE workspace=? AND case_id=?", (case["split"], json.dumps(case, ensure_ascii=False), workspace, case_id))
            self._archive_case(db, workspace, case, "human_review:after")
        return case

    def create_session(self, workspace: str):
        session = {"session_id": str(uuid4()), "revision": 0, "active_intent": None, "slots": {}, "pending_slot": None, "pending_confirmation": False, "clarification_options": [], "clarifications": 0, "messages": []}
        with self.connect() as db:
            db.execute("INSERT INTO sessions VALUES(?,?,?,?)", (workspace, session["session_id"], 0, json.dumps(session)))
        return session

    def claim_turn(self, workspace: str, session_id: str, revision: int):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM sessions WHERE workspace=? AND session_id=?", (workspace, session_id)).fetchone()
            if not row:
                raise KeyError(session_id)
            if revision <= row["revision"]:
                raise ValueError("This conversation turn was already processed or belongs to an older revision.")
            session = json.loads(row["payload"])
            session["revision"] = revision
            db.execute("UPDATE sessions SET revision=?,payload=? WHERE workspace=? AND session_id=?", (revision, json.dumps(session, ensure_ascii=False), workspace, session_id))
        return session

    def finish_turn(self, workspace: str, session: dict, revision: int) -> bool:
        with self.connect() as db:
            count = db.execute("UPDATE sessions SET payload=? WHERE workspace=? AND session_id=? AND revision=?", (json.dumps(session, ensure_ascii=False), workspace, session["session_id"], revision)).rowcount
        return count == 1

    def job(self, workspace: str, job_id: str):
        with self.connect() as db:
            row = db.execute("SELECT payload FROM jobs WHERE workspace=? AND job_id=?", (workspace, job_id)).fetchone()
        return json.loads(row[0]) if row else None

    def create_job(self, workspace: str, kind: str, payload: dict, job_id: str | None = None):
        job = {"id": job_id or str(uuid4()), "kind": kind, "status": "queued", "created": time.time(), "events": [], **payload}
        with self.connect() as db:
            db.execute("INSERT INTO jobs VALUES(?,?,?,?,?,?)", (workspace, job["id"], kind, job["created"], job["status"], json.dumps(job, ensure_ascii=False)))
        return job

    def patch_job(self, workspace: str, job_id: str, updates: dict):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT payload FROM jobs WHERE workspace=? AND job_id=?", (workspace, job_id)).fetchone()
            if not row:
                raise KeyError(job_id)
            job = json.loads(row[0])
            if "event" in updates:
                job["events"].append({"id": len(job["events"])+1, "at": time.time(), **updates["event"]})
            job.update({k: v for k, v in updates.items() if k != "event"})
            db.execute("UPDATE jobs SET status=?,payload=? WHERE workspace=? AND job_id=?", (job["status"], json.dumps(job, ensure_ascii=False), workspace, job_id))
        return job

    def jobs(self, workspace: str, kind="evaluation"):
        with self.connect() as db:
            return [json.loads(r[0]) for r in db.execute("SELECT payload FROM jobs WHERE workspace=? AND kind=? ORDER BY created DESC LIMIT 30", (workspace, kind))]

    @contextmanager
    def _evaluation_transaction(self, workspace: str, job_id: str):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT payload FROM jobs WHERE workspace=? AND job_id=? AND kind='evaluation'",
                             (workspace, job_id)).fetchone()
            if row is None:
                raise KeyError(job_id)
            job = json.loads(row[0])
            yield job
            db.execute("UPDATE jobs SET status=?,payload=? WHERE workspace=? AND job_id=?",
                       (job["status"], json.dumps(job, ensure_ascii=False), workspace, job_id))

    def claim_evaluation(self, workspace: str, job_id: str):
        with self._evaluation_transaction(workspace, job_id) as job:
            if job["status"] != "queued" or job.get("cancel_requested"):
                return None
            job.update(status="running", started=time.time())
        return job

    def cancel_evaluation(self, workspace: str, job_id: str):
        with self._evaluation_transaction(workspace, job_id) as job:
            if job["status"] in ("queued", "running"):
                job["cancel_requested"] = True
                if job["status"] == "queued":
                    job.update(status="cancelled", stop_reason="user_cancelled", phase="complete")
        return job

    def checkpoint_evaluation(self, workspace: str, job_id: str, updates: EvaluationCheckpoint):
        # Progress cannot replace lifecycle state, including cancellation accepted concurrently.
        with self._evaluation_transaction(workspace, job_id) as job:
            if job["status"] == "running":
                job.update({key: value for key, value in updates.items()
                            if key not in ("status", "cancel_requested", "stop_reason", "started", "accounting")})
                if "accounting" in updates:
                    job["accounting"] = updates["accounting"].model_dump()
        return job

    def finalize_evaluation(self, workspace: str, job_id: str,
                            status: EvaluationTerminalStatus,
                            *, stop_reason: StopReason | None = None, error: str | None = None):
        with self._evaluation_transaction(workspace, job_id) as job:
            if job["status"] != "running":
                return job
            if job.get("cancel_requested"):
                job.update(status="cancelled", stop_reason="user_cancelled", error=None)
            else:
                job.update(status=status, stop_reason=stop_reason, error=error)
            job.update(phase="complete", elapsed_ms=round((time.time()-job["started"])*1000, 2))
        return job

    def save_import(self, workspace: str, report: dict):
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO imports VALUES(?,?,?,?)", (workspace, report["dataset_version"], time.time(), json.dumps(report, ensure_ascii=False)))

    def imports(self, workspace: str):
        with self.connect() as db:
            return [json.loads(r[0]) for r in db.execute("SELECT payload FROM imports WHERE workspace=? ORDER BY created DESC", (workspace,))]

    def recover_interrupted_jobs(self):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute("SELECT workspace,job_id,payload FROM jobs WHERE status IN ('queued','running')").fetchall()
            for row in rows:
                job = json.loads(row["payload"])
                job.update(status="failed", error="The run could not complete because the service restarted.")
                if job["kind"] == "evaluation":
                    job.update(stop_reason="interrupted", phase="complete")
                    if job.get("cancel_requested"):
                        job.update(status="cancelled", stop_reason="user_cancelled", error=None)
                db.execute("UPDATE jobs SET status=?,payload=? WHERE workspace=? AND job_id=?", (job["status"], json.dumps(job, ensure_ascii=False), row["workspace"], row["job_id"]))

    def save_calibration(self, workspace, calibration):
        with self.connect() as db:
            db.execute("INSERT INTO calibrations VALUES(?,?,?,?,?)", (workspace, calibration["id"], calibration["identity"], calibration["created"], json.dumps(calibration, ensure_ascii=False)))

    def latest_calibration(self, workspace, identity):
        with self.connect() as db:
            row = db.execute("SELECT payload FROM calibrations WHERE workspace=? AND identity=? ORDER BY created DESC LIMIT 1", (workspace, identity)).fetchone()
        return json.loads(row[0]) if row else None
