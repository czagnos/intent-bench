"""Typed persistence results and structural views of legacy case payloads."""
from typing import NotRequired

from typing_extensions import TypedDict

from .case_context import PreTurnData
from .importer import CaseSplit, HistoricalTrace, ImportedCaseData, ImportReportData


class StoredImportReportData(ImportReportData):
    inserted: int
    already_present: int


class ConversationSplitData(TypedDict):
    conversation_id: str
    split: CaseSplit
    updated_count: int


class StoredCaseData(TypedDict):
    case_id: str
    source: str
    dataset_version: str
    reviewed: bool
    split: CaseSplit
    conversation_id: NotRequired[str | None]
    source_dataset_id: NotRequired[str | None]
    source_session_id: NotRequired[str]
    source_message_id: NotRequired[str]
    question: NotRequired[str]
    reference_answer: NotRequired[str]
    source_flag: NotRequired[str]
    historical_trace: NotRequired[HistoricalTrace]
    context: NotRequired[PreTurnData]


def same_imported_turn(stored: StoredCaseData, incoming: ImportedCaseData) -> bool:
    """Compare immutable parser content, excluding file versions and human review."""
    legacy = incoming["source_dataset_id"] is None
    return (
        stored.get("conversation_id") == incoming["conversation_id"]
        and stored.get("source_dataset_id") == incoming["source_dataset_id"]
        and (stored.get("source_session_id") == incoming["source_session_id"]
             or legacy and "source_session_id" not in stored)
        and (stored.get("source_message_id") == incoming["source_message_id"]
             or legacy and "source_message_id" not in stored)
        and stored["source"] == incoming["source"]
        and stored.get("question") == incoming["question"]
        and stored.get("reference_answer", "") == incoming["reference_answer"]
        and stored.get("source_flag", "") == incoming["source_flag"]
        and stored.get("historical_trace", {}) == incoming["historical_trace"]
        and stored.get("context", {}) == incoming["context"]
    )
