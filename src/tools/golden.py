import hashlib
import json
from functools import lru_cache

import numpy as np

from src.agent.embeddings import embed, lexical_scores
from src.utils.config import settings
from src.utils.logger import event

_DIR = settings.data_dir / "knowledge_base"
_INDEX = _DIR / ".index.npz"


@lru_cache(maxsize=1)
def _corpus() -> tuple[list[dict], list[str], np.ndarray | None]:
    trios = [json.loads(path.read_text()) for path in sorted(_DIR.glob("*.json"))]
    docs = [f"{t['question']} {' '.join(t.get('tags', []))} {t['report']}" for t in trios]
    if not trios:
        return [], [], None

    fingerprint = hashlib.blake2b("|".join(docs).encode(), digest_size=8).hexdigest()
    if _INDEX.exists():
        cached = np.load(_INDEX, allow_pickle=False)
        if str(cached["fingerprint"]) == fingerprint:
            return trios, docs, cached["vectors"]

    vectors = embed(docs)
    if vectors is not None:
        np.savez(_INDEX, vectors=vectors, fingerprint=np.array(fingerprint))
    else:
        event("golden_lexical_fallback", reason="embeddings unavailable")
    return trios, docs, vectors


def search(question: str, k: int = 0) -> list[dict]:
    trios, docs, vectors = _corpus()
    if not trios:
        return []
    scores = lexical_scores(question, docs)
    if vectors is not None:
        query_vector = embed([question], query=True)
        if query_vector is not None:
            scores = 0.75 * (vectors @ query_vector[0]) + 0.25 * scores
    ranked = np.argsort(-scores)[: (k or settings.golden_top_k)]
    hits = [trios[i] | {"score": round(float(scores[i]), 3)} for i in ranked if scores[i] > 0.05]
    event("golden_search", question=question[:120], hits=[h["id"] for h in hits])
    return hits


def render(hits: list[dict]) -> str:
    if not hits:
        return "No prior analyst work matched this question. Rely on the schema and state that openly."
    return "\n\n---\n\n".join(
        f"### Precedent: {h['id']} (similarity {h['score']})\n"
        f"**Analyst was asked:** {h['question']}\n"
        f"**Analyst's SQL:**\n```sql\n{h['sql'].replace('{dataset}', settings.bq_dataset)}\n```\n"
        f"**Analyst's interpretation and house conventions:**\n{h['report']}"
        for h in hits
    )
