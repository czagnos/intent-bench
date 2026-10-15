"""Versioned public synthetic samples; loading never accesses private workspaces."""
import csv
import hashlib
import io
import json
from collections import Counter
from collections.abc import Sequence
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from typing_extensions import TypedDict

from .calibration import question_hash
from .case_context import PreTurnContext, PreTurnData, validate_case_context
from .catalog_presets import PresetId, workspace_preset
from .config import ROOT
from .contracts import Intent, Review
from .store import fingerprint

SampleWorkspace = Literal["demo", "airline", "insurance", "ecommerce"]
WORKSPACES: tuple[SampleWorkspace, ...] = ("demo", "airline", "insurance", "ecommerce")
SECTORS: tuple[PresetId, ...] = ("banking", "airline", "insurance", "ecommerce")
SAMPLE_DIRECTORY = ROOT / "data/samples/synthetic-v1"
SampleDecision = Literal["route", "continue", "clarify", "cancel", "out_of_scope", "handoff"]
Challenge = Literal["paraphrase", "negation", "correction", "noisy_transcript", "near_neighbor",
                    "ambiguity", "multiple_intents", "out_of_scope", "handoff", "context"]
CHALLENGES: tuple[Challenge, ...] = ("paraphrase", "negation", "correction", "noisy_transcript",
                                  "near_neighbor", "ambiguity", "multiple_intents", "out_of_scope",
                                  "handoff", "context")
Identity = Annotated[str, Field(min_length=1, max_length=200, pattern=r"^[a-zA-Z0-9_-]+$")]


class SampleModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, revalidate_instances="always")


class SyntheticCase(SampleModel):
    case_id: Identity
    conversation_id: Identity
    turn_id: Identity
    question: str = Field(min_length=1, max_length=2000)
    context: PreTurnContext
    expected_decision: SampleDecision
    expected_intent_id: str | None
    split: Literal["test"]
    challenge: Challenge
    rationale: str = Field(min_length=10, max_length=2000)

    @field_validator("question", "rationale")
    @classmethod
    def trimmed_text(cls, value: str) -> str:
        if not value.strip() or value != value.strip():
            raise ValueError("Sample text must be nonblank without surrounding whitespace.")
        return value


class SyntheticSector(SampleModel):
    schema_version: Literal[1]
    sample_pack: Literal["synthetic-v1"]
    sector: PresetId
    workspace: SampleWorkspace
    language: Literal["en"]
    catalog_fingerprint: str = Field(pattern=r"^[0-9a-f]{16}$")
    cases: list[SyntheticCase] = Field(min_length=48, max_length=48)


class SyntheticManifest(SampleModel):
    schema_version: Literal[1]
    sample_pack: Literal["synthetic-v1"]
    language: Literal["en"]
    license: Literal["Apache-2.0"]
    label_origin: Literal["ai_assisted_synthetic"]
    authorship: str = Field(min_length=20)
    generation_method: str = Field(min_length=20)
    evaluation_method: str = Field(min_length=20)
    limitations: list[str] = Field(min_length=4)
    sectors: list[PresetId] = Field(min_length=4, max_length=4)

    @field_validator("sectors")
    @classmethod
    def fixed_sectors(cls, value: list[PresetId]) -> list[PresetId]:
        if value != list(SECTORS):
            raise ValueError("The manifest must list the four fixed sectors in canonical order.")
        return value


class SyntheticStoredCase(TypedDict):
    case_id: str
    conversation_id: str
    source_dataset_id: str
    source_session_id: str
    source_message_id: str
    question: str
    context: PreTurnData
    expected_decision: SampleDecision
    expected_intent_id: str | None
    split: Literal["test"]
    source: Literal["customer"]
    dataset_version: Literal["synthetic-v1"]
    reviewed: Literal[True]
    label_origin: Literal["ai_assisted_synthetic"]
    challenge: Challenge
    rationale: str


class SampleMetadata(SampleModel):
    sample_pack: Literal["synthetic-v1"]
    sector: PresetId
    workspace: SampleWorkspace
    source_dataset_id: str
    language: Literal["en"]
    license: Literal["Apache-2.0"]
    label_origin: Literal["ai_assisted_synthetic"]
    content_sha256: str
    catalog_fingerprint: str
    available_count: int
    selected_count: int
    selected_case_ids: list[str]
    selected_challenge_counts: dict[Challenge, int]
    selected_decision_counts: dict[SampleDecision, int]


class _Question(BaseModel):
    question: str


def _context_key(context: PreTurnContext) -> str:
    return json.dumps(context.model_dump(exclude_defaults=True), sort_keys=True, ensure_ascii=False)


def validate_sample_sector(pack: SyntheticSector, catalog: Sequence[Intent],
                           excluded_questions: Sequence[str] = ()) -> SyntheticSector:
    """Validate authored annotations and coverage without inference or storage access."""
    pack = SyntheticSector.model_validate(pack)
    if pack.sector != SECTORS[WORKSPACES.index(pack.workspace)]:
        raise ValueError("Sample sector does not match its workspace.")
    if pack.catalog_fingerprint != fingerprint([intent.model_dump() for intent in catalog]):
        raise ValueError("Sample catalog fingerprint does not match the bundled catalog.")
    intents = {intent.intent_id: intent for intent in catalog}
    forbidden = {question_hash(text) for text in excluded_questions}
    forbidden.update(question_hash(text) for intent in catalog for text in intent.examples)
    case_ids: set[str] = set()
    turns: set[tuple[str, str]] = set()
    texts: set[tuple[str, str]] = set()
    prefix = f"synthetic-v1-{pack.sector}-"
    for case in pack.cases:
        if not all(value.startswith(prefix) for value in (case.case_id, case.conversation_id, case.turn_id)):
            raise ValueError("Sample identities must use the pack and sector prefix.")
        if case.case_id in case_ids or (case.conversation_id, case.turn_id) in turns:
            raise ValueError("Duplicate sample case or conversation turn identity.")
        case_ids.add(case.case_id)
        turns.add((case.conversation_id, case.turn_id))
        validate_case_context(case.context, intents)
        Review(expected_decision=case.expected_decision, expected_intent_id=case.expected_intent_id,
               split=case.split)
        if case.expected_decision in ("route", "continue", "cancel"):
            if case.expected_intent_id not in intents:
                raise ValueError("Expected intent is outside the sample catalog.")
            if case.expected_decision in ("continue", "cancel") and (
                not case.context.active_intent or case.expected_intent_id != case.context.active_intent
            ):
                raise ValueError("Continue and cancel labels must match the active intent.")
        elif case.expected_intent_id is not None:
            raise ValueError("Only route, continue and cancel labels may have an expected intent.")
        key = (question_hash(case.question), _context_key(case.context))
        if key in texts:
            raise ValueError("Duplicate sample question and pre-turn context.")
        texts.add(key)
        if key[1] == "{}" and key[0] in forbidden:
            raise ValueError("Context-free sample wording overlaps a catalog example or existing case.")
        if case.challenge == "context" and (key[1] == "{}" or not case.context.messages):
            raise ValueError("Context challenge requires an explicit prior-message snapshot.")
    counts = Counter(case.challenge for case in pack.cases)
    if counts["context"] < 10 or any(counts[challenge] < 2 for challenge in CHALLENGES[:-1]):
        raise ValueError("Sample challenge coverage is incomplete.")
    groups = Counter(case.conversation_id for case in pack.cases)
    if sum(count > 1 for count in groups.values()) < 3:
        raise ValueError("Samples require at least three multi-turn conversation groups.")
    routes = {case.expected_intent_id for case in pack.cases if case.expected_decision == "route"}
    if len(routes) < 10:
        raise ValueError("Samples require at least ten distinct route intents.")
    return pack


def load_sample_pack(pack_id: str, workspace: str) -> SyntheticSector:
    if pack_id != "synthetic-v1" or workspace not in WORKSPACES:
        raise ValueError("Unsupported sample pack or workspace.")
    SyntheticManifest.model_validate_json((SAMPLE_DIRECTORY / "manifest.json").read_text(encoding="utf-8"))
    packs: dict[str, SyntheticSector] = {}
    standalone_questions: set[str] = set()
    for selected_workspace, sector in zip(WORKSPACES, SECTORS, strict=True):
        pack = SyntheticSector.model_validate_json((SAMPLE_DIRECTORY / f"{sector}.json").read_text(encoding="utf-8"))
        if pack.workspace != selected_workspace or pack.sector != sector:
            raise ValueError("Sample artifact identity does not match its fixed filename.")
        preset = workspace_preset(selected_workspace)
        questions = [_Question.model_validate_json(case.payload).question
                     for case in [*preset.cases(), *preset.benchmark_cases()]]
        pack = validate_sample_sector(pack, preset.intents(), questions)
        for case in pack.cases:
            if _context_key(case.context) != "{}":
                continue
            normalized = question_hash(case.question)
            if normalized in standalone_questions:
                raise ValueError("Context-free wording is repeated across sample sectors.")
            standalone_questions.add(normalized)
        packs[selected_workspace] = pack
    return packs[workspace]


def sample_cases(pack: SyntheticSector) -> list[SyntheticStoredCase]:
    """Adapt trusted authored labels for evaluation, without claiming human review."""
    namespace = f"intentbench-{pack.sample_pack}-{pack.sector}"
    return [SyntheticStoredCase(
        case_id=case.case_id, conversation_id=case.conversation_id,
        source_dataset_id=namespace, source_session_id=case.conversation_id, source_message_id=case.turn_id,
        question=case.question, context=case.context.as_data(), expected_decision=case.expected_decision,
        expected_intent_id=case.expected_intent_id, split=case.split, source="customer",
        dataset_version=pack.sample_pack, reviewed=True, label_origin="ai_assisted_synthetic",
        challenge=case.challenge, rationale=case.rationale,
    ) for case in pack.cases]


def sample_metadata(pack: SyntheticSector, limit: int) -> SampleMetadata:
    """Describe the exact insertion-ordered cohort selected before repeat expansion."""
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ValueError("Sample limit must be a positive integer.")
    selected = pack.cases[:limit]
    canonical = json.dumps(pack.model_dump(), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return SampleMetadata(
        sample_pack=pack.sample_pack, sector=pack.sector, workspace=pack.workspace,
        source_dataset_id=f"intentbench-{pack.sample_pack}-{pack.sector}", language=pack.language,
        license="Apache-2.0", label_origin="ai_assisted_synthetic",
        content_sha256=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        catalog_fingerprint=pack.catalog_fingerprint, available_count=len(pack.cases),
        selected_count=len(selected), selected_case_ids=[case.case_id for case in selected],
        selected_challenge_counts=dict(sorted(Counter(case.challenge for case in selected).items())),
        selected_decision_counts=dict(sorted(Counter(case.expected_decision for case in selected).items())),
    )


def render_sample_csv(pack: SyntheticSector) -> str:
    """Export transcript inputs only; ordinary import always requires independent review."""
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(["SourceDatasetId", "BenchmarkSessionId", "BenchmarkSessionMessageId", "Question",
                     "Answer", "Message Flow", "TRUE/FALSE", "Context", "Split", "Provenance"])
    for case in pack.cases:
        context = json.dumps(case.context.as_data(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        writer.writerow([f"intentbench-{pack.sample_pack}-{pack.sector}", case.conversation_id, case.turn_id,
                         case.question, "", "", "", context, case.split,
                         "AI-assisted synthetic development sample; not a real transcript. Review before evaluation."])
    return output.getvalue()
