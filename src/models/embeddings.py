import re
from functools import lru_cache

import numpy as np

from src.utils.config import settings
from src.utils.logger import event

_TOKEN = re.compile(r"[a-z0-9_]+")


@lru_cache(maxsize=1)
def _backend():
    if settings.llm_provider.lower() != "google" or not settings.google_api_key:
        return None
    from langchain_google_genai import GoogleGenerativeAIEmbeddings

    return GoogleGenerativeAIEmbeddings(
        model=settings.embedding_model, google_api_key=settings.google_api_key
    )


def embed(texts: list[str], query: bool = False) -> np.ndarray | None:
    backend = _backend()
    if backend is None:
        return None
    try:
        vectors = (
            [backend.embed_query(texts[0])] if query else backend.embed_documents(texts)
        )
    except Exception as exc:
        event("embed_failed", error=str(exc)[:200])
        return None
    matrix = np.asarray(vectors, dtype=np.float32)
    return matrix / (np.linalg.norm(matrix, axis=1, keepdims=True) + 1e-9)


def lexical_scores(query: str, documents: list[str]) -> np.ndarray:
    terms = set(_TOKEN.findall(query.lower()))
    if not terms:
        return np.zeros(len(documents), dtype=np.float32)
    return np.array(
        [
            len(terms & set(_TOKEN.findall(doc.lower()))) / len(terms)
            for doc in documents
        ],
        dtype=np.float32,
    )
