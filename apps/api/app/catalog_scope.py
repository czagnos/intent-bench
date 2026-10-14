"""Reproducible, nested catalog subsets for fixed-cohort scaling experiments."""
import json
from collections import defaultdict

from .config import ROOT
from .store import fingerprint

PROTOCOL = "fixed-cohort-nested-domain-v2"


def core_ids():
    return {i["intent_id"] for i in json.loads((ROOT / "data/demo/catalog-core.json").read_text())}


def required_ids(cases):
    ids = set()
    for case in cases:
        if case.get("expected_intent_id"):
            ids.add(case["expected_intent_id"])
        context = case.get("context") or {}
        if context.get("active_intent"):
            ids.add(context["active_intent"])
        for option in context.get("clarification_options", []):
            ids.add(option["intent_id"] if isinstance(option, dict) else option)
    return ids


def select_catalogs(catalog, sizes, cases, calibration_cases=(), seed=42):
    intents = catalog["intents"]
    ids = {i["intent_id"] for i in intents}
    required = required_ids([*cases, *calibration_cases])
    if required - ids:
        raise ValueError("Test veya kalibrasyon için gereken intent aktif katalogda yok.")
    # Labels and dialogue targets must survive every scope. Core intents fill the remaining
    # budget first; making all 48 mandatory would exclude every new product-specific label.
    policy_ids = {"card.cancel", "card.temporary_block", "service.human"}
    protected = (policy_ids & ids) | required
    preferred_ids = core_ids() - protected
    preferred = [i["intent_id"] for i in intents if i["intent_id"] in preferred_ids]
    sizes = sorted(set(sizes or [len(intents)]))
    if any(size < len(protected) or size > len(intents) for size in sizes):
        raise ValueError(f"Katalog büyüklüğü {len(protected)} ile {len(intents)} arasında olmalı. Test, bağlam ve kalibrasyon intentleri korunur.")
    domains = defaultdict(list)
    for intent in intents:
        if intent["intent_id"] not in protected and intent["intent_id"] not in preferred:
            domains[intent["domain"]].append(intent["intent_id"])
    for domain in domains:
        domains[domain].sort(key=lambda iid: fingerprint([seed, iid]))
    remaining = list(preferred)
    for rank in range(max(map(len, domains.values()), default=0)):
        for domain in sorted(domains):
            if rank < len(domains[domain]):
                remaining.append(domains[domain][rank])
    scopes = []
    for size in sizes:
        selected = protected | set(remaining[:size-len(protected)])
        # Preserve catalog order and content; absent confusable candidates are already ignored by retrieval.
        subset = [i for i in intents if i["intent_id"] in selected]
        version = fingerprint(subset)
        scopes.append({"version": version, "intents": subset, "metadata": {
            "version": version, "parent_version": catalog["version"], "intent_count": size,
            "available_intent_count": len(intents), "protected_intent_count": len(protected),
            "intent_ids": [i["intent_id"] for i in subset], "selection_seed": seed, "selection_protocol": PROTOCOL,
        }})
    return scopes
