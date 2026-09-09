import pytest

from src.utils.pii import PolicyError, enforce, scrub

D = "`bigquery-public-data.thelook_ecommerce"


@pytest.mark.parametrize(
    "sql",
    [
        f"SELECT email FROM {D}.users`",
        f"SELECT CONCAT(first_name, last_name) AS n FROM {D}.users`",
        f"WITH t AS (SELECT street_address AS a FROM {D}.users`) SELECT a FROM t",
        f"SELECT * FROM {D}.orders`",
        f"SELECT o.* FROM {D}.orders` o",
        f"DELETE FROM {D}.orders`",
        f"SELECT id FROM {D}.users`; SELECT 1",
        "SELECT name FROM `other-project.private.customers`",
        f"SELECT column_name FROM {D}.INFORMATION_SCHEMA.COLUMNS`",
        f"SELECT CAST(user_id AS STRING) AS u FROM {D}.order_items`",
    ],
)
def test_blocked(sql):
    with pytest.raises(PolicyError):
        enforce(sql)


def test_user_identifiers_are_hashed_not_leaked():
    out = enforce(f"SELECT user_id, SUM(sale_price) s FROM {D}.order_items` GROUP BY 1")
    assert "SHA256" in out and "AS user_id" in out


def test_unqualified_id_resolves_to_users():
    assert "SHA256" in enforce(f"SELECT id, state FROM {D}.users`")


def test_product_id_is_not_hashed():
    out = enforce(f"SELECT p.id, p.name FROM {D}.products` p")
    assert "SHA256" not in out


def test_aggregates_over_identifiers_are_allowed():
    out = enforce(f"SELECT status, COUNT(DISTINCT user_id) n FROM {D}.orders` GROUP BY 1")
    assert "COUNT(DISTINCT user_id)" in out and "SHA256" not in out


def test_row_limit_is_forced_and_clamped():
    assert "LIMIT 500" in enforce(f"SELECT state FROM {D}.users`")
    assert "LIMIT 500" in enforce(f"SELECT state FROM {D}.users` LIMIT 100000")
    assert "LIMIT 10" in enforce(f"SELECT state FROM {D}.users` LIMIT 10")


def test_scrub_redacts_contacts_but_keeps_metrics():
    text = scrub("Mail a@b.com or 555-123-4567. Q1 2023-01-01 to 2023-03-31 was 1,234,567.89.")
    assert "a@b.com" not in text and "555-123-4567" not in text
    assert "1,234,567.89" in text and "2023-01-01" in text
