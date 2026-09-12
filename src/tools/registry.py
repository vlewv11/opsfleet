import json

from langchain_core.tools import tool
from langgraph.types import interrupt

from src.agent import memory
from src.agent.executor import run_sql
from src.tools import charts, golden, reports
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

    The precedents for the manager's original question are already in your system prompt. Call this
    only to re-search with different wording when those did not fit. The precedents carry house
    conventions - metric definitions, exclusions, how to frame a finding - that are not in the
    schema and that the business expects you to follow. If nothing matches closely enough you are
    told so explicitly: work from the schema and say you have no precedent, rather than stretching
    an unrelated one.
    """
    return golden.render(golden.search(question))


@tool
def save_report(title: str, body: str, tags: list[str]) -> str:
    """Save a finished report to the user's Saved Reports library. Call this only after presenting
    the report in the conversation. Pass the full report markdown as body."""
    record = reports.save(memory.active_user.get(), title, scrub(body), tags)
    return f"Saved report {record['id']} — \"{record['title']}\"."


@tool
def create_chart(
    title: str, kind: str, labels: list[str], series: dict[str, list[float]], value_label: str = ""
) -> str:
    """Draw a chart from numbers you have already queried and save it as a PNG.

    Use it when a shape carries the point better than a table — a trend over time, a ranking, or a
    two-region comparison — and whenever this manager prefers charts. Never invent the numbers:
    every value must come from a query_data result in this conversation.

    kind is "line" for anything over time, "bar" for comparisons across categories, "barh" when the
    category names are long. labels are the categories themselves. series maps each series name to
    one value per label, so {"Texas": [...], "California": [...]} draws two. value_label names the
    unit the numbers are in ("USD", "orders", "% returned") — never the category axis.
    Tell the manager the file path.
    """
    try:
        path = charts.render(title, kind, labels, series, value_label)
    except ValueError as exc:
        return f"Chart not created: {exc}"
    return f"Chart saved to {path}. Tell the manager the path so they can open it."


@tool
def delete_reports(selector: str, only_this_conversation: bool = False) -> str:
    """Delete saved reports from this manager's library. Destructive — the manager is shown exactly
    which reports match and must confirm before anything is deleted.

    Pass the manager's own words for picking them ("Client X", "Q1", a report id), or "all" for the
    whole library. Set only_this_conversation for "the reports we made in this conversation".
    You can only ever resolve and delete reports belonging to the manager you are talking to.
    """
    user = memory.active_user.get()
    matches = reports.resolve(user, selector, only_this_conversation)
    if not matches:
        return f"No reports of yours match {selector!r}. Nothing was deleted."
    decision = interrupt(
        {
            "action": "delete_reports",
            "reports": [
                {
                    "id": record["id"],
                    "title": record["title"],
                    "created_at": record["created_at"],
                    "preview": " ".join(record["body"].split())[:120],
                }
                for record in matches
            ],
        }
    )
    if str(decision).strip().lower() not in ("yes", "y", "ok", "confirm", "confirmed", "delete"):
        return "Cancelled. Nothing was deleted."
    deleted = reports.delete(user, [record["id"] for record in matches])
    return f"Deleted {deleted} report(s). Say 'undo' within 30 days to restore them."


@tool
def undo_delete() -> str:
    """Restore the reports removed by this manager's most recent delete, within 30 days.
    Call this when the manager says "undo", "restore them" or "put those back"."""
    restored = reports.restore(memory.active_user.get())
    if not restored:
        return "There is nothing to undo."
    return f"Restored {len(restored)}: " + ", ".join(f'"{r["title"]}"' for r in restored)


@tool
def remember_preference(key: str, value: str) -> str:
    """Store a lasting preference for this user so future answers follow it.

    Use short stable keys such as "format", "depth", "charts" or "language". Call this when the user
    expresses a standing preference ("always give me tables", "keep it to three bullets"), not for a
    one-off formatting request.
    """
    memory.remember(memory.active_user.get(), key, value)
    return f"Noted — I'll apply '{key}: {value}' from now on."


TOOLS = [
    describe_data,
    search_precedents,
    query_data,
    create_chart,
    save_report,
    delete_reports,
    undo_delete,
    remember_preference,
]
