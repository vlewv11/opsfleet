from functools import lru_cache
from pathlib import Path

import yaml
from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel
from pydantic import BaseModel, Field

from src.utils.config import ROOT, settings

PLATFORM = "openrouter"
_CONFIGS = ROOT / "configs"


class APIKeyError(RuntimeError):
    pass


class LLMConfig(BaseModel):
    model: str
    temperature: float = Field(default=0.7, ge=0.0, le=1.0)
    max_tokens: int = Field(default=1000, gt=0)
    top_p: float = Field(default=0.9, ge=0.0, le=1.0)
    timeout: int = Field(default=60, gt=0)
    max_retries: int = Field(default=3, ge=0)


class UnifiedLLMClient:
    def __init__(self, config_path: Path) -> None:
        if not config_path.exists():
            raise FileNotFoundError(f"Configuration file not found: {config_path}")
        if not settings.openrouter_api_key:
            raise APIKeyError(
                "OPENROUTER_API_KEY not found in environment. Please set it in your .env file."
            )
        self.config = LLMConfig(**yaml.safe_load(config_path.read_text())["llm"])
        self.client: BaseChatModel = init_chat_model(
            model=self.config.model,
            model_provider="openai",
            api_key=settings.openrouter_api_key,
            base_url="https://openrouter.ai/api/v1",
            temperature=self.config.temperature,
            max_tokens=self.config.max_tokens,
            top_p=self.config.top_p,
            timeout=self.config.timeout,
            max_retries=self.config.max_retries,
        )


@lru_cache(maxsize=2)
def client(fast: bool) -> UnifiedLLMClient:
    return UnifiedLLMClient(_CONFIGS / f"{'fast' if fast else 'reasoning'}.yaml")


def get_llm(fast: bool = False) -> BaseChatModel:
    return client(fast).client
