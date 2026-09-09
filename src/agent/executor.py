import json
import re
import time

from langchain_core.messages import HumanMessage

from src.models.llm_client import get_llm
from src.prompts.agent_prompts import REPAIR
from src.tools.bigquery import QueryError, dry_run, execute, schema
from src.utils.config import settings
from src.utils.logger import event
from src.utils.pii import PolicyError, describe_policy, enforce, scrub

_FENCE = re.compile(r"^\s*```(?:sql)?\s*|\s*```\s*$", re.I)


def run_sql(sql: str) -> str:
    started = time.perf_counter()
    history: list[dict] = []

    for attempt in range(settings.max_sql_repairs + 1):
        try:
            safe = enforce(sql)
            dry_run(safe)
            columns, rows, meta = execute(safe)
        except (PolicyError, QueryError) as exc:
            reason = str(exc)
            history.append({"attempt": attempt, "error": reason, "sql": sql})
            event("sql_rejected", attempt=attempt, kind=type(exc).__name__, error=reason[:300])
            if attempt == settings.max_sql_repairs:
                event("sql_gave_up", attempts=attempt + 1)
                return json.dumps(
                    {
                        "status": "failed",
                        "attempts": attempt + 1,
                        "last_error": reason,
                        "guidance": "Do not retry this query. Tell the user plainly what could not "
                        "be answered and why, or ask a narrower question of the data.",
                    }
                )
            try:
                sql = _repair(sql, reason)
            except Exception as exc:
                event("repair_unavailable", error=str(exc)[:200])
                return json.dumps(
                    {"status": "failed", "attempts": attempt + 1, "last_error": reason,
                     "guidance": "The repair service is unavailable. Report the failure to the user."}
                )
            continue

        elapsed = round(time.perf_counter() - started, 2)
        if not rows:
            event("sql_empty", seconds=elapsed, **meta)
            return json.dumps(
                {
                    "status": "empty",
                    "sql": safe,
                    "repairs": len(history),
                    "guidance": "The query was valid but matched no rows. Do not re-run it "
                    "unchanged. Check your filter values against the data (spelling, date range, "
                    "status values) with a small probing query, or tell the user no data matched.",
                }
            )

        event("sql_ok", seconds=elapsed, repairs=len(history), **meta)
        return scrub(
            json.dumps(
                {
                    "status": "ok",
                    "sql": safe,
                    "columns": columns,
                    "row_count": len(rows),
                    "truncated": len(rows) >= settings.row_limit,
                    "repairs": len(history),
                    "rows": rows,
                },
                default=str,
            )
        )


def _repair(sql: str, error: str) -> str:
    response = get_llm(fast=True).invoke(
        [
            HumanMessage(
                REPAIR.format(
                    sql=sql,
                    error=error,
                    policy=describe_policy(),
                    schema=json.dumps(schema()),
                )
            )
        ]
    )
    repaired = _FENCE.sub("", str(response.text)).strip()
    event("sql_repaired", before=sql[:200], after=repaired[:200])
    return repaired
