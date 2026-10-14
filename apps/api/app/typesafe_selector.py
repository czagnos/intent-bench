"""TypeSafe's native typed questions adapted to the common routing contract."""
from math import fsum, isclose
from typing import Annotated, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .config import Settings
# Retain the existing public context/question imports used by direct-Jev evaluation.
from .choice_routing import (CandidateContext, ChoiceQuestion, Conversation, PriorTurn, PriorTurnData,
                             RoutingContext, SelectionState, ROUTING_INSTRUCTIONS,
                             make_routing_request, selection_from_choices)
from .contracts import Candidate, Intent, RoutingSelection
from .providers import ModelUnavailable, TYPESAFE_BASE_URL, response_json

PROMPT_VERSION = "router-tr-typesafe-v1-choice"


class SystemOneRequest(BaseModel):
    model: str
    state: SelectionState
    questions: dict[str, ChoiceQuestion]


Probability = Annotated[float, Field(strict=True, ge=0, le=1, allow_inf_nan=False)]


class ChoiceAnswer(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)
    type: Literal["choice"]
    choice: str
    confidence: Probability
    probabilities: dict[str, Probability]


class TokenUsage(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)


class SystemOneResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)
    model: str
    answers: dict[str, ChoiceAnswer]
    usage: TokenUsage


def make_request(settings: Settings, text: str, state: RoutingContext, candidates: list[Candidate], catalog: dict[str, Intent]) -> SystemOneRequest:
    request = make_routing_request(text, state, candidates, catalog)
    return SystemOneRequest(model=settings.llm_model, state=request.state, questions=request.questions)


def routing_selection(data: SystemOneResponse, request: SystemOneRequest, catalog: dict[str, Intent]) -> RoutingSelection:
    return selection_from_choices({key: answer.choice for key, answer in data.answers.items()}, request.state, catalog)


def validate_answers(data: SystemOneResponse, request: SystemOneRequest) -> None:
    if data.answers.keys() != request.questions.keys():
        raise ValueError("Question coverage mismatch")
    for key, question in request.questions.items():
        answer = data.answers[key]
        if answer.probabilities.keys() != question.criteria.keys() or answer.choice not in question.criteria:
            raise ValueError("Choice coverage mismatch")
        # Permit independent rounding to three decimal places, including rounded ties.
        tolerance = len(question.criteria) * .0005 + 1e-9
        if not isclose(fsum(answer.probabilities.values()), 1, rel_tol=0, abs_tol=tolerance):
            raise ValueError("Unnormalized choice distribution")
        if answer.probabilities[answer.choice] + .001 < max(answer.probabilities.values()):
            raise ValueError("Choice is not a maximum-probability option")


def select(settings: Settings, transport: httpx.BaseTransport | None, text: str, state: RoutingContext,
           candidates: list[Candidate], catalog: dict[str, Intent]) -> tuple[RoutingSelection, dict[str, int]]:
    try:
        request = make_request(settings, text, state, candidates, catalog)
        with httpx.Client(timeout=settings.llm_timeout_seconds, transport=transport) as client:
            response = client.post(TYPESAFE_BASE_URL + "/systemone",
                                   headers={"Authorization": "Bearer " + settings.resolved_llm_api_key},
                                   json=request.model_dump())
            data = SystemOneResponse.model_validate(response_json(response, "TypeSafe"))
        validate_answers(data, request)
        selection = routing_selection(data, request, catalog)
    except httpx.TimeoutException as exc:
        raise ModelUnavailable("TypeSafe süre sınırını aştı. İstek yönlendirilmedi.") from exc
    except (httpx.HTTPError, ValidationError, ValueError, KeyError, TypeError) as exc:
        raise ModelUnavailable("TypeSafe bağlantısı veya seçim yanıtı geçersiz.",
                               diagnostics={"service": "llm", "category": "typesafe_contract"}) from exc
    return selection, {"prompt_tokens": data.usage.input_tokens, "completion_tokens": data.usage.output_tokens,
                       "total_tokens": data.usage.input_tokens + data.usage.output_tokens}
