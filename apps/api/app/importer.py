import csv
import hashlib
import io
import json
from collections import Counter

# Customer exports contain large, multiline JSON traces.
csv.field_size_limit(64 * 1024 * 1024)


def import_benchmark(content: bytes, filename: str = "benchmark.csv") -> tuple[list[dict], dict]:
    if len(content) > 100 * 1024 * 1024:
        raise ValueError("The file exceeds the 100 MB limit.")
    text = content.decode("utf-8-sig")
    # Sniff only the header: multiline JSON and answer prose confuse csv.Sniffer.
    header = text.splitlines()[0] if text else ""
    delimiter = max([";", ",", "\t"], key=header.count)
    reader = csv.DictReader(io.StringIO(text, newline=""), delimiter=delimiter)
    if not reader.fieldnames or "Question" not in reader.fieldnames:
        raise ValueError("The CSV header must contain Question. UTF-8 and comma/semicolon delimiters are supported.")
    dataset = hashlib.sha256(content).hexdigest()[:16]
    cases, seen = [], set()
    report = {"dataset_version": dataset, "filename": filename, "source": "customer", "rows": 0, "imported": 0, "skipped_empty_question": 0, "duplicates": 0, "valid_traces": 0, "invalid_traces": 0, "source_flags": Counter(), "historical_actions": Counter(), "reviewed": 0}
    for row in reader:
        report["rows"] += 1
        question = (row.get("Question") or "").strip()
        if not question:
            report["skipped_empty_question"] += 1
            continue
        if len(question) > 2000:
            raise ValueError(f"The question in row {report['rows']} exceeds the 2000-character limit.")
        source_id = (row.get("BenchmarkSessionId") or str(report["rows"])).strip()
        message_id = (row.get("BenchmarkSessionMessageId") or "1").strip()
        key = (source_id, message_id, question)
        if key in seen:
            report["duplicates"] += 1
            continue
        seen.add(key)
        flag = (row.get("TRUE/FALSE") or "").strip()
        report["source_flags"][flag or "empty"] += 1
        trace = {}
        raw = (row.get("Message Flow") or "").strip()
        if raw:
            try:
                flow = json.loads(raw)
                if not isinstance(flow, dict):
                    raise ValueError("trace must be object")
                report["valid_traces"] += 1
                metadata = flow.get("metadata", {})
                trace["elapsed_seconds"] = metadata.get("total_elapsed_time")
                for step in flow.get("steps", []):
                    if isinstance(step, dict) and step.get("step") == "intent_detection":
                        trace["action"] = step.get("action")
                        report["historical_actions"][trace["action"] or "missing"] += 1
                        break
            except (ValueError, TypeError, AttributeError):
                report["invalid_traces"] += 1
        # Answers, old routing decisions and model reasoning are never retrieval exemplars or gold labels.
        cases.append({"case_id": f"{dataset}-{source_id}-{message_id}", "conversation_id": f"{dataset}-{source_id}", "question": question, "reference_answer": (row.get("Answer") or "")[:20000], "source": "customer", "source_flag": flag, "historical_trace": trace, "dataset_version": dataset, "reviewed": False, "split": "test", "expected_decision": None, "expected_intent_id": None, "context": {}})
    report["imported"] = len(cases)
    report["notes"] = ["TRUE/FALSE is a source field and was not interpreted as an intent accuracy label.", "The legacy action field was not used as a suggestion or gold label.", "Rows with an empty Question were excluded from the case count.", "Imported cases contribute to accuracy only after human review."]
    return cases, report
