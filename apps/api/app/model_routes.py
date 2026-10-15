"""Model administration and small, explicit inference probes."""
import json
import time
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from .config import ROOT, Settings
from .contracts import Intent
from .model_registry import Kind, Registration
from .model_catalog import model_enabled
from .providers import ModelUnavailable
from .retrieval import Embeddings, Retriever
from .reranker import Reranker
from .selector import Selector

Workspace = Annotated[str, Query(pattern=r"^[a-zA-Z0-9_-]{1,64}$")]


class ProbeResult(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)
    ok: bool
    model: str
    accuracy_benchmark: Literal[False] = False
    elapsed_ms: float
    error: str | None = None
    dimensions: int | None = None
    scores: list[float] | None = None
    decision: str | None = None
    usage: dict[str, int] | None = None


def model_routes(studio):
    router = APIRouter(prefix="/v1")
    registry = studio.model_catalog.registry

    @router.get("/model-registry")
    def records(workspace: Workspace = "demo"):
        return {"items": [registry.public(r) for r in registry.records(workspace)]}

    @router.post("/model-registry", status_code=201)
    def add(body: Registration, workspace: Workspace = "demo"):
        try:
            return registry.save(workspace, body)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @router.patch("/model-registry/{model_id}")
    def edit(model_id: str, body: Registration, workspace: Workspace = "demo"):
        try:
            return registry.save(workspace, body, model_id)
        except KeyError as exc:
            raise HTTPException(404, "Model registration not found.") from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @router.get("/model-discovery/openrouter")
    def discover(kind: Literal["llm", "embedding"] = "llm", q: str = Query("", max_length=200), with_weights: bool = False,
                 refresh: bool = False, offset: int = Query(0, ge=0), limit: int = Query(25, ge=1, le=100)):
        try:
            result = registry.discover(kind, refresh)
        except ModelUnavailable as exc:
            return JSONResponse(status_code=503, content={"detail": str(exc), "diagnostics": exc.diagnostics})
        items = [m for m in result["items"] if (not with_weights or m["weights_url"])
                 and q.casefold() in (m["model"] + " " + m["name"]).casefold()]
        return {**result, "items": items[offset:offset+limit], "total": len(items), "offset": offset, "limit": limit}

    def probe(kind: Kind, settings: Settings) -> ProbeResult:
        started = time.perf_counter()
        model = getattr(settings, kind + "_model")
        try:
            if not model_enabled(kind, settings):
                raise ModelUnavailable("Configure this model connection on the server before testing.")
            embeddings = Embeddings(settings, transport=studio.embeddings.transport)
            result = ProbeResult(ok=True, model=model, elapsed_ms=0)
            if kind == "embedding":
                passage = embeddings.encode(["Change a credit card limit."])
                query = embeddings.encode(["I want to increase my card limit."], query=True)
                if query.shape != passage.shape:
                    raise ModelUnavailable("Query and catalog embedding dimensions differ.")
                result.dimensions = query.shape[1]
            elif kind == "reranker":
                result.scores = Reranker(settings, transport=studio.reranker.transport).scores(
                    "I want to increase my card limit.", ["Change a credit card limit.", "Check an account balance."])
            else:
                # Fixed synthetic examples only; no customer data or vector preparation.
                catalog = [Intent.model_validate(i) for i in json.loads((ROOT / "data/demo/catalog.json").read_text())
                           if i["intent_id"] in ("card.limit.change", "service.human")]
                retriever = Retriever(catalog, "connection-check", embeddings)
                text = "I want to increase my card limit."
                candidates = retriever.search(text, mode="lexical", k=2)
                decision, usage = Selector(settings, transport=studio.selector.transport).select(text, {}, candidates, retriever.intents)
                result.decision, result.usage = decision.decision, usage
            result.elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
            return result
        except (ModelUnavailable, ValueError) as exc:
            return ProbeResult(ok=False, model=model, error=str(exc) if isinstance(exc, ModelUnavailable)
                               else "The provider returned an invalid response. Check model settings.",
                               elapsed_ms=round((time.perf_counter() - started) * 1000, 2))

    @router.post("/models/{kind}/{model_id}/check", response_model=ProbeResult, response_model_exclude_none=True)
    def check_selection(kind: Literal["embedding", "llm"], model_id: str, workspace: Workspace = "demo"):
        try:
            settings = studio.model_catalog.resolve(kind, model_id, workspace=workspace)
        except ValueError as exc:
            raise HTTPException(422, "The selected model is unavailable or invalid for this workspace.") from exc
        return probe(kind, settings)

    @router.post("/model-registry/{model_id}/check", response_model=ProbeResult, response_model_exclude_none=True)
    def check(model_id: str, workspace: Workspace = "demo"):
        record = registry.get(workspace, model_id)
        if not record:
            raise HTTPException(404, "Model registration not found.")
        try:
            settings = studio.model_catalog.resolve(record["kind"], model_id, workspace=workspace)
        except ValueError:
            return ProbeResult(ok=False, model=record["model"], elapsed_ms=0,
                               error="The model connection is unavailable. Check its server configuration.")
        return probe(record["kind"], settings)

    return router
