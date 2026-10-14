"""Reproducible retrieval-only analysis on repository data. No LLM or label edits."""
import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"apps/api"))
from app.catalog_quality import audit_catalog
from app.catalog_scope import select_catalogs
from app.config import ROOT, Settings
from app.contracts import Intent
from app.retrieval import Embeddings, Retriever
from app.store import fingerprint


def run(args):
    intents = json.loads(args.catalog.read_text())
    cases = [c for c in json.loads(args.cases.read_text()) if c.get("reviewed") and c.get("split") == "test"]
    catalog = {"version": fingerprint(intents), "intents": intents}
    settings = Settings() if args.mode != "lexical" else Settings(_env_file=None, embedding_mode="disabled")
    settings.retrieval_representation = args.representation
    if args.local_files_only:
        if settings.embedding_mode != "local":
            raise ValueError("--local-files-only requires INTENT_EMBEDDING_MODE=local")
        settings.embedding_local_files_only = True
    embeddings = Embeddings(settings)
    output = {"protocol": "repository-retrieval-analysis-v1", "mode": args.mode,
              "embedding": embeddings.metadata if args.mode != "lexical" else None,
              "representation": args.representation, "dataset_fingerprint": fingerprint(cases),
              "case_count": len(cases), "llm_used": False, "accuracy_benchmark": False,
              "audit": audit_catalog(catalog, cases), "results": []}
    for scope in select_catalogs(catalog, args.catalog_sizes, cases, [], 42):
        retriever = Retriever([Intent.model_validate(i) for i in scope["intents"]], scope["version"], embeddings)
        start = time.perf_counter()
        if args.mode != "lexical":
            retriever.prepare_index()
        index_ms = (time.perf_counter()-start)*1000
        records = []
        for case in cases:
            if case.get("expected_decision") != "route":
                continue
            start = time.perf_counter()
            found, trace = retriever.search_with_trace(case["question"], {"semantic": "e5"}.get(args.mode, args.mode), k=40)
            ids = [c.intent_id for c in found]
            records.append({"case_id": case["case_id"], "question": case["question"], "expected_intent_id": case["expected_intent_id"],
                            "rank": ids.index(case["expected_intent_id"])+1 if case["expected_intent_id"] in ids else None,
                            "query_ms": (time.perf_counter()-start)*1000, "candidates": [c.model_dump() for c in found], "trace": trace})
        result = {"catalog": scope["metadata"], "routing_cases": len(records), "index_ms": round(index_ms, 2),
                  "recall": {f"at_{k}": sum(r["rank"] is not None and r["rank"] <= k for r in records)/len(records) if records else None for k in (1, 5, 20, 40)},
                  "query_p95_ms": round(float(np.percentile([r["query_ms"] for r in records], 95)), 2) if records else None,
                  "records": records}
        output["results"].append(result)
        print(json.dumps({k: result[k] for k in ("routing_cases", "recall", "query_p95_ms")} | {"catalog_size": scope["metadata"]["intent_count"]}, ensure_ascii=False), flush=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2))
    print(str(args.output))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=ROOT/"data/demo/catalog.json")
    parser.add_argument("--cases", type=Path, default=ROOT/"data/demo/cases.json")
    parser.add_argument("--mode", choices=["lexical", "semantic", "hybrid"], default="lexical")
    parser.add_argument("--representation", choices=["combined", "separate"], default="combined")
    parser.add_argument("--local-files-only", action="store_true")
    parser.add_argument("--catalog-sizes", type=int, nargs="+", default=[48, 200, 800])
    parser.add_argument("--output", type=Path, default=ROOT/"artifacts/runs/retrieval-analysis.json")
    run(parser.parse_args())
