"""Explicit pre-turn transcript snapshots, bounded independently of live providers."""
from collections.abc import Mapping
from typing import Annotated, cast

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .choice_routing import PriorTurn, RoutingContext
from .contracts import Intent

IntentReference = Annotated[str, Field(strict=True, min_length=1, max_length=100)]
SlotName = Annotated[str, Field(strict=True, min_length=1, max_length=80)]
SlotValue = Annotated[str, Field(strict=True, max_length=2000)]


class PreTurnData(RoutingContext, total=False):
    slots: dict[str, str]
    pending_slot: str | None
    pending_confirmation: bool
    clarifications: int


class TranscriptPriorTurn(PriorTurn):
    model_config = ConfigDict(extra="forbid", strict=True)
    content: str = Field(max_length=2000)


class PreTurnContext(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    active_intent: IntentReference | None = None
    slots: dict[SlotName, SlotValue] = Field(default_factory=dict, max_length=10)
    pending_slot: SlotName | None = None
    pending_confirmation: bool = False
    clarification_options: list[IntentReference] = Field(default_factory=list, max_length=4)
    clarifications: int = Field(default=0, ge=0, le=10)
    messages: list[TranscriptPriorTurn] = Field(default_factory=list, max_length=12)

    @model_validator(mode="after")
    def workflow_has_active_intent(self) -> "PreTurnContext":
        if (self.slots or self.pending_slot or self.pending_confirmation) and not self.active_intent:
            raise ValueError("Workflow context requires an active_intent.")
        if self.pending_slot and self.pending_confirmation:
            raise ValueError("Context cannot wait for a slot and confirmation at the same time.")
        if self.pending_slot in self.slots:
            raise ValueError("The pending slot must not already have a supplied value.")
        return self

    def as_data(self) -> PreTurnData:
        """Keep an explicitly empty context empty, including for calibration eligibility."""
        return cast(PreTurnData, self.model_dump(exclude_unset=True))


def validate_case_context(context: PreTurnContext, catalog: Mapping[str, Intent]) -> PreTurnContext:
    """Validate one explicit snapshot against the workspace's current catalog."""
    references = [*context.clarification_options]
    if context.active_intent:
        references.append(context.active_intent)
    if any(reference not in catalog for reference in references):
        raise ValueError("Context refers to an intent outside the workspace catalog.")
    if context.active_intent:
        required = set(catalog[context.active_intent].required_slots)
        if set(context.slots) - required or (context.pending_slot and context.pending_slot not in required):
            raise ValueError("Context contains a slot outside the active intent's workflow.")
        if context.pending_confirmation and (not required or required - set(context.slots)):
            raise ValueError("Confirmation context requires every slot of the active workflow.")
    return context
