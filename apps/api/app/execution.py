"""Cooperative, evaluation-scoped limits without state on shared model clients."""
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from decimal import Decimal
import time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


StopReason = Literal[
    "request_limit", "duration_limit", "reported_cost_limit", "reported_cost_unknown",
    "user_cancelled", "interrupted",
]
ProviderService = Literal["embedding", "llm", "typesafe", "reranker"]
ExecutionStage = Literal["evaluation", "index", "calibration", "cases"]


class ExecutionLimits(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    max_provider_requests: int | None = Field(default=None, ge=0, le=100000)
    max_duration_seconds: float | None = Field(default=None, ge=1, le=86400, allow_inf_nan=False)
    max_reported_cost_usd: float | None = Field(default=None, gt=0, le=10000, allow_inf_nan=False)


class UsageTotals(BaseModel):
    model_config = ConfigDict(frozen=True)
    provider_requests: int = 0
    known_prompt_tokens: int = 0
    known_completion_tokens: int = 0
    known_total_tokens: int = 0
    unknown_prompt_token_requests: int = 0
    unknown_completion_token_requests: int = 0
    unknown_total_token_requests: int = 0
    known_cost_usd: float = 0
    unknown_cost_requests: int = 0
    reported_cost_usd: float | None = 0


class ServiceStageAccounting(UsageTotals):
    service: ProviderService
    stage: ExecutionStage


class ExecutionAccounting(UsageTotals):
    by_service_stage: list[ServiceStageAccounting] = Field(default_factory=list)


@dataclass(frozen=True)
class ReportedUsage:
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    cost_usd: float | None = None


@dataclass
class _UsageAccumulator:
    provider_requests: int = 0
    known_prompt_tokens: int = 0
    known_completion_tokens: int = 0
    known_total_tokens: int = 0
    unknown_prompt_token_requests: int = 0
    unknown_completion_token_requests: int = 0
    unknown_total_token_requests: int = 0
    known_cost_usd: Decimal = Decimal("0")
    unknown_cost_requests: int = 0

    def reserve(self) -> None:
        self.provider_requests += 1
        self.unknown_prompt_token_requests += 1
        self.unknown_completion_token_requests += 1
        self.unknown_total_token_requests += 1
        self.unknown_cost_requests += 1

    def record(self, usage: ReportedUsage) -> None:
        if usage.prompt_tokens is not None:
            self.known_prompt_tokens += usage.prompt_tokens
            self.unknown_prompt_token_requests -= 1
        if usage.completion_tokens is not None:
            self.known_completion_tokens += usage.completion_tokens
            self.unknown_completion_token_requests -= 1
        if usage.total_tokens is not None:
            self.known_total_tokens += usage.total_tokens
            self.unknown_total_token_requests -= 1
        if usage.cost_usd is not None:
            # Preserve reported decimal amounts; binary float drift must not permit an extra request.
            self.known_cost_usd += Decimal(str(usage.cost_usd))
            self.unknown_cost_requests -= 1

    def snapshot(self) -> UsageTotals:
        return UsageTotals(
            provider_requests=self.provider_requests,
            known_prompt_tokens=self.known_prompt_tokens,
            known_completion_tokens=self.known_completion_tokens,
            known_total_tokens=self.known_total_tokens,
            unknown_prompt_token_requests=self.unknown_prompt_token_requests,
            unknown_completion_token_requests=self.unknown_completion_token_requests,
            unknown_total_token_requests=self.unknown_total_token_requests,
            known_cost_usd=float(self.known_cost_usd),
            unknown_cost_requests=self.unknown_cost_requests,
            reported_cost_usd=None if self.unknown_cost_requests else float(self.known_cost_usd),
        )


@dataclass
class ProviderAttempt:
    """A reserved attempt: absent/failed responses retain its unknown accounting."""
    controller: "EvaluationController"
    service: ProviderService
    stage: ExecutionStage
    _recorded: bool = False

    def record_usage(self, usage: ReportedUsage) -> None:
        if self._recorded:
            raise RuntimeError("A provider attempt can only be accounted once.")
        self._recorded = True
        self.controller.record_usage(self.service, self.stage, usage)


class EvaluationStopped(RuntimeError):
    def __init__(self, stop_reason: StopReason):
        self.stop_reason = stop_reason
        super().__init__(stop_reason)


class EvaluationController:
    def __init__(
        self, limits: ExecutionLimits,
        *, cancel_requested: Callable[[], bool] | None = None,
        on_checkpoint: Callable[[ExecutionAccounting], None] | None = None,
    ):
        self.limits = limits
        self.cancel_requested = cancel_requested
        self.on_checkpoint = on_checkpoint
        self._started_at = time.monotonic()
        self._totals = _UsageAccumulator()
        self._rows: dict[tuple[ProviderService, ExecutionStage], _UsageAccumulator] = {}

    def accounting(self) -> ExecutionAccounting:
        return ExecutionAccounting(
            **self._totals.snapshot().model_dump(),
            by_service_stage=[ServiceStageAccounting(service=service, stage=stage, **row.snapshot().model_dump())
                              for (service, stage), row in sorted(self._rows.items())],
        )

    def checkpoint(self) -> None:
        if self.cancel_requested is not None and self.cancel_requested():
            raise EvaluationStopped("user_cancelled")
        if (self.limits.max_duration_seconds is not None
                and time.monotonic() - self._started_at >= self.limits.max_duration_seconds):
            raise EvaluationStopped("duration_limit")
        if self.limits.max_reported_cost_usd is not None:
            if self._totals.unknown_cost_requests:
                raise EvaluationStopped("reported_cost_unknown")
            if self._totals.known_cost_usd >= Decimal(str(self.limits.max_reported_cost_usd)):
                raise EvaluationStopped("reported_cost_limit")

    def reserve_request(self, service: ProviderService, stage: ExecutionStage) -> ProviderAttempt:
        self.checkpoint()
        if self.limits.max_provider_requests is not None and self._totals.provider_requests >= self.limits.max_provider_requests:
            raise EvaluationStopped("request_limit")
        self._totals.reserve()
        self._rows.setdefault((service, stage), _UsageAccumulator()).reserve()
        self._persist()
        return ProviderAttempt(self, service, stage)

    def record_usage(self, service: ProviderService, stage: ExecutionStage, usage: ReportedUsage) -> None:
        self._totals.record(usage)
        self._rows[(service, stage)].record(usage)
        # Keep the just-finished response available; stop at the next checkpoint.
        self._persist()

    def _persist(self) -> None:
        if self.on_checkpoint is not None:
            self.on_checkpoint(self.accounting())


_controller: ContextVar[EvaluationController | None] = ContextVar("evaluation_controller", default=None)
_stage: ContextVar[ExecutionStage] = ContextVar("evaluation_stage", default="evaluation")


@contextmanager
def activate_execution(controller: EvaluationController) -> Iterator[None]:
    token = _controller.set(controller)
    stage_token = _stage.set("evaluation")
    try:
        yield
    finally:
        _stage.reset(stage_token)
        _controller.reset(token)


@contextmanager
def execution_stage(stage: ExecutionStage) -> Iterator[None]:
    token = _stage.set(stage)
    try:
        yield
    finally:
        _stage.reset(token)


def execution_checkpoint() -> None:
    controller = _controller.get()
    if controller is not None:
        controller.checkpoint()


def reserve_provider_request(service: ProviderService) -> ProviderAttempt | None:
    controller = _controller.get()
    if controller is not None:
        return controller.reserve_request(service, _stage.get())
    return None
