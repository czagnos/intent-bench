"""Empirical OOS threshold fitting on a separate, labelled calibration split."""
import math
import time
from uuid import uuid4

from .model_catalog import embedding_key
from .providers import ModelUnavailable
from .retrieval import normalize, tokens
from .store import fingerprint

ALGORITHM = "cosine-oos-max-far-v1"
MIN_PER_CLASS = 10


def question_hash(text):
    return fingerprint(" ".join(tokens(normalize(text))))


def data_fingerprint(cases):
    return fingerprint([{k: c.get(k) for k in ("case_id", "question", "expected_decision", "expected_intent_id", "split", "source", "context")} for c in cases])


def calibration_identity(settings, version):
    return fingerprint({"embedding": embedding_key(settings), "catalog": version, "candidate_k": settings.candidate_k, "algorithm": ALGORITHM})


def public_calibration(artifact):
    public = {k: v for k, v in artifact.items() if k not in ("records", "question_hashes")}
    # Keep the full operating curve in storage; per-request metadata only needs the chosen point.
    public["metrics"] = {k: v for k, v in artifact["metrics"].items() if k != "operating_points"}
    return public


def fit_threshold(records, max_false_accept_rate):
    """Maximise in-scope retention subject to the requested empirical OOS FAR."""
    if not 0 <= max_false_accept_rate <= .5 or any(not math.isfinite(r["score"]) for r in records):
        raise ValueError("Invalid calibration scores or target rate.")
    inside = [r for r in records if r["in_scope"]]
    outside = [r for r in records if not r["in_scope"]]
    if min(len(inside), len(outside)) < MIN_PER_CLASS:
        raise ValueError("Calibration requires at least 10 labelled in-scope and 10 OOS cases.")
    scores = sorted({r["score"] for r in records})
    thresholds = [math.nextafter(scores[0], -math.inf)] + [(a+b)/2 for a, b in zip(scores, scores[1:])] + [math.nextafter(scores[-1], math.inf)]
    operating_points = []
    for threshold in thresholds:
        accepted_in = sum(r["score"] >= threshold for r in inside)
        accepted_out = sum(r["score"] >= threshold for r in outside)
        retention, far = accepted_in/len(inside), accepted_out/len(outside)
        operating_points.append({"threshold": threshold, "in_scope_accept_rate": retention, "oos_false_accept_rate": far,
                                 "in_scope_false_reject_rate": 1-retention, "balanced_accuracy": (retention+1-far)/2,
                                 "in_scope_total": len(inside), "oos_total": len(outside),
                                 "in_scope_accepted": accepted_in, "oos_false_accepted": accepted_out})
    feasible = [point for point in operating_points if point["oos_false_accept_rate"] <= max_false_accept_rate]
    best = max(feasible, key=lambda p: (p["in_scope_accept_rate"], -p["oos_false_accept_rate"], -p["threshold"]))
    return {**best, "low_retention": best["in_scope_accept_rate"] < .9, "operating_points": operating_points}


class Calibrator:
    def __init__(self, studio):
        self.studio = studio
        self.store = studio.store

    def cases(self, workspace, source):
        return self.store.cases(workspace, source=source, reviewed=True, split="calibration")

    def fit_snapshot(self, retriever, cases, source, max_false_accept_rate, candidate_k):
        """Run-private threshold from a frozen independent split, for exactly this subset.

        Called after index preparation; normal query latency excludes this work.
        Does not replace a user's live calibration or read mutable labels mid-run.
        """
        records = []
        for case in cases:
            candidates = retriever.search(case["question"], "e5", candidate_k)
            if not candidates:
                raise ModelUnavailable("No intent candidate was found for calibration.")
            records.append({"case_id": case["case_id"], "question": case["question"], "score": candidates[0].score,
                            "in_scope": case["expected_decision"] != "out_of_scope", "nearest_intent_id": candidates[0].intent_id})
        fit = fit_threshold(records, max_false_accept_rate)
        return {"id": str(uuid4()), "created": time.time(), "mode": "calibrated", "calibrated": True,
                "algorithm": ALGORITHM, "model": retriever.embeddings.settings.embedding_model,
                "embedding": retriever.embeddings.metadata, "catalog_version": retriever.version,
                "dataset_fingerprint": data_fingerprint(cases), "source": source, "split": "calibration",
                "sample_count": len(cases), "max_oos_false_accept_rate": max_false_accept_rate,
                "threshold": fit["threshold"], "metrics": fit, "experiment_only": True,
                "records": records, "question_hashes": [question_hash(c["question"]) for c in cases]}

    def validate_cases(self, workspace, cases, catalog):
        if any(c.get("context") or c["expected_decision"] not in ("route", "handoff", "out_of_scope") for c in cases):
            raise ValueError("Use context-free in-scope or OOS cases for calibration.")
        hashes = [question_hash(c["question"]) for c in cases]
        if len(set(hashes)) != len(hashes):
            raise ValueError("The calibration set contains duplicate utterances.")
        test_hashes = {question_hash(c["question"]) for c in self.store.cases(workspace, split="test")}
        example_hashes = {question_hash(text) for i in catalog["intents"] for text in i["examples"]}
        if set(hashes) & (test_hashes | example_hashes):
            raise ValueError("Calibration utterances cannot duplicate test cases or catalog examples.")
        ids = {i["intent_id"] for i in catalog["intents"]}
        if any(c["expected_decision"] == "route" and c["expected_intent_id"] not in ids for c in cases):
            raise ValueError("A calibration label is missing from the active catalog.")
        if min(sum(c["expected_decision"] != "out_of_scope" for c in cases), sum(c["expected_decision"] == "out_of_scope" for c in cases)) < MIN_PER_CLASS:
            raise ValueError("Calibration requires at least 10 labelled in-scope and 10 OOS cases.")

    def resolve(self, workspace, variant, version, mode, evaluation_cases=None):
        if variant.method != "e5":
            return None
        if mode == "off":
            return {"mode": "off", "calibrated": False}
        artifact = self.store.latest_calibration(workspace, calibration_identity(variant.settings, version))
        if not artifact:
            raise ValueError("No calibration exists for this model and catalog. Fit a threshold on the Calibration page.")
        current = self.cases(workspace, artifact["source"])
        if data_fingerprint(current) != artifact["dataset_fingerprint"]:
            raise ValueError("Calibration data has changed. Refit the threshold.")
        if evaluation_cases and set(artifact["question_hashes"]) & {question_hash(c["question"]) for c in evaluation_cases}:
            raise ValueError("Cases used for calibration cannot be tested with that threshold. Choose a separate test split.")
        return public_calibration(artifact)

    def status(self, workspace):
        version = self.store.catalog(workspace)["version"]
        profiles = []
        for option in self.studio.model_catalog.options(workspace)["embedding"]:
            entry = {"embedding_id": option["id"], "model": option["model"], "available": option["available"], "calibration": None}
            if option["available"]:
                try:
                    variant = self.studio.model_catalog.variant("e5", option["id"], workspace=workspace)
                    entry["calibration"] = self.resolve(workspace, variant, version, "calibrated")
                except ValueError as exc:
                    entry["reason"] = str(exc)
            profiles.append(entry)
        counts = {}
        for source in ("seed", "customer"):
            cases = self.cases(workspace, source)
            counts[source] = {"total": len(cases), "in_scope": sum(c["expected_decision"] in ("route", "handoff") for c in cases), "oos": sum(c["expected_decision"] == "out_of_scope" for c in cases)}
        return {"profiles": profiles, "datasets": counts, "catalog_version": version, "algorithm": ALGORITHM}

    def start(self, workspace, options):
        cases = self.cases(workspace, options.source)
        catalog = self.store.catalog(workspace)
        self.validate_cases(workspace, cases, catalog)
        variants, seen = [], set()
        for model_id in options.embedding_ids:
            variant = self.studio.model_catalog.variant("e5", model_id, workspace=workspace)
            key = embedding_key(variant.settings)
            if key not in seen:
                variants.append(variant)
                seen.add(key)
        job = self.store.create_job(workspace, "calibration", {"options": options.model_dump(), "catalog_version": catalog["version"], "progress": 0, "total": len(cases)*len(variants), "results": {}, "dataset_fingerprint": data_fingerprint(cases)})
        self.studio.evaluation_pool.submit(self.run, workspace, job["id"], cases, variants, options)
        return job

    def run(self, workspace, job_id, cases, variants, options):
        job = self.store.job(workspace, job_id)
        self.store.patch_job(workspace, job_id, {"status": "running"})
        results, progress = {}, 0
        for variant in variants:
            started, completed = time.perf_counter(), 0
            self.store.patch_job(workspace, job_id, {"active_model": variant.settings.embedding_model})
            try:
                retriever = self.studio.retriever(workspace, job["catalog_version"], variant.settings)
                retriever.prepare_index()
                records = []
                for case in cases:
                    # Only the question enters retrieval. Labels are used after scoring.
                    candidates = retriever.search(case["question"], "e5", variant.settings.candidate_k)
                    if not candidates:
                        raise ModelUnavailable("No intent candidate was found for calibration.")
                    records.append({"case_id": case["case_id"], "question": case["question"], "score": candidates[0].score,
                                    "in_scope": case["expected_decision"] != "out_of_scope", "nearest_intent_id": candidates[0].intent_id})
                    progress += 1
                    completed += 1
                    self.store.patch_job(workspace, job_id, {"progress": progress})
                fit = fit_threshold(records, options.max_oos_false_accept_rate)
                # Never publish a fit if its labels or catalog changed while it was running.
                if self.store.catalog(workspace)["version"] != job["catalog_version"] or data_fingerprint(self.cases(workspace, options.source)) != job["dataset_fingerprint"]:
                    raise ValueError("Data or catalog changed during calibration. Refit the threshold.")
                self.validate_cases(workspace, cases, self.store.catalog(workspace))
                artifact = {"id": str(uuid4()), "created": time.time(), "identity": calibration_identity(variant.settings, job["catalog_version"]),
                            "mode": "calibrated", "calibrated": True, "algorithm": ALGORITHM,
                            "model": variant.settings.embedding_model, "embedding": retriever.embeddings.metadata, "catalog_version": job["catalog_version"],
                            "dataset_fingerprint": job["dataset_fingerprint"], "source": options.source, "split": "calibration", "sample_count": len(records),
                            "max_oos_false_accept_rate": options.max_oos_false_accept_rate, "threshold": fit["threshold"], "metrics": fit,
                            "question_hashes": [question_hash(c["question"]) for c in cases], "records": records}
                self.store.save_calibration(workspace, artifact)
                results[variant.embedding_id] = {"status": "completed", "model": variant.settings.embedding_model, "calibration": public_calibration(artifact)}
            except Exception as exc:
                # One failed model must not publish a partial fit or prevent other models from fitting.
                progress += len(cases)-completed
                message = str(exc) if isinstance(exc, (ModelUnavailable, ValueError)) else "Calibration could not be completed. Check the model connection."
                results[variant.embedding_id] = {"status": "failed", "model": variant.settings.embedding_model, "error": message, "diagnostics": getattr(exc, "diagnostics", {})}
            results[variant.embedding_id]["elapsed_ms"] = round((time.perf_counter()-started)*1000, 2)
            self.store.patch_job(workspace, job_id, {"results": results, "progress": progress})
        status = "completed" if any(r["status"] == "completed" for r in results.values()) else "failed"
        self.store.patch_job(workspace, job_id, {"status": status, "results": results, "progress": progress})
