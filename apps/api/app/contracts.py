from typing import Annotated, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Method = Literal["lexical", "e5", "hybrid_llm"]
ModelId = Annotated[str, Field(pattern=r"^[a-zA-Z0-9_.-]{1,80}$")]
DecisionType = Literal["route", "continue", "clarify", "cancel", "out_of_scope", "handoff", "error"]


class Intent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    intent_id: str = Field(pattern=r"^[a-z][a-z0-9_.]{1,99}$")
    name: str = Field(min_length=2, max_length=160)
    domain: str = Field(min_length=2, max_length=80)
    description: str = Field(min_length=5, max_length=1600)
    examples: list[str] = Field(min_length=1, max_length=30)
    exclusions: list[str] = Field(default_factory=list, max_length=20)
    confusable_with: list[str] = Field(default_factory=list, max_length=20)
    workflow_id: str = Field(pattern=r"^[a-z][a-z0-9_.]{1,119}$")
    required_slots: list[str] = Field(default_factory=list, max_length=10)
    slot_questions: dict[str, str] = Field(default_factory=dict)
    channels: list[str] = ["chat", "voice"]
    kind: Literal["information", "transaction"] = "information"
    selection_rule: str = Field(default="", max_length=800)


class RetrievalProfile(BaseModel):
    """An experiment recipe. Credentials and arbitrary endpoints cannot enter requests."""
    model_config = ConfigDict(extra="forbid")
    id: ModelId = "hybrid"
    name: str = Field(default="Mevcut hibrit", min_length=1, max_length=100)
    source: Literal["hybrid", "semantic"] = "hybrid"
    representation: Literal["combined", "separate"] = "combined"
    source_k: int = Field(default=40, ge=2, le=100)
    pool_k: int = Field(default=20, ge=2, le=100)
    candidate_k: int = Field(default=20, ge=2, le=40)
    semantic_weight: float = Field(default=.5, gt=0, lt=1)
    reranker_id: ModelId | None = None

    @model_validator(mode="after")
    def budgets(self):
        if self.candidate_k > self.pool_k or self.pool_k > self.source_k:
            raise ValueError("Aday sayısı ≤ havuz sayısı ≤ kaynak arama sayısı olmalı.")
        return self


class IntentEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: str = Field(min_length=1, max_length=64)
    intent: Intent


class Candidate(BaseModel):
    intent_id: str
    name: str
    domain: str
    score: float
    score_type: str
    evidence: str
    semantic_score: float | None = None
    lexical_score: float | None = None


class RouteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: str = Field(default_factory=lambda: str(uuid4()), pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    session_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    turn_revision: int = Field(ge=1)
    user_text: str = Field(min_length=1, max_length=2000)
    method: Method = "lexical"
    embedding_id: ModelId | None = None
    llm_id: ModelId | None = None
    retrieval_profile: RetrievalProfile | None = None
    semantic_rejection: Literal["calibrated", "off"] = "calibrated"
    channel: Literal["chat", "voice"] = "chat"

    @field_validator("user_text")
    @classmethod
    def text_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Mesaj boş olamaz.")
        return value.strip()


class Proposal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: DecisionType
    intent_id: str | None = None
    slots: dict[str, str] = Field(default_factory=dict)
    question: str | None = Field(default=None, max_length=300)
    reason_code: str = Field(default="model_selection", max_length=80)
    mentioned_intent_ids: list[str] = Field(default_factory=list, max_length=4)


class RoutingSelection(BaseModel):
    """Model-facing intent selection. Workflow fields and slot collection stay server-side."""
    model_config = ConfigDict(extra="forbid")
    decision: Literal["route", "continue", "clarify", "cancel", "out_of_scope", "handoff"]
    intent_id: str | None = None
    question: str | None = Field(default=None, max_length=300)
    reason_code: Literal["model_selection", "intent_identified", "ambiguous_intent", "multiple_intents",
                         "missing_context", "candidate_not_found", "out_of_scope", "handoff_requested",
                         "active_flow_cancel", "continue_flow"] = "model_selection"
    mentioned_intent_ids: list[str] = Field(default_factory=list, max_length=4)

    @model_validator(mode="after")
    def clarification_is_about_intent(self):
        if self.decision == "clarify":
            if self.intent_id is not None or not (self.question or "").strip():
                raise ValueError("Intent netleştirmede tek bir intent seçilmez ve ayırt edici soru gerekir.")
            if len(set(self.mentioned_intent_ids)) == 1:
                raise ValueError("Tek bilinen intentin işlem bilgilerini workflow toplar.")
        return self


class Review(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_decision: Literal["route", "clarify", "out_of_scope", "handoff"]
    expected_intent_id: str | None = None
    split: Literal["dev", "calibration", "test"] = "test"


class EvaluationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    methods: list[Method] = Field(default=["lexical"], min_length=1, max_length=3)
    embedding_ids: list[ModelId] = Field(default=["default"], min_length=1, max_length=8)
    llm_ids: list[ModelId] = Field(default=["default"], min_length=1, max_length=12)
    semantic_rejection: Literal["calibrated", "off"] = "calibrated"
    source: Literal["all", "seed", "customer"] = "seed"
    split: Literal["dev", "calibration", "test"] = "test"
    limit: int = Field(default=100, ge=1, le=2000)
    catalog_sizes: list[Annotated[int, Field(strict=True, ge=1, le=2000)]] | None = Field(default=None, min_length=1, max_length=8)
    catalog_seed: int = Field(default=42, ge=0, le=2147483647)
    scale_calibration_source: Literal["seed", "customer"] = "seed"
    scale_max_oos_false_accept_rate: float = Field(default=.05, ge=0, le=.5)
    retrieval_profiles: list[RetrievalProfile] | None = Field(default=None, min_length=1, max_length=8)

    @model_validator(mode="after")
    def profiles_for_llm(self):
        if self.retrieval_profiles is not None:
            if "hybrid_llm" not in self.methods:
                raise ValueError("Arama stratejileri için Hibrit arama + LLM yöntemini seçin.")
            ids = [p.id for p in self.retrieval_profiles]
            if len(ids) != len(set(ids)):
                raise ValueError("Arama stratejisi kimlikleri benzersiz olmalı.")
        return self


class CalibrationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    embedding_ids: list[ModelId] = Field(default=["default"], min_length=1, max_length=8)
    source: Literal["seed", "customer"] = "seed"
    max_oos_false_accept_rate: float = Field(default=.05, ge=0, le=.5)
