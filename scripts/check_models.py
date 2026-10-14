"""Check configured model endpoints using fixed demo text; uses API credits."""
import argparse
import json
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps/api"))

from app.config import ROOT, Settings
from app.contracts import Intent
from app.model_catalog import ModelCatalog
from app.retrieval import Embeddings, ModelUnavailable, Retriever
from app.selector import Selector


def call_with_rate_limit_retry(operation, retries: int, state: dict, sleep=time.sleep):
    """Opt-in retries for diagnostic calls only; keep one total five-second wait budget."""
    for attempt in range(retries+1):
        try:
            return operation()
        except ModelUnavailable as exc:
            details = exc.diagnostics
            if details.get("http_status") != 429 and details.get("error_code") != 429:
                raise
            delay = details.get("retry_after_seconds")
            if delay is None:
                delay = .5 * (2**attempt) + random.uniform(0, .25)
            if attempt >= retries or delay > 5 - state["wait_seconds"]:
                # A longer Retry-After is reported, never shortened to fit the budget.
                raise
            sleep(delay)
            state["wait_seconds"] += delay
            state["retry_count"] += 1


def check_models(settings: Settings, embedding=True, llm=True, retry_429=0) -> list[dict]:
    checks = []
    embeddings = Embeddings(settings)
    text = "Kredi kartımın limitini artırmak istiyorum"
    retry_state = {"retry_count": 0, "wait_seconds": 0.0}
    if embedding:
        started = time.perf_counter()
        phase = "passage"
        try:
            passage = call_with_rate_limit_retry(lambda: embeddings.encode(["Kredi kartı limiti değiştirme. Kart limitimi artırmak istiyorum."]), retry_429, retry_state)
            phase = "query"
            query = call_with_rate_limit_retry(lambda: embeddings.encode([text], query=True), retry_429, retry_state)
            if query.shape != passage.shape:
                raise ModelUnavailable("Sorgu ve katalog embedding boyutları farklı.")
            checks.append({"service": "embedding", "ok": True, "model": settings.embedding_model, "dimensions": query.shape[1], "elapsed_ms": round((time.perf_counter()-started)*1000, 2)})
        except ModelUnavailable as exc:
            checks.append({"service": "embedding", "ok": False, "model": settings.embedding_model, "failed_phase": phase, "error": str(exc), "diagnostics": exc.diagnostics})
        checks[-1]["retry_count"] = retry_state["retry_count"]
        checks[-1]["retry_wait_ms"] = round(retry_state["wait_seconds"]*1000, 2)
    if llm:
        started = time.perf_counter()
        before_retries = retry_state.copy()
        try:
            catalog = [Intent.model_validate(i) for i in json.loads((ROOT / "data/demo/catalog.json").read_text())]
            retriever = Retriever(catalog, "connection-check", embeddings)
            candidates = retriever.search(text, mode="lexical", k=20)
            proposal, usage = call_with_rate_limit_retry(lambda: Selector(settings).select(text, {}, candidates, retriever.intents), retry_429, retry_state)
            checks.append({"service": "llm", "ok": True, "model": settings.llm_model, "decision": proposal.decision, "intent_id": proposal.intent_id, "usage": usage, "elapsed_ms": round((time.perf_counter()-started)*1000, 2)})
        except ModelUnavailable as exc:
            checks.append({"service": "llm", "ok": False, "model": settings.llm_model, "error": str(exc), "diagnostics": exc.diagnostics})
        checks[-1]["retry_count"] = retry_state["retry_count"] - before_retries["retry_count"]
        checks[-1]["retry_wait_ms"] = round((retry_state["wait_seconds"] - before_retries["wait_seconds"])*1000, 2)
    return checks


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run real model connection checks with fixed demo text (uses API credits). Does not measure accuracy.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--embedding-only", action="store_true")
    group.add_argument("--llm-only", action="store_true")
    parser.add_argument("--retry-429", type=int, choices=range(3), default=0, help="Additional retries per failed request (0-2); respect Retry-After, at most 5 seconds total waiting.")
    parser.add_argument("--workspace", default="demo", help="Workspace containing registered models.")
    parser.add_argument("--list-models", action="store_true", help="List server model presets without inference calls.")
    parser.add_argument("--embedding-id", default="default", help="Embedding preset ID from --list-models.")
    parser.add_argument("--llm-id", default="default", help="LLM preset ID from --list-models.")
    args = parser.parse_args()
    settings = Settings()
    registry = ModelCatalog(settings)
    if args.list_models:
        print(json.dumps(registry.options(args.workspace), ensure_ascii=False, indent=2))
        sys.exit(0)
    try:
        if not args.llm_only:
            settings = registry.resolve("embedding", args.embedding_id, settings, args.workspace)
        if not args.embedding_only:
            settings = registry.resolve("llm", args.llm_id, settings, args.workspace)
    except ValueError as exc:
        print(json.dumps({"error": str(exc), "accuracy_benchmark": False}, ensure_ascii=False, indent=2))
        sys.exit(1)
    checks = check_models(settings, embedding=not args.llm_only, llm=not args.embedding_only, retry_429=args.retry_429)
    print(json.dumps({"checks": checks, "accuracy_benchmark": False}, ensure_ascii=False, indent=2))
    sys.exit(0 if all(check["ok"] for check in checks) else 1)
