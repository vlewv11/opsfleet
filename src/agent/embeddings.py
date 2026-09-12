import re
from functools import lru_cache

import numpy as np

from src.utils.config import settings
from src.utils.logger import event

_TOKEN = re.compile(r"[a-z0-9_]+")
_STOP = frozenset(
    "and are but can did does for from had has have how its not our out she than that the them "
    "then there these they this those was were what when where which who why will with you your "
    "about any been because could would should into more most much only other over same some "
    "such very want way well were".split()
)


@lru_cache(maxsize=1)
def _backend():
    if not settings.google_api_key:
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


def _terms(text: str) -> set[str]:
    return {token for token in _TOKEN.findall(text.lower()) if len(token) > 2 and token not in _STOP}


def lexical_scores(query: str, documents: list[str]) -> np.ndarray:
    terms = _terms(query)
    if not terms:
        return np.zeros(len(documents), dtype=np.float32)
    return np.array(
        [len(terms & _terms(doc)) / len(terms) for doc in documents],
        dtype=np.float32,
    )
