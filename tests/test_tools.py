import json

import pytest

import src.agent.executor as ex
from src.agent import memory
from src.tools import golden, reports
from src.tools.bigquery import QueryError
from src.utils.config import settings

GOOD = f"SELECT state FROM `{settings.bq_dataset}.users` LIMIT 5"


@pytest.fixture
def stub_bq(monkeypatch):
    calls = {"dry": 0, "exec": 0, "repair": 0}

    def repair(sql, error):
        calls["repair"] += 1
        return GOOD

    monkeypatch.setattr(ex, "_repair", repair)
    monkeypatch.setattr(ex, "execute", lambda sql: (calls.__setitem__("exec", calls["exec"] + 1), (["state"], [{"state": "Texas"}], {"job_id": "j", "gb_scanned": 0.1, "cache_hit": False, "rows": 1}))[1])
    return calls


def test_repairs_once_then_succeeds(stub_bq, monkeypatch):
    attempts = iter([QueryError("Syntax error: unexpected FROMM at [1:8]"), None])

    def dry_run(sql):
        error = next(attempts)
        if error:
            raise error
        return 1000

    monkeypatch.setattr(ex, "dry_run", dry_run)
    result = json.loads(ex.run_sql(GOOD))
    assert result["status"] == "ok" and result["repairs"] == 1
    assert stub_bq["repair"] == 1


def test_repair_budget_is_bounded(stub_bq, monkeypatch):
    monkeypatch.setattr(ex, "dry_run", lambda sql: (_ for _ in ()).throw(QueryError("still broken")))
    result = json.loads(ex.run_sql(GOOD))
    assert result["status"] == "failed"
    assert result["attempts"] == settings.max_sql_repairs + 1
    assert stub_bq["repair"] == settings.max_sql_repairs
    assert stub_bq["exec"] == 0


def test_empty_result_is_reported_not_retried(stub_bq, monkeypatch):
    monkeypatch.setattr(ex, "dry_run", lambda sql: 10)
    monkeypatch.setattr(ex, "execute", lambda sql: ([], [], {"job_id": "j", "gb_scanned": 0.0, "cache_hit": False, "rows": 0}))
    result = json.loads(ex.run_sql(GOOD))
    assert result["status"] == "empty" and stub_bq["repair"] == 0


def test_policy_violation_feeds_the_repair_loop(stub_bq, monkeypatch):
    monkeypatch.setattr(ex, "dry_run", lambda sql: 10)
    result = json.loads(ex.run_sql(f"SELECT email FROM `{settings.bq_dataset}.users`"))
    assert result["status"] == "ok" and stub_bq["repair"] == 1


def test_rows_are_scrubbed_on_the_way_out(monkeypatch):
    monkeypatch.setattr(ex, "dry_run", lambda sql: 10)
    monkeypatch.setattr(ex, "execute", lambda sql: (["note"], [{"note": "ping a@b.com"}], {"job_id": "j", "gb_scanned": 0.0, "cache_hit": False, "rows": 1}))
    assert "a@b.com" not in ex.run_sql(GOOD)


def test_precedent_retrieval_ranks_a_relevant_trio(monkeypatch):
    monkeypatch.setattr(golden, "embed", lambda *a, **k: None)
    hits = golden.search("compare product A against product B on performance")
    assert hits and hits[0]["id"] == "compare-two-products"


def test_reports_and_preferences_are_per_user(monkeypatch, tmp_path):
    monkeypatch.setattr(reports, "_DIR", tmp_path / "reports")
    monkeypatch.setattr(memory, "_PREFS", tmp_path / "prefs.json")

    reports.save("manager_a", "Q1 Review", "body", ["q1"])
    reports.save("manager_b", "Stock Review", "body", [])
    assert len(reports.listing("manager_a")) == 1
    assert len(reports.listing()) == 2

    memory.remember("manager_a", "format", "tables")
    assert memory.preferences("manager_a")["format"] == "tables"
    assert memory.preferences("manager_b")["format"] == memory.DEFAULTS["format"]


@pytest.fixture
def library(monkeypatch, tmp_path):
    monkeypatch.setattr(reports, "_DIR", tmp_path / "reports")
    memory.active_user.set("manager_a")
    memory.active_thread.set("thread-1")
    a = reports.save("manager_a", "Q1 Review for Client X", "Client X grew 12%.", ["q1"])
    memory.active_thread.set("thread-2")
    b = reports.save("manager_a", "Returns deep dive", "Outerwear drove returns.", ["returns"])
    c = reports.save("manager_b", "Client X pricing", "Client X margin fell.", ["pricing"])
    return a, b, c


def test_resolve_is_owner_scoped(library):
    mine, _, theirs = library
    matches = reports.resolve("manager_a", "Client X")
    assert [r["id"] for r in matches] == [mine["id"]]
    assert theirs["id"] not in [r["id"] for r in reports.resolve("manager_a", "all")]


def test_delete_ignores_ids_the_caller_does_not_own(library):
    mine, _, theirs = library
    assert reports.delete("manager_a", [mine["id"], theirs["id"]]) == 1
    assert reports.listing("manager_b")[0]["id"] == theirs["id"]


def test_delete_is_soft_and_undoable(library):
    mine, other, _ = library
    reports.delete("manager_a", [mine["id"]])
    assert [r["id"] for r in reports.listing("manager_a")] == [other["id"]]
    assert [r["id"] for r in reports.restore("manager_a")] == [mine["id"]]
    assert len(reports.listing("manager_a")) == 2
    assert reports.restore("manager_a") == []


def test_conversation_scope_resolves_against_the_thread(library):
    _, other, _ = library
    memory.active_thread.set("thread-2")
    matches = reports.resolve("manager_a", "all", this_conversation=True)
    assert [r["id"] for r in matches] == [other["id"]]
