"""Run reviewed cases using the same interface as the UI. Results stay out of git."""
import argparse
import json
import signal
import sqlite3
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from types import FrameType
from typing import TypedDict

import httpx
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps/api"))
from app.config import Settings
from app.contracts import EvaluationRequest
from app.evaluation_types import EvaluationMetrics
from app.execution import ExecutionLimits
from app.service import Studio


class EvaluationSummary(TypedDict):
    status: str
    file: str
    results: dict[str, EvaluationMetrics]


class CommandError(TypedDict):
    error: str


def main(argv: Sequence[str] | None = None, *, settings: Settings | None = None,
         transport: httpx.BaseTransport | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", choices=["seed", "customer", "all"], default="seed")
    parser.add_argument("--methods", nargs="+", choices=["lexical", "e5", "hybrid_llm"], default=["lexical"])
    parser.add_argument("--semantic-rejection", choices=["calibrated", "off"], default="calibrated")
    parser.add_argument("--embedding-ids", nargs="+", default=["default"])
    parser.add_argument("--llm-ids", nargs="+", default=["default"])
    parser.add_argument("--catalog-sizes", type=int, nargs="+", help="Compare these catalog sizes on the same fixed cases")
    parser.add_argument("--catalog-seed", type=int, default=42)
    parser.add_argument("--scale-calibration-source", choices=["seed", "customer"], default="seed")
    parser.add_argument("--scale-max-oos-far", type=float, default=.05)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--workspace", default="demo")
    parser.add_argument("--retrieval-profiles", type=Path, help="JSON array of retrieval strategy configurations (hybrid_llm only)")
    parser.add_argument("--repetitions", type=int, default=1, help="Sequential frozen-cohort repeats (1–5).")
    parser.add_argument("--max-provider-requests", type=int, help="Maximum outbound inference attempts (0–100000).")
    parser.add_argument("--max-duration-seconds", type=float, help="Cooperative duration limit including preparation (1–86400 seconds).")
    parser.add_argument("--max-reported-cost-usd", type=float, help="Soft OpenRouter reported USD threshold (>0–10000); in-flight work may exceed it.")
    args = parser.parse_args(argv)
    studio = Studio(settings or Settings())
    interrupted = False

    def request_cancel(signum: int, frame: FrameType | None) -> None:
        nonlocal interrupted
        # Defer SQLite work to the poll loop; repeated signals cannot interrupt saving or shutdown.
        interrupted = True

    previous_handler = signal.signal(signal.SIGINT, request_cancel)
    exit_code = 1
    try:
        profiles = json.loads(args.retrieval_profiles.read_text()) if args.retrieval_profiles else None
        options = EvaluationRequest(
            source=args.source, methods=args.methods, limit=args.limit, semantic_rejection=args.semantic_rejection,
            embedding_ids=args.embedding_ids, llm_ids=args.llm_ids, catalog_sizes=args.catalog_sizes,
            catalog_seed=args.catalog_seed, scale_calibration_source=args.scale_calibration_source,
            scale_max_oos_false_accept_rate=args.scale_max_oos_far, retrieval_profiles=profiles,
            repetitions=args.repetitions, execution_limits=ExecutionLimits(
                max_provider_requests=args.max_provider_requests, max_duration_seconds=args.max_duration_seconds,
                max_reported_cost_usd=args.max_reported_cost_usd,
            ),
        )
        studio.embeddings.transport = studio.selector.transport = studio.reranker.transport = transport
        studio.ensure_workspace(args.workspace)
        job = studio.start_evaluation(args.workspace, options)
        cancellation_sent = False
        while job["status"] in ("queued", "running"):
            if interrupted and not cancellation_sent:
                job = studio.store.cancel_evaluation(args.workspace, job["id"])
                cancellation_sent = True
                print("Cancellation requested; waiting for in-flight work before saving results.", file=sys.stderr)
                if job["status"] not in ("queued", "running"):
                    break
            time.sleep(.2)
            job = studio.store.job(args.workspace, job["id"])
        destination = Path("artifacts/runs") / (job["id"] + ".json")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
        summary: EvaluationSummary = {"status": job["status"], "file": str(destination),
                                      "results": {key: value["metrics"] for key, value in job.get("results", {}).items()}}
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        exit_code = {"completed": 0, "stopped": 2, "cancelled": 130, "failed": 1}[job["status"]]
    except ValidationError as exc:
        error: CommandError = {"error": "Invalid evaluation options: " + "; ".join(
            ".".join(str(part) for part in item["loc"]) + ": " + item["msg"] for item in exc.errors(include_input=False)
        )}
        print(json.dumps(error), file=sys.stderr)
    except ValueError as exc:
        error = {"error": str(exc)}
        print(json.dumps(error), file=sys.stderr)
    except (OSError, sqlite3.Error):
        error = {"error": "Local evaluation data or output unavailable; check the data directory and permissions."}
        print(json.dumps(error), file=sys.stderr)
    finally:
        try:
            studio.close()
        finally:
            signal.signal(signal.SIGINT, previous_handler)
    return 130 if interrupted else exit_code


if __name__ == "__main__":
    raise SystemExit(main())
