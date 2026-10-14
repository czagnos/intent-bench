"""Workspace-owned connections. Only credential references are stored or returned."""
import ipaddress
import logging
import os
import re
import threading
import time
from typing import Literal, get_args
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
from dotenv import dotenv_values
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .providers import OPENROUTER_BASE_URL, TYPESAFE_BASE_URL, ModelUnavailable, is_openrouter, response_json
from .store import fingerprint

Kind = Literal["llm", "embedding", "reranker"]
Connection = Literal["openrouter", "onprem", "typesafe"]
Authentication = Literal["shared_openrouter", "env", "none"]
logger = logging.getLogger(__name__)


def discovery_error(kind, category, message, status=None, diagnostics=None):
    details = {**(diagnostics or {}), "service": "model_discovery", "model_kind": kind, "category": category}
    if status is not None:
        details["upstream_status"] = status
    # Provider bodies, request headers and exception messages can contain credentials.
    logger.warning("OpenRouter discovery failed: kind=%s category=%s upstream_status=%s", kind, category, status)
    return ModelUnavailable(message, diagnostics=details)


def endpoint(value):
    value = value.strip().rstrip("/")
    try:
        url = urlsplit(value)
        if (url.scheme not in ("http", "https") or not url.hostname or url.username or url.password
                or url.query or url.fragment or any(c.isspace() for c in value) or "\\" in value):
            raise ValueError()
        if url.port is not None and not 1 <= url.port <= 65535:
            raise ValueError()
        if url.hostname.lower() in ("metadata.google.internal", "metadata", "instance-data"):
            raise ValueError()
        try:
            address = ipaddress.ip_address(url.hostname)
        except ValueError:
            address = None
        if address and (address.is_link_local or address.is_unspecified or address.is_multicast
                        or (getattr(address, "ipv4_mapped", None) and address.ipv4_mapped.is_link_local)):
            raise ValueError()
    except ValueError as exc:
        raise ValueError("Geçerli bir HTTP(S) API kök adresi girin; URL içinde anahtar kullanmayın.") from exc
    return value


class Registration(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    kind: Kind
    name: str = Field(min_length=1, max_length=120)
    model: str = Field(min_length=1, max_length=200, pattern=r"^[^\s]+$")
    connection: Connection
    base_url: str = Field(default="", max_length=500)
    auth: Authentication = "shared_openrouter"
    credential_env: str = Field(default="", max_length=120, pattern=r"^(INTENT_TYPESAFE_API_KEY|INTENT_MODEL_KEY_[A-Z0-9_]+)?$")
    enabled: bool = True
    description: str = Field(default="", max_length=500)
    weights_url: str = Field(default="", max_length=300, pattern=r"^(https://huggingface\.co/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)?$")
    license: str = Field(default="", max_length=80)
    profile: Literal["auto", "qwen3", "e5", "plain"] = "auto"
    provider_only: list[str] = Field(default_factory=list, max_length=10)
    reasoning: Literal["auto", "disabled", "low", "none"] = "none"
    max_tokens: int = Field(default=600, ge=128, le=8192)
    response_format: Literal["json_schema", "json_object", "prompt"] = "json_object"
    thinking_parameter: Literal["none", "chat_template", "top_level"] = "none"
    send_temperature: bool = True
    timeout_seconds: float = Field(default=30, ge=1, le=120)
    reranker_protocol: Literal["cohere", "tei"] = "cohere"

    @field_validator("provider_only")
    @classmethod
    def providers(cls, values):
        if any(not re.fullmatch(r"[A-Za-z0-9_./-]{1,100}", v) for v in values):
            raise ValueError("Sağlayıcı kimliği geçersiz.")
        return list(dict.fromkeys(values))

    @model_validator(mode="after")
    def validate_connection(self):
        if self.kind == "reranker" and self.connection != "onprem":
            raise ValueError("Reranker için özel /rerank endpoint bağlantısı ekleyin.")
        if self.connection == "typesafe":
            if self.kind != "llm" or self.auth != "env":
                raise ValueError("TypeSafe yalnız LLM ve sunucudaki anahtar değişkeni ile kullanılabilir.")
            if self.base_url and self.base_url.rstrip("/") != TYPESAFE_BASE_URL:
                raise ValueError("TypeSafe için resmi API adresi kullanılmalı.")
            self.base_url = TYPESAFE_BASE_URL
            if self.provider_only:
                raise ValueError("Sağlayıcı filtresi yalnızca OpenRouter bağlantısında kullanılabilir.")
        elif self.connection == "openrouter":
            if self.base_url and not is_openrouter(self.base_url):
                raise ValueError("OpenRouter için resmi API adresi kullanılmalı.")
            self.base_url = OPENROUTER_BASE_URL
            if self.auth == "none":
                raise ValueError("OpenRouter API anahtarı gerekli.")
        else:
            self.base_url = endpoint(self.base_url)
            if is_openrouter(self.base_url) or self.auth == "shared_openrouter":
                raise ValueError("On-prem bağlantısı kendi kimlik doğrulama ayarını kullanmalı.")
            if self.provider_only:
                raise ValueError("Sağlayıcı filtresi yalnızca OpenRouter bağlantısında kullanılabilir.")
        if self.auth == "env" and not self.credential_env:
            raise ValueError("INTENT_MODEL_KEY_ ile başlayan anahtar değişkenini girin.")
        if self.credential_env == "INTENT_TYPESAFE_API_KEY" and self.connection != "typesafe":
            raise ValueError("TypeSafe anahtarı yalnız resmi TypeSafe bağlantısında kullanılabilir.")
        if self.auth != "env":
            self.credential_env = ""
        return self


class ModelRegistry:
    def __init__(self, settings, store):
        self.settings, self.store = settings, store
        self.transport = None
        self.cache = {}
        self.lock = threading.Lock()

    def records(self, workspace):
        # Keep unsupported local records intact without publishing their private metadata.
        return [record for record in self.store.model_registrations(workspace)
                if record.get("connection") in get_args(Connection) and record.get("auth") in get_args(Authentication)]

    def get(self, workspace, model_id):
        record = self.store.model_registration(workspace, model_id)
        if record and record.get("connection") in get_args(Connection) and record.get("auth") in get_args(Authentication):
            return record
        return None

    def save(self, workspace, body, model_id=None):
        previous = self.get(workspace, model_id) if model_id else None
        if model_id and not previous:
            raise KeyError("Model kaydı bulunamadı.")
        if previous and previous["kind"] != body.kind:
            raise ValueError("Model türü değiştirilemez; yeni kayıt ekleyin.")
        record = body.model_dump()
        # Stable connection identity for renames/toggles; changed inference settings invalidate calibration.
        config = {k: v for k, v in record.items() if k not in ("name", "description", "license", "weights_url", "enabled")}
        record.update(id=model_id or "model_" + uuid4().hex, revision=fingerprint(config), updated=time.time())
        self.store.save_model_registration(workspace, record, update=bool(model_id))
        return self.public(record)

    def credential(self, record):
        if record["auth"] == "none":
            return ""
        if record["auth"] == "shared_openrouter":
            # Never inherit an on-prem dedicated key or the other model type's dedicated key.
            key = self.settings.openrouter_api_key.strip()
            kind = record["kind"]
            base = getattr(self.settings, f"{kind}_base_url")
            return key or (getattr(self.settings, f"resolved_{kind}_api_key") if is_openrouter(base) else "")
        name = record["credential_env"]
        value = os.environ.get(name)
        if value is None and self.settings.model_credentials_file.is_file():
            value = dotenv_values(self.settings.model_credentials_file, interpolate=False).get(name)
        return (value or "").strip()

    def public(self, record):
        configured = record["auth"] == "none" or bool(self.credential(record))
        return {**record, "available": bool(record["enabled"] and configured), "credential_configured": configured,
                "unavailable_reason": ("Model devre dışı." if not record["enabled"] else
                                       "Model için sunucuda API anahtarı tanımlayın." if not configured else None)}

    def resolve(self, current, record):
        if not record["enabled"]:
            raise ValueError("Model devre dışı.")
        key = self.credential(record)
        if record["auth"] != "none" and not key:
            raise ValueError("Model için sunucuda API anahtarı tanımlayın.")
        kind = record["kind"]
        setattr(current, f"{kind}_base_url", record["base_url"])
        setattr(current, f"{kind}_api_key", key)
        setattr(current, f"{kind}_model", record["model"])
        setattr(current, f"{kind}_timeout_seconds", record["timeout_seconds"])
        setattr(current, f"{kind}_connection_id", record["id"] + ":" + record["revision"])
        if kind == "embedding":
            current.embedding_mode = "http"
            current.embedding_profile = record["profile"]
            current.embedding_provider_only = list(record["provider_only"])
        elif kind == "reranker":
            current.reranker_mode = "http"
            current.reranker_protocol = record.get("reranker_protocol", "cohere")
        else:
            current.llm_protocol = "typesafe" if record["connection"] == "typesafe" else "openai"
            current.llm_reasoning = record["reasoning"]
            current.llm_max_tokens = record["max_tokens"]
            current.llm_response_format = record["response_format"]
            current.llm_thinking_parameter = record["thinking_parameter"]
            current.llm_send_temperature = record["send_temperature"]
            current.llm_provider_only = list(record["provider_only"])
        return current

    def discover(self, kind, refresh=False):
        """Public model metadata only. No customer text, paid inference, or arbitrary URLs."""
        with self.lock:
            cached = self.cache.get(kind)
            if cached and not refresh and time.time() - cached["fetched_at"] < 300:
                return {**cached, "cached": True}
            url = OPENROUTER_BASE_URL + ("/embeddings/models" if kind == "embedding" else "/models")
            key = self.credential({"auth": "shared_openrouter", "kind": kind})
            headers = {"Authorization": "Bearer " + key} if key else {}
            upstream_status, phase = None, "connection"
            try:
                # Omitting offset/limit requests the full catalog per OpenRouter's API contract.
                with httpx.Client(timeout=20, transport=self.transport, follow_redirects=False) as client:
                    with client.stream("GET", url, headers=headers) as response:
                        upstream_status, phase = response.status_code, "response_decoding"
                        size, chunks = 0, []
                        for chunk in response.iter_bytes():
                            size += len(chunk)
                            if size > 12 * 1024 * 1024:
                                raise ModelUnavailable("OpenRouter: Model listesi yanıtı boyut sınırını aştı.", diagnostics={"category": "response_size"})
                            chunks.append(chunk)
                        # iter_bytes() has already decompressed gzip/deflate/etc. Keeping
                        # Content-Encoding would make Response decode the same bytes again.
                        decoded_headers = [(name, value) for name, value in response.headers.multi_items()
                                           if name.lower() not in ("content-encoding", "content-length", "transfer-encoding")]
                        body = httpx.Response(response.status_code, headers=decoded_headers,
                                              content=b"".join(chunks), request=response.request)
                        phase = "response_json"
                        data = response_json(body, "OpenRouter")
                phase = "catalog_schema"
                if not isinstance(data.get("data"), list):
                    raise ValueError("Invalid catalog")
                items = []
                for raw in data["data"]:
                    if not isinstance(raw, dict) or not isinstance(raw.get("id"), str):
                        continue
                    arch = raw.get("architecture") or {}
                    if "text" not in arch.get("input_modalities", ["text"]):
                        continue
                    if kind == "llm" and "text" not in arch.get("output_modalities", ["text"]):
                        continue
                    hf = raw.get("hugging_face_id") or ""
                    weights = "https://huggingface.co/" + hf if re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", hf) else ""
                    params = raw.get("supported_parameters") or []
                    items.append({"model": raw["id"][:200], "name": str(raw.get("name") or raw["id"])[:120],
                                  "description": str(raw.get("description") or "")[:500], "kind": kind,
                                  "weights_url": weights, "context_length": raw.get("context_length"),
                                  "supported_parameters": [p for p in params if isinstance(p, str)][:50],
                                  "response_format": "json_schema" if "structured_outputs" in params else "json_object" if "response_format" in params else "prompt",
                                  "reasoning": "auto" if "reasoning" in params else "none",
                                  "send_temperature": "temperature" in params})
                result = {"items": items, "fetched_at": time.time(), "source": url, "cached": False}
                self.cache[kind] = result
                return result
            except ModelUnavailable as exc:
                category = exc.diagnostics.get("category", "upstream_error")
                raise discovery_error(kind, category, str(exc), upstream_status, exc.diagnostics) from exc
            except httpx.TimeoutException as exc:
                raise discovery_error(kind, "timeout", "OpenRouter: Model listesi isteği süre sınırını aştı. Yeniden deneyin.", upstream_status) from exc
            except httpx.DecodingError as exc:
                raise discovery_error(kind, "response_decoding", "OpenRouter: Sıkıştırılmış model listesi yanıtı çözümlenemedi.", upstream_status) from exc
            except httpx.HTTPError as exc:
                raise discovery_error(kind, "connection", "OpenRouter: Bağlantı kurulamadı. Ağ, proxy ve TLS ayarlarını kontrol edin.", upstream_status) from exc
            except ImportError as exc:
                raise discovery_error(kind, "client_configuration", "OpenRouter: HTTP istemcisi başlatılamadı. Python bağımlılıklarını requirements.lock ile kurun.", upstream_status) from exc
            except (ValueError, TypeError, AttributeError) as exc:
                raise discovery_error(kind, phase, "OpenRouter: Model listesi yanıt formatı geçersiz.", upstream_status) from exc
