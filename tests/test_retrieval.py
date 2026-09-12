import json

import numpy as np
import pytest

from src.agent import embeddings
from src.tools import golden

RELEVANT = {
    "which buyers brought in the most money this year?": "top-customers-by-spend",
    "how does the Levi's line stack up against Calvin Klein on profit?": "compare-two-products",
    "is our month over month growth speeding up or slowing down?": "monthly-revenue-trend",
    "our shoppers in one state buy less than another area, why is that?": "regional-spend-comparison",
    "lots of items came back last month, what happened and who might leave?": "return-rate-and-churn-signal",
    "which departments sell best in the northeast versus the west?": "category-performance-by-region",
}
IRRELEVANT = [
    "what is the capital of France?",
    "write me a python script to parse a csv file",
    "how do I reset my password?",
    "tell me a joke about accountants",
    "who won the world cup in 2022?",
    "explain quantum entanglement",
    "what are the office parking rules?",
    "what data do we have and what can I ask about?",
    "how many orders are currently in processing status?",
    "what is the average delivery time from order to shipment?",
    "list every brand we carry",
]


@pytest.fixture(autouse=True)
def clear_caches():
    golden._corpus_cache = None
    golden._query_cache.clear()
    yield
    golden._corpus_cache = None
    golden._query_cache.clear()


@pytest.fixture
def corpus(monkeypatch):
    def build(vectors):
        trios = [
            {"id": f"trio-{i}", "question": f"q{i}", "sql": "", "report": "", "tags": []}
            for i in range(len(vectors))
        ]
        docs = ["alpha revenue", "beta returns", "gamma region", "delta margin"][: len(vectors)]
        monkeypatch.setattr(golden, "_corpus", lambda: (trios, docs, np.asarray(vectors, dtype=np.float32)))
        return trios

    return build


def _query(monkeypatch, vector):
    monkeypatch.setattr(golden, "embed", lambda texts, query=False: np.asarray([vector], dtype=np.float32))


def test_a_clear_semantic_match_is_returned(corpus, monkeypatch):
    corpus(np.eye(4))
    _query(monkeypatch, [1, 0, 0, 0])
    assert [h["id"] for h in golden.search("anything")] == ["trio-0"]


def test_a_uniformly_weak_match_returns_no_precedent(corpus, monkeypatch):
    corpus(np.eye(4))
    _query(monkeypatch, [0.5, 0.5, 0.5, 0.5])
    assert golden.search("anything") == []


def test_a_corpus_that_cannot_discriminate_returns_no_precedent(corpus, monkeypatch):
    corpus(np.tile([1.0, 0.0, 0.0, 0.0], (4, 1)))
    _query(monkeypatch, [1, 0, 0, 0])
    assert golden.search("every trio is identical") == []


def test_render_states_the_absence_rather_than_staying_silent():
    text = golden.render([])
    assert "without precedent" in text and "schema" in text


def test_a_repeated_question_is_embedded_once(corpus, monkeypatch):
    corpus(np.eye(4))
    calls = []

    def counted(texts, query=False):
        calls.append(texts)
        return np.asarray([[1, 0, 0, 0]], dtype=np.float32)

    monkeypatch.setattr(golden, "embed", counted)
    first = golden.search("same question")
    assert golden.search("same question") == first
    assert len(calls) == 1


def test_corpus_reloads_when_the_knowledge_base_changes(monkeypatch, tmp_path):
    monkeypatch.setattr(golden, "_DIR", tmp_path)
    monkeypatch.setattr(golden, "_INDEX", tmp_path / ".index.npz")
    monkeypatch.setattr(golden, "embed", lambda *a, **k: None)
    trio = {"id": "one", "question": "q", "sql": "", "report": "r", "tags": []}
    (tmp_path / "01.json").write_text(json.dumps(trio))
    assert len(golden._corpus()[0]) == 1
    (tmp_path / "02.json").write_text(json.dumps(trio | {"id": "two"}))
    assert len(golden._corpus()[0]) == 2


def test_stopwords_do_not_create_lexical_overlap():
    scores = embeddings.lexical_scores(
        "what is the capital of France?", ["which of our customers spend the most"]
    )
    assert scores[0] == 0.0


@pytest.mark.integration
@pytest.mark.parametrize("question,expected", RELEVANT.items(), ids=lambda v: v[:24])
def test_live_retrieval_finds_the_right_precedent(question, expected):
    hits = [h["id"] for h in golden.search(question)]
    assert expected in hits, f"{question!r} -> {hits}"


@pytest.mark.integration
@pytest.mark.parametrize("question", IRRELEVANT, ids=lambda v: v[:24])
def test_live_retrieval_rejects_questions_with_no_precedent(question):
    assert golden.search(question) == []
