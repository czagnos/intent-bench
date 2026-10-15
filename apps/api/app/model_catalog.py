"""Built-in presets and registered connections. Routing requests only choose model IDs."""
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .config import Settings
from .contracts import ModelId, RetrievalProfile
from .model_registry import ModelRegistry
from .providers import is_openrouter
from .retrieval import Embeddings
from .reranker import Reranker
from .selector import prompt_version
from .store import Store, fingerprint

MAX_VARIANTS = 32
METHOD_NAMES = {"lexical": "Lexical baseline", "e5": "Semantic search", "hybrid_llm": "Hybrid retrieval + LLM"}


class Preset(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: ModelId
    name: str = Field(min_length=1, max_length=120)
    model: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=500)
    license: str = Field(min_length=1, max_length=80)
    weights_url: str = Field(pattern=r"^https://huggingface.co/", max_length=300)
    connection: Literal["openrouter", "configured"] = "openrouter"
    profile: Literal["auto", "qwen3", "e5", "plain"] = "auto"
    provider_only: list[str] = Field(default_factory=list, max_length=10)
    reasoning: Literal["auto", "disabled", "low", "none"] = "auto"
    max_tokens: int = Field(default=600, ge=128, le=8192)
    response_format: Literal["json_schema", "json_object"] = "json_schema"


class CatalogFile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    verified_on: str
    llms: list[Preset] = Field(max_length=32)
    embeddings: list[Preset] = Field(max_length=32)

    @model_validator(mode="after")
    def unique_ids(self):
        for presets in (self.llms, self.embeddings):
            ids = [p.id for p in presets]
            if "default" in ids or len(ids) != len(set(ids)):
                raise ValueError("Model IDs must be unique; default is reserved.")
        return self


def llm_metadata(settings):
    if settings.llm_protocol == "typesafe":
        return {"model": settings.llm_model, "provider": "typesafe", "protocol": "systemone",
                "prompt_version": prompt_version(settings), "timeout_seconds": settings.llm_timeout_seconds,
                **({"connection_id": settings.llm_connection_id} if settings.llm_connection_id else {})}
    return {**({"connection_id": settings.llm_connection_id, "send_temperature": settings.llm_send_temperature,
                "thinking_parameter": settings.llm_thinking_parameter, "provider_only": settings.llm_provider_only} if settings.llm_connection_id else {}),
            "model": settings.llm_model,
            "provider": "openrouter" if is_openrouter(settings.llm_base_url) else "openai_compatible",
            "reasoning": settings.resolved_llm_reasoning,
            "max_tokens": settings.resolved_llm_max_tokens,
            "response_format": settings.llm_response_format,
            "timeout_seconds": settings.llm_timeout_seconds}


def embedding_key(settings):
    # Cache identity includes provider restrictions and formatting, not just vector dimensions.
    return fingerprint({**Embeddings(settings).metadata, "base_url": settings.embedding_base_url.strip().rstrip("/"),
                        **({"representation": settings.retrieval_representation} if settings.retrieval_representation != "combined" else {})})


def model_details(kind, settings):
    return (Embeddings(settings).metadata if kind == "embedding" else
            Reranker(settings).metadata if kind == "reranker" else llm_metadata(settings))


def model_enabled(kind, settings):
    return (Embeddings(settings).enabled if kind == "embedding" else
            Reranker(settings).enabled if kind == "reranker" else settings.llm_configured)


def embedding_runtime_key(settings):
    # Private, in-memory cache key only: credential rotation must replace clients, not calibration.
    key = embedding_key(settings)
    return key + ":" + fingerprint(settings.resolved_embedding_api_key)


@dataclass(frozen=True)
class Variant:
    id: str
    method: str
    settings: Settings
    embedding_id: str | None
    llm_id: str | None
    labels: dict | None = None
    retrieval: RetrievalProfile | None = None

    @property
    def metadata(self):
        return {"id": self.id, "method": self.method, "name": METHOD_NAMES[self.method],
                **({"model_labels": dict(self.labels)} if self.labels else {}),
                "embedding_id": self.embedding_id, "llm_id": self.llm_id,
                "embedding": Embeddings(self.settings).metadata if self.embedding_id else None,
                "llm": llm_metadata(self.settings) if self.llm_id else None,
                **({"retrieval_profile": self.retrieval.model_dump(),
                    "reranker": Reranker(self.settings).metadata if self.retrieval.reranker_id else None} if self.retrieval else {}),
                "candidate_k": self.settings.candidate_k,
                "prompt_version": prompt_version(self.settings) if self.llm_id else None}


class ModelCatalog:
    def __init__(self, settings: Settings, store=None):
        self.settings = settings
        self.catalog = CatalogFile.model_validate_json(settings.model_catalog_path.read_text())
        self.registry = ModelRegistry(settings, store or Store(settings.data_dir))

    def resolve(self, kind, model_id, settings=None, workspace="demo"):
        current = (settings or self.settings).model_copy(deep=True)
        if model_id == "default":
            return current
        record = self.registry.get(workspace, model_id) if model_id.startswith("model_") else None
        if record:
            if record["kind"] != kind:
                raise ValueError("The selected model type is incompatible with this method.")
            return self.registry.resolve(current, record)
        presets = self.catalog.embeddings if kind == "embedding" else self.catalog.llms if kind == "llm" else []
        preset = next((p for p in presets if p.id == model_id), None)
        if preset is None:
            raise ValueError(f"Unknown {kind} model selection: {model_id}")
        base_url = current.embedding_base_url if kind == "embedding" else current.llm_base_url
        if preset.connection == "openrouter" and (not is_openrouter(base_url) or (kind == "embedding" and current.embedding_mode != "http")):
            raise ValueError(f"An OpenRouter connection is required for {preset.name}.")
        if kind == "embedding":
            current.embedding_model = preset.model
            current.embedding_profile = preset.profile
            # A default Nebius restriction must not bleed into BGE/E5 or Qwen 4B.
            current.embedding_provider_only = list(preset.provider_only)
        else:
            current.llm_protocol = "openai"
            current.llm_model = preset.model
            current.llm_reasoning = preset.reasoning
            current.llm_max_tokens = preset.max_tokens
            current.llm_response_format = preset.response_format
        return current

    def options(self, workspace="demo"):
        groups = {}
        for kind, presets in (("embedding", self.catalog.embeddings), ("llm", self.catalog.llms), ("reranker", [])):
            model = getattr(self.settings, kind + "_model")
            matching = next((p for p in presets if p.model == model), None)
            entries = [{"id": "default", "name": (matching.name if matching else model) + " · default",
                        "model": model, "description": "Current model and connection settings configured on the server.",
                        "license": matching.license if matching else None,
                        "weights_url": matching.weights_url if matching else None}]
            seen = set()
            for item in entries + [p.model_dump() for p in presets]:
                try:
                    settings = self.resolve(kind, item["id"])
                    details = model_details(kind, settings)
                    available = model_enabled(kind, settings)
                    reason = None if available else "A model connection and API key must be configured on the server."
                    identity = fingerprint(details)
                    if identity in seen:
                        continue
                    seen.add(identity)
                except ValueError as exc:
                    available, reason, details = False, str(exc), {}
                groups.setdefault(kind, []).append({k: item.get(k) for k in ("id", "name", "model", "description", "license", "weights_url")} | {"available": available, "unavailable_reason": reason, "settings": details})
        for record in self.registry.records(workspace):
            item = self.registry.public(record)
            details = {}
            if item["available"]:
                settings = self.registry.resolve(self.settings.model_copy(deep=True), record)
                details = model_details(record["kind"], settings)
            groups[record["kind"]].append({**{k: item.get(k) for k in ("id", "name", "model", "description", "license", "weights_url", "available", "unavailable_reason")}, "registered": True, "settings": details})
        return {**groups, "max_variants": MAX_VARIANTS, "verified_on": self.catalog.verified_on}

    def variant(self, method, embedding_id=None, llm_id=None, workspace="demo", retrieval=None):
        if method not in METHOD_NAMES:
            raise ValueError("Unknown method.")
        if retrieval is not None and method != "hybrid_llm":
            raise ValueError("Retrieval profiles are available only for Hybrid retrieval + LLM.")
        embedding_id = (embedding_id or "default") if method != "lexical" else None
        llm_id = (llm_id or "default") if method == "hybrid_llm" else None
        settings = self.settings.model_copy(deep=True)
        if embedding_id:
            settings = self.resolve("embedding", embedding_id, settings, workspace)
            if not Embeddings(settings).enabled:
                raise ValueError("The embedding connection is not configured.")
        if llm_id:
            settings = self.resolve("llm", llm_id, settings, workspace)
            if not settings.llm_configured:
                raise ValueError("The LLM connection is not configured.")
        if retrieval:
            retrieval = retrieval.model_copy(deep=True)
            settings.retrieval_representation = retrieval.representation
            settings.candidate_k = retrieval.candidate_k
            if retrieval.reranker_id:
                settings = self.resolve("reranker", retrieval.reranker_id, settings, workspace)
                if not Reranker(settings).enabled:
                    raise ValueError("Reranker connection is not configured.")
        labels = {}
        for kind, model_id in (("embedding", embedding_id), ("llm", llm_id), ("reranker", retrieval.reranker_id if retrieval else None)):
            record = self.registry.get(workspace, model_id) if model_id else None
            if record:
                labels[kind] = record["name"]
        variant = Variant(method, method, settings, embedding_id, llm_id, labels, retrieval)
        if retrieval or any(i not in (None, "default") for i in (embedding_id, llm_id)):
            identity = {k: v for k, v in variant.metadata.items() if k != "model_labels"}
            return Variant(method + "-" + fingerprint(identity)[:12], method, settings, embedding_id, llm_id, labels, retrieval)
        return variant  # Old clients and stored default-only runs keep their method keys.

    def expand(self, options, workspace="demo"):
        variants, seen = [], set()
        for method in dict.fromkeys(options.methods):
            embeddings = list(dict.fromkeys(options.embedding_ids)) if method != "lexical" else [None]
            llms = list(dict.fromkeys(options.llm_ids)) if method == "hybrid_llm" else [None]
            for embedding in embeddings:
                for llm in llms:
                    profiles = options.retrieval_profiles if method == "hybrid_llm" and options.retrieval_profiles else [None]
                    for profile in profiles:
                        variant = self.variant(method, embedding, llm, workspace, profile)
                        config = {k: v for k, v in variant.metadata.items() if k not in ("id", "embedding_id", "llm_id", "model_labels")}
                        if profile:
                            config["retrieval_profile"] = {k: v for k, v in config["retrieval_profile"].items() if k not in ("id", "name", "reranker_id")}
                        identity = fingerprint(config)
                        if identity not in seen:
                            variants.append(variant)
                            seen.add(identity)
        if len(variants) > MAX_VARIANTS:
            raise ValueError(f"An experiment can contain at most {MAX_VARIANTS} model combinations.")
        return variants
