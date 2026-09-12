import json

import pytest

from src.agent.executor import run_sql
from src.tools.bigquery import QueryError, client, dry_run, execute, schema
from src.utils.config import settings
from src.utils.pii import PolicyError, enforce

pytestmark = pytest.mark.integration

D = settings.bq_dataset
SMALL = f"SELECT state, COUNT(*) AS n FROM `{D}.users` GROUP BY 1 ORDER BY 2 DESC LIMIT 5"


def test_credentials_authenticate_and_target_the_right_project():
    runner = client()
    assert runner.client.project == settings.gcp_project
    assert runner.dataset_id == D


def test_schema_exposes_every_required_table():
    tables = schema()
    assert set(tables) == {"orders", "order_items", "products", "users"}
    assert {"id", "email", "state", "age"} <= set(tables["users"])
    assert {"sale_price", "order_id", "product_id", "status"} <= set(tables["order_items"])


def test_dry_run_estimates_bytes_without_executing():
    assert dry_run(SMALL) > 0


def test_dry_run_enforces_the_cost_cap(monkeypatch):
    monkeypatch.setattr(settings, "max_bytes_billed", 1)
    with pytest.raises(QueryError, match="budget"):
        dry_run(SMALL)


def test_syntax_error_is_mapped_to_query_error():
    with pytest.raises(QueryError) as excinfo:
        dry_run(f"SELECT stat FROMM `{D}.users`")
    assert "\n\n" not in str(excinfo.value)


def test_unknown_column_is_mapped_to_query_error():
    with pytest.raises(QueryError, match="not found|Unrecognized"):
        dry_run(f"SELECT nonexistent_column FROM `{D}.users`")


def test_execute_returns_rows_columns_and_observability_metadata():
    columns, rows, meta = execute(SMALL)
    assert columns == ["state", "n"]
    assert rows and all(set(r) == {"state", "n"} for r in rows)
    assert meta["job_id"] and meta["rows"] == len(rows)
    assert meta["gb_scanned"] >= 0 and isinstance(meta["cache_hit"], bool)


def test_blocked_column_is_rejected_before_reaching_bigquery():
    with pytest.raises(PolicyError):
        enforce(f"SELECT email FROM `{D}.users`")


def test_identifiers_come_back_hashed_from_live_data():
    payload = json.loads(run_sql(f"SELECT id, state FROM `{D}.users` LIMIT 5"))
    assert payload["status"] == "ok"
    assert "SHA256" in payload["sql"]
    ids = [row["id"] for row in payload["rows"]]
    assert all(isinstance(i, str) and len(i) == 12 for i in ids)


def test_empty_result_is_reported_rather_than_retried():
    payload = json.loads(run_sql(f"SELECT state FROM `{D}.users` WHERE state = 'Atlantis'"))
    assert payload["status"] == "empty"
    assert payload["repairs"] == 0


def test_row_limit_is_enforced_against_live_data():
    monkeypatched = json.loads(run_sql(f"SELECT state FROM `{D}.users` LIMIT 100000"))
    assert monkeypatched["row_count"] <= settings.row_limit
