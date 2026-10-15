"""Read-only readiness for the selected workspace and model connections."""
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict

from .model_catalog import model_enabled
from .providers import ModelUnavailable

if TYPE_CHECKING:
    from .service import Studio


class ConnectionStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    model: str
    configured: bool
    reason: str | None = None


class IndexStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")
    state: Literal["present", "missing", "invalid", "unavailable"]
    representation: Literal["combined", "separate"]
    reason: str | None = None


class CalibrationStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")
    state: Literal["current", "missing_or_stale", "unavailable"]
    reason: str | None = None


class SetupStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace: str
    catalog_version: str
    shared_openrouter_key_present: bool
    embedding: ConnectionStatus
    llm: ConnectionStatus
    index: IndexStatus
    calibration: CalibrationStatus


def setup_status(studio: "Studio", workspace: str, embedding_id: str, llm_id: str) -> SetupStatus:
    catalog = studio.store.catalog(workspace)
    if not catalog:
        raise LookupError("Open the sector workspace before checking setup.")
    options = studio.model_catalog.options(workspace)

    def connection(kind: Literal["embedding", "llm"], model_id: str) -> ConnectionStatus:
        option = next((item for item in options[kind] if item["id"] == model_id), None)
        if option is not None and not option["available"]:
            return ConnectionStatus(id=model_id, model=option["model"], configured=False,
                                    reason=option["unavailable_reason"])
        # Resolve presets as well as registrations; aliases may be deduplicated in options.
        settings = studio.model_catalog.resolve(kind, model_id, workspace=workspace)
        configured = model_enabled(kind, settings)
        return ConnectionStatus(id=model_id, model=getattr(settings, kind + "_model"), configured=configured,
                                reason=None if configured else "Configure this model connection on the server.")

    embedding = connection("embedding", embedding_id)
    llm = connection("llm", llm_id)
    index = IndexStatus(state="unavailable", representation=studio.settings.retrieval_representation,
                        reason="Select a configured embedding connection.")
    calibration = CalibrationStatus(state="unavailable", reason=index.reason)
    if embedding.configured:
        variant = studio.model_catalog.variant("e5", embedding_id, workspace=workspace)
        index.representation = variant.settings.retrieval_representation
        try:
            retriever = studio.retriever(workspace, catalog["version"], variant.settings)
            if retriever.vector_index is not None:
                retriever.vector_index.load()
                index.state, index.reason = "present", None
        except FileNotFoundError:
            index.state, index.reason = "missing", "Prepare the selected catalog index with scripts/warm_models.py."
        except (ModelUnavailable, OSError):
            index.state, index.reason = "invalid", "The persistent index is invalid or unreadable. Check storage access and rebuild it with scripts/reindex.py."
        try:
            studio.calibrator.resolve(workspace, variant, catalog["version"], "calibrated")
            calibration = CalibrationStatus(state="current")
        except ValueError as exc:
            calibration = CalibrationStatus(state="missing_or_stale", reason=str(exc))
    return SetupStatus(workspace=workspace, catalog_version=catalog["version"],
                       shared_openrouter_key_present=bool(studio.settings.openrouter_api_key.strip()),
                       embedding=embedding, llm=llm, index=index, calibration=calibration)
