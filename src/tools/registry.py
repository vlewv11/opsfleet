import json

from langchain_core.tools import tool

from src.agent import memory
from src.agent.executor import run_sql
from src.tools import golden, reports
from src.tools.bigquery import schema
from src.utils.pii import BLOCKED_NAMES, describe_policy, scrub


@tool
def query_data(sql: str) -> str:
    """Run one read-only BigQuery SELECT against the retail dataset and return the rows as JSON.

    The query is validated, PII-masked and cost-capped before it runs, and is automatically
    repaired and retried if it is rejected. Returns status "ok" with rows, "empty" if nothing
    matched, or "failed" with the reason. Prefer several small aggregate queries over one large one.
    """
    return run_sql(sql)


@tool
def describe_data() -> str:
    """Return the tables, columns and types available, plus which columns are blocked by policy.

    Use this to answer questions about what data exists and what analysis is possible, and to check
    exact column names before writing SQL.
    """
    return json.dumps(
        {"dataset_schema": schema(), "blocked_columns": sorted(BLOCKED_NAMES), "policy": describe_policy()}
    )


@tool
def search_precedents(question: str) -> str:
    """Retrieve past analyst work (question, the SQL they wrote, and their written interpretation).

    Call this before writing SQL for any non-trivial analysis. The precedents carry house
    conventions - metric definitions, exclusions, how to frame a finding - that are not in the
    schema and that the business expects you to follow.
    """
    return golden.render(golden.search(question))


@tool
def save_report(title: str, body: str, tags: list[str]) -> str:
    """Save a finished report to the user's Saved Reports library. Call this only after presenting
    the report in the conversation. Pass the full report markdown as body."""
    record = reports.save(memory.active_user.get(), title, scrub(body), tags)
    return f"Saved report {record['id']} — \"{record['title']}\"."


@tool
def remember_preference(key: str, value: str) -> str:
    """Store a lasting preference for this user so future answers follow it.

    Use short stable keys such as "format", "depth", "charts" or "language". Call this when the user
    expresses a standing preference ("always give me tables", "keep it to three bullets"), not for a
    one-off formatting request.
    """
    memory.remember(memory.active_user.get(), key, value)
    return f"Noted — I'll apply '{key}: {value}' from now on."


TOOLS = [describe_data, search_precedents, query_data, save_report, remember_preference]
