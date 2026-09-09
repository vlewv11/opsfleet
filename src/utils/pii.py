import re

import sqlglot
from sqlglot import exp

from src.utils.config import settings

BLOCKED = {
    "users": {
        "email",
        "first_name",
        "last_name",
        "street_address",
        "postal_code",
        "latitude",
        "longitude",
        "user_geom",
    }
}
BLOCKED_NAMES = {c for cols in BLOCKED.values() for c in cols}
PSEUDONYM_NAMES = {"user_id", "customer_id"}
ALLOWED_TABLES = {"orders", "order_items", "products", "users"}
ALLOWED_DATASET = settings.bq_dataset.rsplit(".", 1)[-1]

_SCRUB = (
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.]{2,}"), "[REDACTED_EMAIL]"),
    (
        re.compile(
            r"(?<!\d)(?:\+\d{1,3}[\s.-]?)?(?:\(\d{3}\)|\d{3})[\s.-]\d{3}[\s.-]\d{4}(?!\d)"
        ),
        "[REDACTED_PHONE]",
    ),
    (
        re.compile(r"\b(?:4\d{3}|5[1-5]\d{2}|3[47]\d{2}|6011)[ -]?\d{4}[ -]?\d{4}[ -]?\d{2,4}\b"),
        "[REDACTED_CARD]",
    ),
    (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), "[REDACTED_IP]"),
)


class PolicyError(ValueError):
    pass


def describe_policy() -> str:
    return (
        f"Queryable tables: {', '.join(sorted(ALLOWED_TABLES))} in `{settings.bq_dataset}`.\n"
        f"Columns you must never select, filter on, or join on: "
        f"{', '.join(sorted(BLOCKED_NAMES))}.\n"
        "Star projections (SELECT *, t.*) are rejected; list columns explicitly. COUNT(*) is fine.\n"
        "Only a single read-only SELECT/WITH statement is accepted; no DML, DDL or scripting.\n"
        f"Every query is capped at {settings.row_limit} rows. Aggregate rather than paginate.\n"
        "User identifiers are irreversibly hashed before you or the user ever see them."
    )


def _output_selects(tree: exp.Expression) -> list[exp.Select]:
    if isinstance(tree, exp.SetOperation):
        return _output_selects(tree.left) + _output_selects(tree.right)
    return [tree] if isinstance(tree, exp.Select) else []


def _is_user_id(column: exp.Column, aliases: dict[str, str]) -> bool:
    name = column.name.lower()
    if name in PSEUDONYM_NAMES:
        return True
    if name != "id":
        return False
    scope = column.table.lower()
    return aliases.get(scope) == "users" or (not scope and "users" in aliases.values())


def _hash(column: exp.Column, salt: str) -> exp.Expression:
    return sqlglot.parse_one(
        f"SUBSTR(TO_HEX(SHA256(CONCAT('{salt}', "
        f"CAST({column.sql('bigquery')} AS STRING)))), 1, 12)",
        dialect="bigquery",
    )


def enforce(sql: str) -> str:
    try:
        statements = sqlglot.parse(sql, dialect="bigquery")
    except sqlglot.ParseError as exc:
        raise PolicyError(f"SQL does not parse: {exc}") from exc

    statements = [s for s in statements if s is not None]
    if len(statements) != 1:
        raise PolicyError("Submit exactly one statement.")
    tree = statements[0]
    if not isinstance(tree, (exp.Select, exp.SetOperation)):
        raise PolicyError(f"Only SELECT/WITH queries are permitted, got {tree.key.upper()}.")

    ctes = {c.alias_or_name.lower() for c in tree.find_all(exp.CTE)}
    aliases = {}
    for table in tree.find_all(exp.Table):
        name = table.name.lower()
        if name in ctes:
            continue
        if name not in ALLOWED_TABLES:
            raise PolicyError(f"Table `{table.sql('bigquery')}` is outside the approved dataset.")
        if table.db and table.db.lower() != ALLOWED_DATASET:
            raise PolicyError(f"Dataset `{table.db}` is not approved.")
        aliases[(table.alias or table.name).lower()] = name

    for star in tree.find_all(exp.Star):
        if not isinstance(star.parent, exp.AggFunc):
            raise PolicyError("Star projections are blocked; list the columns you need explicitly.")

    for column in tree.find_all(exp.Column):
        if column.name.lower() in BLOCKED_NAMES:
            raise PolicyError(
                f"Column `{column.name}` is personally identifying and is blocked by policy. "
                "Rewrite the query using aggregates or non-identifying attributes "
                "(city, state, country, age, gender, traffic_source)."
            )

    salt = settings.pii_salt.replace("'", "")
    for select in _output_selects(tree):
        for projection in select.expressions:
            column = projection.this if isinstance(projection, exp.Alias) else projection
            if isinstance(column, exp.Column) and _is_user_id(column, aliases):
                hashed = _hash(column, salt)
                if isinstance(projection, exp.Alias):
                    projection.set("this", hashed)
                else:
                    column.replace(exp.alias_(hashed, column.alias_or_name))
                continue
            for inner in projection.find_all(exp.Column):
                if _is_user_id(inner, aliases) and inner.find_ancestor(exp.AggFunc) is None:
                    raise PolicyError(
                        f"`{inner.sql('bigquery')}` is a customer identifier and may only be "
                        "returned as a bare column (it is then hashed) or inside an aggregate "
                        "such as COUNT(DISTINCT ...). Remove the surrounding expression."
                    )

    limit = tree.args.get("limit")
    current = int(limit.expression.name) if limit and limit.expression.is_int else None
    if current is None or current > settings.row_limit:
        tree = tree.limit(settings.row_limit)

    return tree.sql(dialect="bigquery", pretty=True)


def scrub(text: str) -> str:
    for pattern, replacement in _SCRUB:
        text = pattern.sub(replacement, text)
    return text
