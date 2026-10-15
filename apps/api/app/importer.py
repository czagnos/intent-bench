"""CSV transcript parsing without inference, review, or persistence side effects."""
import csv
import hashlib
import io
import json
from collections import Counter
from typing import Annotated, Literal, cast

from typing_extensions import TypedDict

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .case_context import PreTurnContext, PreTurnData

# Customer exports contain large, multiline JSON traces.
csv.field_size_limit(64 * 1024 * 1024)
CaseSplit = Literal["dev", "calibration", "test"]
SourceId = Annotated[str, Field(strict=True, min_length=1, max_length=200)]


class SourceIdentifiers(BaseModel):
    source_dataset_id: SourceId | None = None
    source_session_id: SourceId
    source_message_id: SourceId


class HistoricalTrace(TypedDict, total=False):
    elapsed_seconds: float | int | str | None
    action: str | None


class ImportedCaseData(TypedDict):
    case_id: str
    conversation_id: str
    source_dataset_id: str | None
    source_session_id: str
    source_message_id: str
    question: str
    reference_answer: str
    source: Literal["customer"]
    source_flag: str
    historical_trace: HistoricalTrace
    dataset_version: str
    reviewed: Literal[False]
    split: CaseSplit
    split_explicit: bool
    expected_decision: None
    expected_intent_id: None
    context: PreTurnData


class ParsedTranscriptCase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    case_id: str
    conversation_id: str
    source_dataset_id: str | None
    source_session_id: str
    source_message_id: str
    question: str
    reference_answer: str
    source: Literal["customer"] = "customer"
    source_flag: str
    historical_trace: HistoricalTrace
    dataset_version: str
    reviewed: Literal[False] = False
    split: CaseSplit = "test"
    split_explicit: bool = False
    expected_decision: None = None
    expected_intent_id: None = None
    context: PreTurnContext = Field(default_factory=PreTurnContext)

    def as_data(self) -> ImportedCaseData:
        data = cast(ImportedCaseData, self.model_dump(exclude={"context"}))
        data["context"] = self.context.as_data()
        return data


class ImportReportData(TypedDict):
    dataset_version: str
    filename: str
    source: Literal["customer"]
    rows: int
    imported: int
    skipped_empty_question: int
    duplicates: int
    valid_traces: int
    invalid_traces: int
    source_flags: dict[str, int]
    historical_actions: dict[str, int]
    reviewed: int
    notes: list[str]


class LegacyMetadata(BaseModel):
    total_elapsed_time: float | int | str | None = None


class LegacyStep(BaseModel):
    step: str | None = None
    action: str | None = None


class LegacyFlow(BaseModel):
    metadata: LegacyMetadata = Field(default_factory=LegacyMetadata)
    steps: list[LegacyStep] = Field(default_factory=list)

    @field_validator("steps", mode="before")
    @classmethod
    def first_intent_step(cls, value: object) -> object:
        # Legacy extraction skips opaque/unrelated steps and stops at the first action.
        if isinstance(value, list):
            for step in value:
                if isinstance(step, dict) and step.get("step") == "intent_detection":
                    return [step]
            return []
        return value


def _stable_identity(kind: str, parts: tuple[str, ...]) -> str:
    canonical = json.dumps(parts, ensure_ascii=False, separators=(",", ":"))
    return kind + "-" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def import_benchmark(content: bytes, filename: str = "benchmark.csv") -> tuple[list[ImportedCaseData], ImportReportData]:
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
    seen: dict[str, ParsedTranscriptCase] = {}
    conversation_splits: dict[str, CaseSplit] = {}
    report: ImportReportData = {
        "dataset_version": dataset, "filename": filename, "source": "customer", "rows": 0,
        "imported": 0, "skipped_empty_question": 0, "duplicates": 0, "valid_traces": 0,
        "invalid_traces": 0, "source_flags": Counter(), "historical_actions": Counter(), "reviewed": 0,
        "notes": [
            "TRUE/FALSE is a source field and was not interpreted as an intent accuracy label.",
            "The legacy action field was not used as a suggestion or gold label.",
            "Rows with an empty Question were excluded from the case count.",
            "Imported cases contribute to accuracy only after human review.",
        ],
    }
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
        raw_namespace = row.get("SourceDatasetId") or ""
        source_dataset_id = raw_namespace.strip() or None
        raw_context = (row.get("Context") or "").strip()
        if raw_namespace or raw_context:
            identity = SourceIdentifiers(
                source_dataset_id=raw_namespace.strip() if raw_namespace else None,
                source_session_id=(row.get("BenchmarkSessionId") or "").strip(),
                source_message_id=(row.get("BenchmarkSessionMessageId") or "").strip(),
            )
            source_id, message_id = identity.source_session_id, identity.source_message_id
            source_dataset_id = identity.source_dataset_id
        if source_dataset_id:
            conversation_id = _stable_identity("conversation", (source_dataset_id, source_id))
            case_id = _stable_identity("transcript", (source_dataset_id, source_id, message_id))
        else:
            conversation_id = f"{dataset}-{source_id}"
            case_id = f"{dataset}-{source_id}-{message_id}"
        context = PreTurnContext.model_validate_json(raw_context) if raw_context else PreTurnContext()
        raw_split = (row.get("Split") or "").strip()
        flag = (row.get("TRUE/FALSE") or "").strip()
        trace: HistoricalTrace = {}
        raw = (row.get("Message Flow") or "").strip()
        trace_status: Literal["absent", "valid", "invalid"] = "absent"
        if raw:
            try:
                flow = LegacyFlow.model_validate_json(raw)
                trace_status = "valid"
                trace["elapsed_seconds"] = flow.metadata.total_elapsed_time
                for step in flow.steps:
                    if step.step == "intent_detection":
                        trace["action"] = step.action
                        break
            except ValueError:
                trace_status = "invalid"
        # Answers, old routing decisions and model reasoning are never exemplars or gold labels.
        parsed = ParsedTranscriptCase(
            case_id=case_id, conversation_id=conversation_id, source_dataset_id=source_dataset_id,
            source_session_id=source_id, source_message_id=message_id, question=question,
            reference_answer=(row.get("Answer") or "")[:20000], source_flag=flag,
            historical_trace=trace, dataset_version=dataset, context=context,
            split=raw_split or "test", split_explicit=bool(raw_split),
        )
        if parsed.split_explicit:
            if conversation_id in conversation_splits and conversation_splits[conversation_id] != parsed.split:
                raise ValueError(f"The conversation in row {report['rows']} has conflicting explicit splits.")
            conversation_splits[conversation_id] = parsed.split
        previous = seen.get(case_id)
        if previous is not None:
            compared_fields = {"split", "split_explicit"}
            if (previous.model_dump(exclude=compared_fields) != parsed.model_dump(exclude=compared_fields)
                    or previous.context.as_data() != parsed.context.as_data()):
                raise ValueError(f"Conflicting source turn identity in row {report['rows']}.")
            # An implicit default must not hide a duplicate's explicit split choice.
            if parsed.split_explicit:
                previous.split = parsed.split
                previous.split_explicit = True
            report["duplicates"] += 1
            continue
        seen[case_id] = parsed
        report["source_flags"][flag or "empty"] += 1
        if trace_status == "valid":
            report["valid_traces"] += 1
            if "action" in trace:
                report["historical_actions"][trace["action"] or "missing"] += 1
        elif trace_status == "invalid":
            report["invalid_traces"] += 1
    cases = [parsed.as_data() for parsed in seen.values()]
    report["imported"] = len(cases)
    return cases, report
