import asyncio
import json
import re
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import ROOT, Settings
from .contracts import CalibrationRequest, EvaluationRequest, Intent, IntentEdit, IntentSaved, Review, RouteRequest
from .catalog_quality import audit_catalog
from .importer import import_benchmark
from .model_catalog import embedding_runtime_key, llm_metadata
from .model_routes import model_routes
from .retrieval import ModelUnavailable
from .request_security import LocalRequestMiddleware
from .service import Studio
from .catalog_scope import core_ids
from .catalog_presets import PresetMetadata, catalog_presets
from .store import fingerprint
from .setup import SetupStatus, setup_status

Workspace = Annotated[str, Query(pattern=r"^[a-zA-Z0-9_-]{1,64}$")]


def validate_intent_references(intent: Intent, catalog_ids: set[str]) -> None:
    if any(neighbor not in catalog_ids or neighbor == intent.intent_id for neighbor in intent.confusable_with):
        raise HTTPException(422, f"{intent.intent_id} must reference other intents in this catalog.")
    if len(set(intent.required_slots)) != len(intent.required_slots):
        raise HTTPException(422, f"{intent.intent_id} has duplicate required slots.")
    if any(not slot.strip() or not intent.slot_questions.get(slot, "").strip() for slot in intent.required_slots):
        raise HTTPException(422, f"{intent.intent_id} needs a nonempty question for each required slot.")
    if not intent.channels or any(channel not in {"chat", "voice"} for channel in intent.channels):
        raise HTTPException(422, f"{intent.intent_id} must support at least one of chat or voice.")


def create_app(settings: Settings | None = None):
    settings = settings or Settings()
    studio = Studio(settings)
    studio.ensure_workspace("demo")

    @asynccontextmanager
    async def lifespan(app):
        studio.store.recover_interrupted_jobs()
        yield
        studio.close()

    app = FastAPI(title="IntentBench", version="0.1.0", lifespan=lifespan)
    app.state.studio = studio
    app.include_router(model_routes(studio))

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        if request.url.path.startswith("/v1/model-registry"):
            # Never echo invalid input: someone may paste a secret into the wrong form field.
            return JSONResponse(status_code=422, content={"detail": "Invalid model form. Check the fields and key variable name.",
                "fields": [".".join(str(v) for v in error["loc"][1:]) for error in exc.errors()
                           if error["type"] != "extra_forbidden"]})
        return await request_validation_exception_handler(request, exc)
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["GET", "POST", "PATCH"], allow_headers=["Content-Type"])
    app.add_middleware(LocalRequestMiddleware, allowed_origins=settings.cors_origins, trusted_hosts=settings.trusted_hosts)

    def ensure(workspace):
        studio.ensure_workspace(workspace)

    @app.get("/health")
    def health():
        return {"status": "ok", "version": "0.1.0"}

    @app.get("/v1/status")
    def status(workspace: Workspace = "demo"):
        ensure(workspace)
        cases = studio.store.cases(workspace)
        catalog = studio.store.catalog(workspace)
        return {"workspace": workspace, "catalog_version": catalog["version"], "intent_count": len(catalog["intents"]), "catalog_min_size": max(1, len(core_ids() & {i["intent_id"] for i in catalog["intents"]})), "case_count": len(cases), "customer_case_count": sum(c["source"] == "customer" for c in cases), "reviewed_customer_count": sum(c["source"] == "customer" and c["reviewed"] for c in cases), "reviewed_customer_test_count": sum(c["source"] == "customer" and c["reviewed"] and c["split"] == "test" for c in cases), "seed_case_count": sum(c["source"] == "seed" and c["split"] == "test" for c in cases), "llm_configured": settings.llm_configured, "llm_model": settings.llm_model, "llm_provider": llm_metadata(settings)["provider"], "embedding_mode": settings.embedding_mode, "embedding_model": settings.embedding_model, "embedding_configured": studio.embeddings.enabled, "embedding_profile": settings.resolved_embedding_profile, "methods": studio.methods(workspace), "imports": studio.store.imports(workspace)}

    @app.get("/v1/methods")
    def methods(workspace: Workspace = "demo"):
        return studio.methods(workspace)

    @app.get("/v1/models")
    def models(workspace: Workspace = "demo"):
        return studio.model_catalog.options(workspace)

    @app.get("/v1/setup", response_model=SetupStatus)
    def setup(workspace: Workspace = "demo", embedding_id: str = Query("default", min_length=1, max_length=200),
              llm_id: str = Query("default", min_length=1, max_length=200)):
        try:
            return setup_status(studio, workspace, embedding_id, llm_id)
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, "Invalid model selection for this workspace.") from exc

    @app.get("/v1/calibrations")
    def calibrations(workspace: Workspace = "demo"):
        ensure(workspace)
        return studio.calibrator.status(workspace)

    @app.post("/v1/calibrations", status_code=202)
    def calibrate(body: CalibrationRequest, workspace: Workspace = "demo"):
        ensure(workspace)
        try:
            job = studio.calibrator.start(workspace, body)
            return {"id": job["id"], "status": job["status"]}
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get("/v1/catalog")
    def catalog(workspace: Workspace = "demo", version: str | None = Query(default=None, min_length=1, max_length=64)):
        ensure(workspace)
        snapshot = studio.store.catalog(workspace, version)
        if not snapshot:
            raise HTTPException(404, "Catalog version not found.")
        return snapshot

    @app.get("/v1/catalog/presets", response_model=list[PresetMetadata])
    def presets():
        return catalog_presets()

    @app.get("/v1/catalog/versions")
    def versions(workspace: Workspace = "demo"):
        ensure(workspace)
        return studio.store.catalog_versions(workspace)

    @app.get("/v1/catalog/audit")
    def catalog_audit(workspace: Workspace = "demo"):
        ensure(workspace)
        return {**audit_catalog(studio.store.catalog(workspace), studio.store.cases(workspace)),
                "seed_migrations": studio.store.migration_reports(workspace)}

    @app.get("/v1/catalog/migrations")
    def catalog_migrations(workspace: Workspace = "demo"):
        ensure(workspace)
        return studio.store.migration_reports(workspace)

    @app.post("/v1/catalog/intents", status_code=201, response_model=IntentSaved)
    def add_intent(body: IntentEdit, workspace: Workspace = "demo"):
        ensure(workspace)
        snapshot = studio.store.catalog(workspace)
        if body.expected_version != snapshot["version"]:
            raise HTTPException(409, "The catalog changed. Refresh it before retrying your edit.")
        ids = {item["intent_id"] for item in snapshot["intents"]}
        if body.intent.intent_id in ids:
            raise HTTPException(422, "This intent ID already exists. Choose a unique ID.")
        if len(snapshot["intents"]) >= 2000:
            raise HTTPException(422, "A catalog can contain at most 2000 intents.")
        validate_intent_references(body.intent, ids)
        replacement = body.intent.model_dump()
        payload = [*snapshot["intents"], replacement]
        try:
            version = studio.store.save_catalog(workspace, payload, expected_version=body.expected_version)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        # The new catalog version gets an index lazily; adding definitions makes no provider call.
        return {"version": version, "intent_count": len(payload), "intent": replacement}

    @app.patch("/v1/catalog/intents/{intent_id}")
    def edit_intent(intent_id: str, body: IntentEdit, workspace: Workspace = "demo"):
        ensure(workspace)
        snapshot = studio.store.catalog(workspace)
        ids = {i["intent_id"] for i in snapshot["intents"]}
        if intent_id not in ids:
            raise HTTPException(404, "Intent not found.")
        if body.expected_version != snapshot["version"]:
            raise HTTPException(409, "The catalog changed. Load the current version and apply the edit again.")
        intent = body.intent
        if intent.intent_id != intent_id or any(i not in ids for i in intent.confusable_with):
            raise HTTPException(422, "Invalid intent ID or confusable intent reference.")
        original = next(i for i in snapshot["intents"] if i["intent_id"] == intent_id)
        validated_original = Intent.model_validate(original)
        for field in ("workflow_id", "required_slots", "slot_questions", "channels", "kind", "domain"):
            if getattr(intent, field) != getattr(validated_original, field):
                raise HTTPException(422, "This editor updates only the intent definition and selection boundaries.")
        replacement = intent.model_dump()
        payload = [replacement if i["intent_id"] == intent_id else i for i in snapshot["intents"]]
        try:
            version = studio.store.save_catalog(workspace, payload, expected_version=body.expected_version)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        # Indexes are versioned and built lazily on the next run; existing jobs keep their snapshot.
        return {"version": version, "intent_count": len(payload), "intent": replacement}

    @app.post("/v1/catalog/import")
    def catalog_import(intents: list[Intent], workspace: Workspace = "demo"):
        if not 1 <= len(intents) <= 2000:
            raise HTTPException(422, "The catalog must contain 1–2000 intents.")
        ids = {i.intent_id for i in intents}
        if len(ids) != len(intents):
            raise HTTPException(422, "Duplicate intent_id found.")
        for intent in intents:
            validate_intent_references(intent, ids)
        payload = [i.model_dump() for i in intents]
        try:
            prepared = studio.prepare_catalog(workspace, intents)
        except ModelUnavailable as exc:
            raise HTTPException(503, "The new index could not be prepared; the active catalog was preserved.") from exc
        version = studio.store.save_catalog(workspace, payload)
        with studio.lock:
            studio.retrievers[(workspace, version, embedding_runtime_key(settings))] = prepared
        return {"version": version, "intent_count": len(intents)}

    @app.post("/v1/cases/import")
    async def cases_import(file: Annotated[UploadFile, File()], workspace: Workspace = "demo"):
        ensure(workspace)
        content = await file.read(100*1024*1024+1)
        await file.close()
        try:
            cases, report = await asyncio.to_thread(import_benchmark, content, Path(file.filename or "benchmark.csv").name)
        except (ValueError, UnicodeDecodeError) as exc:
            raise HTTPException(422, str(exc)) from exc
        studio.store.save_cases(workspace, cases)
        studio.store.save_import(workspace, report)
        return report

    @app.get("/v1/cases")
    def cases(workspace: Workspace = "demo", source: str = "all", q: str = "", reviewed: bool | None = None, split: str | None = None, offset: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=100)):
        ensure(workspace)
        rows = studio.store.cases(workspace, source, reviewed, split=split)
        if q:
            rows = [r for r in rows if q.casefold() in r["question"].casefold()]
        retriever = studio.retriever(workspace)
        selected = []
        for case in rows[offset:offset+limit]:
            suggestion = retriever.search(case["question"], k=3)
            selected.append({**case, "suggestions": [c.model_dump() for c in suggestion]})
        return {"items": selected, "total": len(rows), "offset": offset, "limit": limit}

    @app.get("/v1/cases/{case_id}/versions")
    def case_versions(case_id: str, workspace: Workspace = "demo"):
        ensure(workspace)
        try:
            return studio.store.case_versions(workspace, case_id)
        except KeyError as exc:
            raise HTTPException(404, "Case not found.") from exc

    @app.patch("/v1/cases/{case_id}/review")
    def review_case(case_id: str, review: Review, workspace: Workspace = "demo"):
        ensure(workspace)
        ids = {i["intent_id"] for i in studio.store.catalog(workspace)["intents"]}
        if review.expected_decision == "route" and review.expected_intent_id not in ids:
            raise HTTPException(422, "Select an intent from the catalog for routing.")
        if review.expected_decision != "route" and review.expected_intent_id is not None:
            raise HTTPException(422, "This decision type requires an empty intent label.")
        try:
            return studio.store.review_case(workspace, case_id, review.model_dump())
        except KeyError as exc:
            raise HTTPException(404, "Case not found.") from exc

    @app.post("/v1/sessions", status_code=201)
    def session(workspace: Workspace = "demo"):
        ensure(workspace)
        return studio.store.create_session(workspace)

    @app.post("/v1/route", status_code=202)
    def route(body: RouteRequest, workspace: Workspace = "demo"):
        ensure(workspace)
        previous = studio.store.job(workspace, body.request_id)
        body_hash = fingerprint(body.model_dump(exclude_none=True))
        if previous:
            legacy_body = body.model_dump(exclude_none=True, exclude={"semantic_rejection"})
            legacy_retry = "calibration" not in previous and "semantic_rejection" not in body.model_fields_set and previous.get("request_hash") == fingerprint(legacy_body)
            if previous.get("request_hash") != body_hash and not legacy_retry:
                raise HTTPException(409, "This request_id was already used for a different request.")
            return {"request_id": previous["id"], "status": previous["status"], "catalog_version": previous.get("catalog_version")}
        if not next(m["available"] for m in studio.methods(workspace) if m["id"] == body.method):
            raise HTTPException(409, "This method is not configured. Complete its model connections.")
        try:
            variant = studio.model_catalog.variant(body.method, body.embedding_id, body.llm_id, workspace, body.retrieval_profile)
            catalog = studio.store.catalog(workspace)
            calibration = studio.calibrator.resolve(workspace, variant, catalog["version"], body.semantic_rejection)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        try:
            state = studio.store.claim_turn(workspace, body.session_id, body.turn_revision)
        except KeyError as exc:
            raise HTTPException(404, "Conversation not found.") from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        try:
            studio.store.create_job(workspace, "route", {"request_hash": body_hash, "catalog_version": catalog["version"], "variant": variant.metadata, "calibration": calibration}, body.request_id)
        except sqlite3.IntegrityError as exc:
            raise HTTPException(409, "This request is already being processed.") from exc
        studio.router_pool.submit(studio.run_route, workspace, body, state, catalog["version"], variant, calibration)
        return {"request_id": body.request_id, "status": "queued", "catalog_version": catalog["version"]}

    @app.get("/v1/requests/{request_id}")
    def request_status(request_id: str, workspace: Workspace = "demo"):
        job = studio.store.job(workspace, request_id)
        if not job:
            raise HTTPException(404, "Request not found.")
        return job

    @app.get("/v1/requests/{request_id}/events")
    async def events(request_id: str, request: Request, workspace: Workspace = "demo"):
        if not studio.store.job(workspace, request_id):
            raise HTTPException(404, "Request not found.")
        async def stream():
            last = 0
            while not await request.is_disconnected():
                job = studio.store.job(workspace, request_id)
                for event in job["events"]:
                    if event["id"] > last:
                        yield f"id: {event['id']}\nevent: stage\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
                        last = event["id"]
                if job["status"] in ("completed", "failed", "superseded"):
                    yield f"event: result\ndata: {json.dumps(job, ensure_ascii=False)}\n\n"
                    break
                yield ": heartbeat\n\n"
                await asyncio.sleep(.2)
        return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.post("/v1/evaluations", status_code=202)
    def evaluate(body: EvaluationRequest, workspace: Workspace = "demo"):
        ensure(workspace)
        try:
            job = studio.start_evaluation(workspace, body)
            return {"id": job["id"], "status": job["status"]}
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get("/v1/evaluations")
    def evaluations(workspace: Workspace = "demo"):
        return [{k: v for k, v in j.items() if k not in ("results", "events")} for j in studio.store.jobs(workspace)]

    @app.get("/v1/evaluations/{evaluation_id}")
    def evaluation(evaluation_id: str, workspace: Workspace = "demo"):
        job = studio.store.job(workspace, evaluation_id)
        if not job or job["kind"] != "evaluation":
            raise HTTPException(404, "Evaluation not found.")
        return job

    # A production web build can be served by the same on-prem API process.
    dist = ROOT / "apps/web/dist"
    if dist.is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/")
        def web_index():
            return FileResponse(dist / "index.html")

    return app


app = create_app()
