from functools import lru_cache

from langchain_core.language_models import BaseChatModel

from src.utils.config import settings


@lru_cache(maxsize=4)
def get_llm(fast: bool = False) -> BaseChatModel:
    model = settings.fast_model if fast else settings.reasoning_model
    provider = settings.llm_provider.lower()

    if provider == "google":
        from langchain_google_genai import ChatGoogleGenerativeAI

        if not settings.google_api_key:
            raise RuntimeError("GOOGLE_API_KEY is not set; see README setup.")
        return ChatGoogleGenerativeAI(
            model=model,
            google_api_key=settings.google_api_key,
            temperature=0.0,
            max_retries=4,
            timeout=90,
        )

    if provider == "openrouter":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=model,
            api_key=settings.openrouter_api_key,
            base_url=settings.openrouter_base_url,
            temperature=0.0,
            max_retries=4,
            timeout=90,
        )

    if provider == "ollama":
        from langchain_ollama import ChatOllama

        return ChatOllama(model=model, base_url=settings.ollama_base_url, temperature=0.0)

    raise RuntimeError(f"Unknown LLM_PROVIDER '{settings.llm_provider}'.")
