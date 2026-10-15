"""Server-owned starter catalogs and immutable, conservative upgrade manifests."""
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .config import ROOT
from .contracts import DecisionType, Intent

PresetId = Literal["banking", "airline", "insurance", "ecommerce"]


class SeedCase(BaseModel):
    """Typed storage columns with the original JSON envelope preserved verbatim."""
    model_config = ConfigDict(extra="forbid", frozen=True)
    case_id: str
    source: Literal["seed"]
    dataset_version: str
    reviewed: bool
    split: Literal["test", "calibration"]
    payload: str

    def references(self) -> "SeedCaseReferences":
        return SeedCaseReferences.model_validate_json(self.payload)


class SeedCaseContext(BaseModel):
    active_intent: str | None = None
    clarification_options: list[str] = Field(default_factory=list)


class SeedCaseReferences(BaseModel):
    expected_decision: DecisionType
    expected_intent_id: str | None = None
    context: SeedCaseContext = Field(default_factory=SeedCaseContext)

    def intent_ids(self) -> set[str]:
        ids = set(self.context.clarification_options)
        for intent_id in (self.expected_intent_id, self.context.active_intent):
            if intent_id:
                ids.add(intent_id)
        if self.expected_decision == "handoff":
            ids.add("service.human")
        return ids


class PresetRevision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str
    previous_catalog_hashes: dict[str, str]
    previous_case_ids: list[str]


class CaseLabelChange(BaseModel):
    case_id: str
    previous_intent_id: str | None
    intent_id: str | None


class PresetRevisionReport(BaseModel):
    id: str
    created: float
    applicable: bool
    from_catalog_version: str | None
    to_catalog_version: str | None
    skipped_reason: Literal["unrecognized_catalog", "capacity_exceeded"] | None = None
    updated_intents: list[str] = Field(default_factory=list)
    preserved_intents: list[str] = Field(default_factory=list)
    updated_cases: list[str] = Field(default_factory=list)
    preserved_cases: list[str] = Field(default_factory=list)
    skipped_cases: list[str] = Field(default_factory=list)
    relabeled_cases: list[str] = Field(default_factory=list)
    case_changes: list[CaseLabelChange] = Field(default_factory=list)


class PresetDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: PresetId
    name: str
    description: str
    workspace: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")

    @property
    def directory(self) -> Path:
        return ROOT / "data" / ("demo" if self.id == "banking" else f"presets/{self.id}")

    def intents(self) -> list[Intent]:
        return [Intent.model_validate(item) for item in json.loads((self.directory / "catalog.json").read_text())]

    def cases(self) -> list[SeedCase]:
        """Original test/calibration rows used by immutable historical releases."""
        return self._read_cases(("cases.json", "calibration-cases.json"))

    def benchmark_cases(self) -> list[SeedCase]:
        return self._read_cases(("benchmark-cases.json",))

    def benchmark_revision(self) -> PresetRevision:
        return PresetRevision.model_validate_json((self.directory / "migrations/case-depth-v1.json").read_text())

    def _read_cases(self, filenames: tuple[str, ...]) -> list[SeedCase]:
        return [SeedCase(case_id=item["case_id"], source=item["source"], dataset_version=item["dataset_version"],
                         reviewed=item["reviewed"], split=item["split"], payload=json.dumps(item, ensure_ascii=False))
                for filename in filenames
                for item in json.loads((self.directory / filename).read_text())]

    def revisions(self) -> list[PresetRevision]:
        if self.id == "banking":
            return []
        return [PresetRevision.model_validate_json(path.read_text())
                for path in sorted((self.directory / "migrations").glob("expansion-*.json"))]


class PresetMetadata(PresetDefinition):
    intent_count: int = Field(ge=1, le=2000)


def definitions() -> list[PresetDefinition]:
    return [PresetDefinition.model_validate(item) for item in json.loads((ROOT / "data/presets/manifest.json").read_text())]


def catalog_presets() -> list[PresetMetadata]:
    return [PresetMetadata(**preset.model_dump(), intent_count=len(preset.intents())) for preset in definitions()]


def workspace_preset(workspace: str) -> PresetDefinition:
    presets = definitions()
    return next((preset for preset in presets if preset.workspace == workspace), presets[0])
