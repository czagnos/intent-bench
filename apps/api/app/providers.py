"""Provider-specific HTTP conventions without exposing provider payloads or secrets."""
import math
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import httpx

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
TYPESAFE_BASE_URL = "https://api.typesafe.ai/v1"


def is_openrouter(base_url: str) -> bool:
    # Shared credentials only apply to the documented OpenRouter endpoint.
    return base_url.strip().rstrip("/") == OPENROUTER_BASE_URL


class ModelUnavailable(RuntimeError):
    def __init__(self, message: str, *, diagnostics: dict | None = None):
        super().__init__(message)
        self.diagnostics = diagnostics or {}


def retry_after_seconds(value: str | None) -> float | None:
    if not value:
        return None
    try:
        if re.fullmatch(r"\d+(?:\.\d+)?", value.strip()):
            seconds = float(value)
        else:
            deadline = parsedate_to_datetime(value)
            if deadline.tzinfo is None:
                deadline = deadline.replace(tzinfo=timezone.utc)
            seconds = (deadline - datetime.now(timezone.utc)).total_seconds()
        return round(max(0, seconds), 3) if math.isfinite(seconds) else None
    except (ValueError, TypeError, OverflowError):
        return None


def error_diagnostics(response: httpx.Response, error: dict) -> dict:
    details = {"http_status": response.status_code}
    code = error.get("code")
    if re.fullmatch(r"\d{3}", str(code)) and 100 <= int(code) <= 599:
        details["error_code"] = int(code)
    metadata = error.get("metadata")
    if isinstance(metadata, dict):
        # Never return raw errors, flagged inputs, messages or request headers.
        for field in ("provider_name", "error_type", "provider_code"):
            raw_value = metadata.get(field)
            if not isinstance(raw_value, (str, int)) or isinstance(raw_value, bool):
                continue
            value = str(raw_value)
            if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 ._/-]{0,79}", value) and not value.lower().startswith(("sk-", "bearer ")):
                details[field] = value
    retry_after = retry_after_seconds(response.headers.get("Retry-After"))
    if retry_after is not None:
        details["retry_after_seconds"] = retry_after
    for name in ("Limit", "Remaining", "Reset"):
        value = response.headers.get("X-RateLimit-" + name, "")
        if re.fullmatch(r"\d{1,20}(?:\.\d{1,6})?", value):
            details["rate_limit_" + name.lower()] = value
    details["rate_limit_source"] = "unknown"
    try:
        openrouter_response = str(response.request.url) in {
            OPENROUTER_BASE_URL + "/embeddings", OPENROUTER_BASE_URL + "/chat/completions",
        }
    except RuntimeError:
        openrouter_response = False
    if response.status_code == 429 or details.get("error_code") == 429:
        if openrouter_response and any("rate_limit_" + key in details for key in ("limit", "remaining", "reset")):
            details["rate_limit_source"] = "openrouter"
        elif openrouter_response and (details.get("provider_name") or details.get("provider_code")):
            details["rate_limit_source"] = "upstream_provider"
    return details


def provider_error(service: str, code: int | str | None, diagnostics: dict | None = None) -> ModelUnavailable:
    messages = {
        "401": "API anahtarı eksik veya geçersiz.",
        "402": "API kredisi yetersiz; sağlayıcı bakiyesini kontrol edin.",
        "403": "API anahtarının bu model için erişim izni yok.",
        "404": "Model veya istenen özellikleri destekleyen sağlayıcı bulunamadı.",
        "408": "İstek süre sınırını aştı.",
        "429": "API istek sınırına veya sağlayıcı kapasitesine ulaşıldı.",
        "503": "Sağlayıcı şu anda kullanılamıyor.",
    }
    return ModelUnavailable(f"{service}: {messages.get(str(code), 'Sağlayıcı isteği tamamlayamadı; model ve API ayarlarını kontrol edin.')}", diagnostics=diagnostics)


def response_json(response: httpx.Response, service: str, *, allow_list=False):
    try:
        data = response.json()
    except ValueError:
        if response.is_error:
            raise provider_error(service, response.status_code, error_diagnostics(response, {})) from None
        raise
    error = data.get("error") if isinstance(data, dict) else None
    error_data = error if isinstance(error, dict) else {}
    if response.is_error:
        raise provider_error(service, response.status_code, error_diagnostics(response, error_data))
    if allow_list and isinstance(data, list):
        return data
    if not isinstance(data, dict):
        raise ValueError("Expected a JSON object")
    # Gateways can return an upstream error inside an HTTP 200 response.
    if "error" in data:
        raise provider_error(service, error_data.get("code"), error_diagnostics(response, error_data))
    return data
