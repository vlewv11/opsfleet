import hashlib
import json
import time

import numpy as np

from src.agent.embeddings import embed, lexical_scores
from src.utils.config import settings
from src.utils.logger import event

_DIR = settings.data_dir / "knowledge_base"
_INDEX = _DIR / ".index.npz"

RRF_K = 10
COSINE_FLOOR = 0.60
SPREAD_FLOOR = 0.035
LEXICAL_FLOOR = 0.30
QUERY_TTL = 300.0

_corpus_cache: tuple[float, tuple] | None = None
_query_cache: dict[str, tuple[float, list[dict]]] = {}

NO_PRECEDENT = (
    "No prior analyst work matches this question closely enough to be worth following. Rely on the "
    "schema, and say plainly that you are working without precedent rather than stretching an "
    "unrelated one."
)


def _corpus() -> tuple[list[dict], list[str], np.ndarray | None]:
    global _corpus_cache
    paths = sorted(_DIR.glob("*.json"))
    stamp = max((path.stat().st_mtime for path in paths), default=0.0)
    if _corpus_cache and _corpus_cache[0] == stamp:
        return _corpus_cache[1]

    trios = [json.loads(path.read_text()) for path in paths]
    docs = [f"{t['question']} {' '.join(t.get('tags', []))} {t['report']}" for t in trios]
    if not trios:
        _corpus_cache = (stamp, ([], [], None))
        return _corpus_cache[1]

    fingerprint = hashlib.blake2b("|".join(docs).encode(), digest_size=8).hexdigest()
    vectors = None
    if _INDEX.exists():
        cached = np.load(_INDEX, allow_pickle=False)
        if str(cached["fingerprint"]) == fingerprint:
            vectors = cached["vectors"]
    if vectors is None:
        vectors = embed(docs)
        if vectors is not None:
            np.savez(_INDEX, vectors=vectors, fingerprint=np.array(fingerprint))
        else:
            event("golden_lexical_fallback", reason="embeddings unavailable")

    _corpus_cache = (stamp, (trios, docs, vectors))
    return _corpus_cache[1]


def _ranks(scores: np.ndarray) -> np.ndarray:
    ranks = np.empty(len(scores), dtype=int)
    ranks[np.argsort(-scores)] = np.arange(len(scores))
    return ranks


def search(question: str, k: int = 0) -> list[dict]:
    trios, docs, vectors = _corpus()
    if not trios:
        return []

    cached = _query_cache.get(question)
    if cached and time.monotonic() - cached[0] < QUERY_TTL:
        return cached[1]

    lexical = lexical_scores(question, docs)
    cosine = None
    if vectors is not None:
        query_vector = embed([question], query=True)
        if query_vector is not None:
            cosine = vectors @ query_vector[0]

    if cosine is None:
        relevant = lexical.max() >= LEXICAL_FLOOR
        fused, shown = 1.0 / (RRF_K + _ranks(lexical)), lexical
        admissible = lexical >= LEXICAL_FLOOR
    else:
        relevant = cosine.max() >= COSINE_FLOOR and cosine.max() - cosine.mean() >= SPREAD_FLOOR
        fused = 1.0 / (RRF_K + _ranks(cosine))
        if lexical.max() > 0:
            fused = fused + 1.0 / (RRF_K + _ranks(lexical))
        shown, admissible = cosine, cosine >= COSINE_FLOOR

    hits = []
    if relevant:
        order = [i for i in np.argsort(-fused) if admissible[i]][: (k or settings.golden_top_k)]
        hits = [trios[i] | {"score": round(float(shown[i]), 3)} for i in order]

    _query_cache[question] = (time.monotonic(), hits)
    event(
        "golden_search",
        question=question[:120],
        mode="hybrid" if cosine is not None else "lexical",
        hits=[h["id"] for h in hits],
        scores=[h["score"] for h in hits],
        top=round(float((cosine if cosine is not None else lexical).max()), 3),
        spread=round(float(cosine.max() - cosine.mean()), 3) if cosine is not None else None,
    )
    return hits


def render(hits: list[dict]) -> str:
    if not hits:
        return NO_PRECEDENT
    return "\n\n---\n\n".join(
        f"### Precedent: {h['id']} (similarity {h['score']})\n"
        f"**Analyst was asked:** {h['question']}\n"
        f"**Analyst's SQL:**\n```sql\n{h['sql'].replace('{dataset}', settings.bq_dataset)}\n```\n"
        f"**Analyst's interpretation and house conventions:**\n{h['report']}"
        for h in hits
    )
