"""Model administration and small, explicit inference probes."""
import json
import time
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse

from .config import ROOT
from .contracts import Intent
from .model_registry import Kind, Registration
from .providers import ModelUnavailable
from .retrieval import Embeddings, Retriever
from .reranker import Reranker
from .selector import Selector

Workspace = Annotated[str, Query(pattern=r"^[a-zA-Z0-9_-]{1,64}$")]


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
            raise HTTPException(404, "Model kaydı bulunamadı.") from exc
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

    @router.post("/model-registry/{model_id}/check")
    def check(model_id: str, workspace: Workspace = "demo"):
        record = registry.get(workspace, model_id)
        if not record:
            raise HTTPException(404, "Model kaydı bulunamadı.")
        started = time.perf_counter()
        try:
            settings = studio.model_catalog.resolve(record["kind"], model_id, workspace=workspace)
            embeddings = Embeddings(settings, transport=studio.embeddings.transport)
            if record["kind"] == "embedding":
                passage = embeddings.encode(["Kredi kartı limiti değiştirme."])
                query = embeddings.encode(["Kart limitimi artırmak istiyorum."], query=True)
                if query.shape != passage.shape:
                    raise ModelUnavailable("Sorgu ve katalog embedding boyutları farklı.")
                details = {"dimensions": query.shape[1]}
            elif record["kind"] == "reranker":
                values = Reranker(settings, transport=studio.reranker.transport).scores(
                    "Kart limitimi artırmak istiyorum.", ["Kredi kartı limiti değiştirme.", "Hesap bakiyesi sorgulama."])
                details = {"scores": values}
            else:
                # Fixed seed examples only; no customer records and no vector-index preparation.
                catalog = [Intent.model_validate(i) for i in json.loads((ROOT / "data/demo/catalog.json").read_text())
                           if i["intent_id"] in ("card.limit.change", "service.human")]
                retriever = Retriever(catalog, "connection-check", embeddings)
                text = "Kart limitimi artırmak istiyorum."
                candidates = retriever.search(text, mode="lexical", k=2)
                decision, usage = Selector(settings, transport=studio.selector.transport).select(text, {}, candidates, retriever.intents)
                # Connectivity/contract validation, deliberately not an accuracy score.
                details = {"decision": decision.decision, "usage": usage}
            return {"ok": True, "model": record["model"], "accuracy_benchmark": False,
                    "elapsed_ms": round((time.perf_counter() - started) * 1000, 2), **details}
        except (ModelUnavailable, ValueError) as exc:
            return {"ok": False, "model": record["model"], "accuracy_benchmark": False,
                    "error": str(exc), "elapsed_ms": round((time.perf_counter() - started) * 1000, 2)}

    return router
