from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel
from pydantic import BaseModel, Field

from src.utils.config import ROOT, settings

_CONFIGS = ROOT / "configs"


class APIKeyError(RuntimeError):
    pass


class LLMParameters(BaseModel):
    temperature: float = Field(default=0.7, ge=0.0, le=1.0)
    max_tokens: int = Field(default=1000, gt=0)
    top_p: float = Field(default=0.9, ge=0.0, le=1.0)


class ModelConfig(BaseModel):
    name: str


class OpenRouterSettings(BaseModel):
    timeout: int = Field(default=30, gt=0)
    max_retries: int = Field(default=3, ge=0)


class OllamaSettings(BaseModel):
    base_url: str = "http://localhost:11434"
    timeout: int = Field(default=60, gt=0)


class LLMConfig(BaseModel):
    platform: Literal["openrouter", "ollama"]
    model: ModelConfig
    parameters: LLMParameters = Field(default_factory=LLMParameters)
    openrouter: OpenRouterSettings | None = None
    ollama: OllamaSettings | None = None


class UnifiedLLMClient:
    def __init__(self, config_path: Path) -> None:
        if not config_path.exists():
            raise FileNotFoundError(f"Configuration file not found: {config_path}")
        self.config = LLMConfig(**yaml.safe_load(config_path.read_text())["llm"])
        self.client = self._initialize_model()

    def _initialize_model(self) -> BaseChatModel:
        params = self.config.parameters
        if self.config.platform == "openrouter":
            if not settings.openrouter_api_key:
                raise APIKeyError(
                    "OPENROUTER_API_KEY not found in environment. Please set it in your .env file."
                )
            options = self.config.openrouter or OpenRouterSettings()
            return init_chat_model(
                model=self.config.model.name,
                model_provider="openai",
                api_key=settings.openrouter_api_key,
                base_url="https://openrouter.ai/api/v1",
                temperature=params.temperature,
                max_tokens=params.max_tokens,
                top_p=params.top_p,
                timeout=options.timeout,
                max_retries=options.max_retries,
            )
        options = self.config.ollama or OllamaSettings()
        return init_chat_model(
            model=self.config.model.name,
            model_provider="ollama",
            base_url=options.base_url,
            temperature=params.temperature,
            num_predict=params.max_tokens,
            top_p=params.top_p,
            timeout=options.timeout,
        )


@lru_cache(maxsize=2)
def client(fast: bool) -> UnifiedLLMClient:
    return UnifiedLLMClient(_CONFIGS / f"{'fast' if fast else 'reasoning'}.yaml")


def get_llm(fast: bool = False) -> BaseChatModel:
    return client(fast).client
