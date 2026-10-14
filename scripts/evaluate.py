"""Run reviewed cases using the same interface as the UI. Results stay out of git."""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps/api"))
from app.config import Settings
from app.contracts import EvaluationRequest
from app.service import Studio

parser = argparse.ArgumentParser()
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
args = parser.parse_args()
studio = Studio(Settings())
studio.ensure_workspace(args.workspace)
try:
    profiles = json.loads(args.retrieval_profiles.read_text()) if args.retrieval_profiles else None
    job = studio.start_evaluation(args.workspace, EvaluationRequest(source=args.source, methods=args.methods, limit=args.limit, semantic_rejection=args.semantic_rejection, embedding_ids=args.embedding_ids, llm_ids=args.llm_ids, catalog_sizes=args.catalog_sizes, catalog_seed=args.catalog_seed, scale_calibration_source=args.scale_calibration_source, scale_max_oos_false_accept_rate=args.scale_max_oos_far, retrieval_profiles=profiles))
    while job["status"] in ("queued", "running"):
        time.sleep(.2)
        job = studio.store.job(args.workspace, job["id"])
    destination = Path("artifacts/runs") / (job["id"] + ".json")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(job, ensure_ascii=False, indent=2))
    print(json.dumps({"status": job["status"], "file": str(destination), "results": {k: v["metrics"] for k, v in job.get("results", {}).items()}}, ensure_ascii=False, indent=2))
    if job["status"] != "completed":
        raise SystemExit(1)
finally:
    studio.close()
