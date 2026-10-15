import math
from collections import Counter

import numpy as np


def diagnose(record):
    """Post-hoc only. Gold labels never enter retrieval, reranking or selection."""
    trace = record.get("retrieval_trace") or {}
    expected = record.get("expected_intent_id") if record["expected_decision"] == "route" else None
    ranks = {stage: (trace.get(stage, []).index(expected)+1 if expected and expected in trace.get(stage, []) else None)
             for stage in ("semantic", "lexical", "fusion", "pool", "final")}
    if record["correct"]:
        category = "correct"
    elif record["decision"] == "error":
        category = "technical_error"
    elif not trace.get("executed"):
        category = "context_decision" if "executed" in trace else "untracked"
    elif expected:
        if not ranks["pool"]:
            category = "fusion_cutoff" if ranks["semantic"] or ranks["lexical"] else "retrieval_miss"
        elif not ranks["final"]:
            category = "reranker_cutoff" if trace.get("reranker_used") else "candidate_cutoff"
        elif trace.get("proposal_decision") == "route" and trace.get("proposal_intent_id") == expected:
            category = "policy_decision"
        elif record["decision"] == "clarify":
            category = "unnecessary_clarification"
        elif record["decision"] == "out_of_scope":
            category = "false_rejection"
        else:
            category = "selection_error"
    elif record["expected_decision"] == "out_of_scope" and record["decision"] == "route":
        category = "oos_false_accept"
    else:
        category = "decision_error"
    return {"category": category, "expected_ranks": ranks, "error_stage": record.get("error_stage")}


def stage_quality(records):
    routing = [r for r in records if r["expected_decision"] == "route"]
    traced = [r for r in routing if r.get("retrieval_trace", {}).get("completed")]
    count = len(traced)
    def ratio(n, d):
        return n/d if d else None
    final_hits = [r for r in traced if r["expected_intent_id"] in r["retrieval_trace"].get("final", [])]
    stages = {}
    for stage in ("semantic", "lexical", "pool", "final"):
        relevant = traced if stage in ("pool", "final") else [r for r in traced if (
            r["retrieval_trace"].get("source") in (("e5", "hybrid") if stage == "semantic" else ("lexical", "hybrid"))
            or (not r["retrieval_trace"].get("source") and r["retrieval_trace"].get(stage)))]
        numerator = sum(r["expected_intent_id"] in r["retrieval_trace"].get(stage, []) for r in relevant)
        stages[stage] = {"hits": numerator, "total": len(relevant), "recall": ratio(numerator, len(relevant))}
    return {"protocol": "routing-stage-quality-v1", "routing_total": len(routing), "retrieval_completed": count,
            "context_bypasses": sum(bool(r.get("retrieval_trace", {}).get("context_bypass")) for r in routing),
            "retrieval_incomplete": sum("retrieval_trace" in r and not r["retrieval_trace"].get("completed") and not r["retrieval_trace"].get("context_bypass") for r in routing),
            "stages": stages,
            "candidate_conditioned_accuracy": ratio(sum(r["correct"] for r in final_hits), len(final_hits)),
            "candidate_conditioned_correct": sum(r["correct"] for r in final_hits),
            "candidate_conditioned_total": len(final_hits),
            "categories": dict(Counter(diagnose(r)["category"] for r in records)),
            "technical_stages": dict(Counter(r.get("error_stage") or "unknown" for r in records if r["decision"] == "error"))}


def wilson(correct: int, total: int):
    if not total:
        return None
    p, z = correct/total, 1.95996398454
    center = (p+z*z/(2*total))/(1+z*z/total)
    radius = z*math.sqrt(p*(1-p)/total+z*z/(4*total*total))/(1+z*z/total)
    return [max(0, center-radius), min(1, center+radius)]


def summarize(records: list[dict], k=20):
    total = len(records)
    routing = [r for r in records if r["expected_decision"] == "route"]
    routed = [r for r in records if r["decision"] == "route"]
    oos = [r for r in records if r["expected_decision"] == "out_of_scope"]
    correct_routing = sum(r["decision"] == "route" and r["intent_id"] == r["expected_intent_id"] for r in routing)
    correct = sum(r["correct"] for r in records)
    labels = sorted({r["expected_intent_id"] for r in routing})
    f1s, per_intent = [], []
    for label in labels:
        tp = sum(r["expected_intent_id"] == label and r["intent_id"] == label and r["decision"] == "route" for r in routing)
        fp = sum((r["expected_decision"] != "route" or r["expected_intent_id"] != label) and r["intent_id"] == label and r["decision"] == "route" for r in records)
        fn = sum(r["expected_intent_id"] == label and not (r["intent_id"] == label and r["decision"] == "route") for r in routing)
        f1 = 2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else 0
        f1s.append(f1)
        per_intent.append({"intent_id": label, "support": tp+fn, "recall": tp/(tp+fn) if tp+fn else None, "f1": f1})
    durations = [r["total_ms"] for r in records]
    confusions = Counter((r["expected_intent_id"] or r["expected_decision"], r["intent_id"] if r["decision"] == "route" else r["decision"]) for r in records if not r["correct"])
    result = {"total": total, "correct": correct, "routing_total": len(routing), "routing_correct": correct_routing, "routing_accuracy": correct_routing/len(routing) if routing else None, "decision_accuracy": correct/total if total else None, "routing_accuracy_ci95": wilson(correct_routing, len(routing)), "macro_f1": sum(f1s)/len(f1s) if f1s else None, "recall_at_k": sum(r["candidate_hit"] for r in routing)/len(routing) if routing else None, "k": k, "coverage": len(routed)/total if total else None, "routed_precision": sum(r["correct"] for r in routed)/len(routed) if routed else None, "clarification_rate": sum(r["decision"] == "clarify" for r in records)/total if total else None, "oos_false_accept_rate": sum(r["decision"] == "route" for r in oos)/len(oos) if oos else None, "in_scope_false_reject_rate": sum(r["decision"] == "out_of_scope" for r in routing)/len(routing) if routing else None, "oos_total": len(oos), "errors": sum(r["decision"] == "error" for r in records), "latency_ms": {f"p{p}": float(np.percentile(durations, p)) if durations else None for p in (50, 95, 99)}, "intent_count": len(labels), "per_intent": per_intent, "confusions": [{"expected": e, "predicted": p, "count": n} for (e, p), n in confusions.most_common(12)]}
    result["stage_latency_ms"] = {}
    if any("retrieval_trace" in r for r in records):
        result["stage_quality"] = stage_quality(records)
    for stage in ("retrieval", "reranking", "selection", "policy"):
        values = [r["timings_ms"][stage] for r in records if stage in r.get("timings_ms", {})]
        result["stage_latency_ms"][stage] = {"count": len(values), "p50": float(np.percentile(values, 50)) if values else None, "p95": float(np.percentile(values, 95)) if values else None}
    result["usage"] = {}
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        values = [(r.get("usage") or {}).get(key) for r in records]
        result["usage"][key] = sum(v for v in values if isinstance(v, (int, float)) and math.isfinite(v) and v >= 0)
    return result
