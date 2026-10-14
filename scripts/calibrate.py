"""Fit semantic OOS thresholds on the reviewed calibration split, without an LLM."""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps/api"))
from app.config import Settings
from app.contracts import CalibrationRequest
from app.service import Studio


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", choices=["seed", "customer"], default="seed")
    parser.add_argument("--embedding-ids", nargs="+", default=["default"])
    parser.add_argument("--max-oos-far", type=float, default=.05, help="Empirical false acceptance limit, from 0 to 0.5")
    parser.add_argument("--workspace", default="demo")
    args = parser.parse_args()
    studio = Studio(Settings())
    try:
        studio.ensure_workspace(args.workspace)
        options = CalibrationRequest(source=args.source, embedding_ids=args.embedding_ids, max_oos_false_accept_rate=args.max_oos_far)
        job = studio.calibrator.start(args.workspace, options)
        while job["status"] in ("queued", "running"):
            time.sleep(.2)
            job = studio.store.job(args.workspace, job["id"])
        destination = Path("artifacts/calibrations") / (job["id"] + ".json")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(job, ensure_ascii=False, indent=2))
        print(json.dumps({"status": job["status"], "file": str(destination), "results": job["results"]}, ensure_ascii=False, indent=2))
        return 0 if job["status"] == "completed" and all(r["status"] == "completed" for r in job["results"].values()) else 1
    except ValueError as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False))
        return 1
    finally:
        studio.close()


if __name__ == "__main__":
    raise SystemExit(main())
