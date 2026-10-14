from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from .providers import TYPESAFE_BASE_URL, is_openrouter

ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="INTENT_", env_file=ROOT / ".env", extra="ignore")
    data_dir: Path = ROOT / "data/private"
    openrouter_api_key: str = Field(default="", repr=False)
    llm_base_url: str = ""
    llm_api_key: str = Field(default="", repr=False)
    llm_model: str = "Qwen/Qwen3.5-35B-A3B"
    llm_protocol: Literal["openai", "typesafe"] = "openai"
    llm_timeout_seconds: float = Field(default=20, ge=1, le=120)
    llm_response_format: Literal["json_schema", "json_object", "prompt"] = "json_schema"
    llm_send_temperature: bool = True
    llm_connection_id: str = ""
    llm_provider_only: list[str] = Field(default_factory=list, max_length=10)
    llm_thinking_parameter: Literal["chat_template", "top_level", "openrouter", "none"] = "chat_template"
    llm_reasoning: Literal["auto", "disabled", "low", "none"] = "auto"
    llm_max_tokens: int = Field(default=600, ge=128, le=8192)
    model_catalog_path: Path = ROOT / "data/model-presets.json"
    embedding_mode: Literal["disabled", "local", "http"] = "disabled"
    embedding_model: str = "intfloat/multilingual-e5-base"
    embedding_profile: Literal["auto", "e5", "qwen3", "plain"] = "auto"
    embedding_query_instruction: str = Field(default="Given a Turkish banking customer request, retrieve the banking intent descriptions and examples that match the customer's intended operation or question.", min_length=1, max_length=1000)
    embedding_batch_size: int = Field(default=32, ge=1, le=256)
    embedding_timeout_seconds: float = Field(default=30, ge=1, le=120)
    embedding_cpu_threads: int = Field(default=4, ge=1, le=32)
    embedding_local_files_only: bool = False
    embedding_base_url: str = ""
    embedding_api_key: str = Field(default="", repr=False)
    embedding_connection_id: str = ""
    model_credentials_file: Path = ROOT / ".env"
    embedding_provider_only: list[str] = Field(default_factory=list, max_length=10)
    candidate_k: int = Field(default=20, ge=2, le=40)
    retrieval_representation: Literal["combined", "separate"] = "combined"
    reranker_mode: Literal["disabled", "local", "http"] = "disabled"
    reranker_model: str = "BAAI/bge-reranker-v2-m3"
    reranker_base_url: str = ""
    reranker_api_key: str = Field(default="", repr=False)
    reranker_connection_id: str = ""
    reranker_protocol: Literal["cohere", "tei"] = "cohere"
    reranker_timeout_seconds: float = Field(default=30, ge=1, le=120)
    reranker_batch_size: int = Field(default=16, ge=1, le=128)
    reranker_local_files_only: bool = False
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    trusted_hosts: list[str] = Field(default_factory=lambda: ["localhost", "127.0.0.1", "::1"])

    @property
    def resolved_llm_reasoning(self) -> str:
        if self.llm_reasoning != "auto":
            return self.llm_reasoning
        if "gpt-oss" in self.llm_model.lower():
            return "low"
        if "instruct-2507" in self.llm_model.lower():
            return "none"
        return "disabled"

    @property
    def resolved_llm_max_tokens(self) -> int:
        # Reasoning tokens consume the completion budget even when excluded from the response.
        return max(4096, self.llm_max_tokens) if self.resolved_llm_reasoning == "low" else self.llm_max_tokens

    @property
    def llm_configured(self) -> bool:
        if self.llm_protocol == "typesafe":
            return self.llm_base_url.strip().rstrip("/") == TYPESAFE_BASE_URL and bool(self.llm_api_key.strip())
        return bool(self.llm_base_url.strip()) and (not is_openrouter(self.llm_base_url) or bool(self.resolved_llm_api_key))

    @property
    def resolved_llm_api_key(self) -> str:
        if self.llm_protocol == "typesafe":
            return self.llm_api_key.strip()
        return self.llm_api_key.strip() or (self.openrouter_api_key.strip() if is_openrouter(self.llm_base_url) else "")

    @property
    def resolved_embedding_api_key(self) -> str:
        return self.embedding_api_key.strip() or (self.openrouter_api_key.strip() if is_openrouter(self.embedding_base_url) else "")

    @property
    def resolved_embedding_profile(self) -> str:
        if self.embedding_profile != "auto":
            return self.embedding_profile
        model = self.embedding_model.lower()
        if "qwen3-embedding" in model:
            return "qwen3"
        if "multilingual-e5" in model or model.startswith("intfloat/e5-"):
            return "e5"
        return "plain"
