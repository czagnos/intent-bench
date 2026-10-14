"""Deterministic review aids. Findings do not change labels or accuracy denominators."""
import unicodedata
from collections import Counter, defaultdict

from .retrieval import tokens
from .store import fingerprint
from .demo_taxonomy import PARENTS

# Explicitly scoped to the illustrative generator's product/action taxonomy.
# These are possible scope overlaps, never an automatic equivalence relation.
DEMO_PARENTS = PARENTS


def text_key(value):
    return " ".join(unicodedata.normalize("NFC", value).casefold().split())


def audit_catalog(catalog, cases):
    intents = {i["intent_id"]: i for i in catalog["intents"]}
    examples, questions = defaultdict(set), defaultdict(list)
    issues = []
    for iid, intent in intents.items():
        for example in intent["examples"]:
            examples[text_key(example)].add(iid)
    for case in cases:
        questions[text_key(case["question"])].append(case)
    def add(kind, ids, matched=(), example=None):
        ids = sorted(set(ids))
        issues.append({"id": fingerprint([kind, ids, example])[:16], "kind": kind,
                       "intent_ids": ids, "intent_names": [intents[i]["name"] for i in ids if i in intents],
                       "documented_rule": bool(ids) and all(bool(intents[i].get("selection_rule")) for i in ids if i in intents),
                       "cases": [{"case_id": c["case_id"], "question": c["question"], "split": c["split"],
                                  "expected_intent_id": c.get("expected_intent_id")} for c in matched[:10]],
                       "example": example})
    for example, ids in examples.items():
        if len(ids) > 1:
            add("duplicate_example", ids, questions.get(example, []), example)
        if example in questions:
            add("example_test_overlap", ids, questions[example], example)
    for key, group in questions.items():
        reviewed = [c for c in group if c.get("reviewed")]
        labels = {(c.get("expected_decision"), c.get("expected_intent_id"),
                   fingerprint(c.get("context") or {})) for c in reviewed}
        contexts = {label[2] for label in labels}
        if any(len({(d, i) for d, i, context in labels if context == current}) > 1 for current in contexts):
            add("conflicting_labels", [i for _, i, _ in labels if i], reviewed, key)
        if len({c["split"] for c in group}) > 1:
            add("split_overlap", [c["expected_intent_id"] for c in reviewed if c.get("expected_intent_id")], group, key)
    for iid, intent in intents.items():
        parts = iid.split(".")
        if len(parts) != 4 or parts[0] != "bank":
            continue
        parent = DEMO_PARENTS.get((parts[1], parts[3]))
        if parent not in intents:
            continue
        product = intent["name"].split(" - ")[0]
        distinctive = set(tokens(product)) - {"hesabi", "karti", "transferi", "kredisi", "mevduat", "bankacilik"}
        matched = [c for c in cases if c.get("expected_intent_id") == iid or
                   (c.get("expected_intent_id") == parent and distinctive
                    and distinctive <= set(tokens(c["question"])))]
        add("demo_scope_overlap", [parent, iid], matched)
    tested = {c.get("expected_intent_id") for c in cases if c.get("reviewed") and c["split"] == "test" and c.get("expected_decision") == "route"}
    issues.sort(key=lambda item: (not bool(item["cases"]), item["documented_rule"], item["kind"], item["id"]))
    return {"protocol": "catalog-review-v1", "catalog_version": catalog["version"],
            "case_fingerprint": fingerprint(cases), "intent_count": len(intents), "case_count": len(cases),
            "tested_intent_count": len(tested & intents.keys()),
            "untested_intent_count": len(intents.keys()-tested),
            "counts": dict(Counter(i["kind"] for i in issues)), "issues": issues,
            "automatic_label_changes": False, "semantic_audit": False}
