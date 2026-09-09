import json
from functools import lru_cache

from google.api_core import exceptions, retry
from google.cloud import bigquery

from src.utils.config import settings
from src.utils.logger import event

TABLES = ("orders", "order_items", "products", "users")
_CACHE = settings.data_dir / "schema.json"
_RETRY = retry.Retry(
    predicate=retry.if_exception_type(
        exceptions.ServerError, exceptions.TooManyRequests, ConnectionError, TimeoutError
    ),
    initial=1.0,
    maximum=8.0,
    timeout=45.0,
)


class QueryError(RuntimeError):
    pass


@lru_cache(maxsize=1)
def client() -> bigquery.Client:
    return bigquery.Client(project=settings.gcp_project or None, location=settings.bq_location)


def dry_run(sql: str) -> int:
    try:
        job = client().query(
            sql, job_config=bigquery.QueryJobConfig(dry_run=True, use_query_cache=False)
        )
    except exceptions.BadRequest as exc:
        raise QueryError(exc.message.split("\n\n")[0]) from exc
    if job.total_bytes_processed > settings.max_bytes_billed:
        raise QueryError(
            f"Query would scan {job.total_bytes_processed / 1e9:.1f} GB, over the "
            f"{settings.max_bytes_billed / 1e9:.1f} GB budget. Narrow the date range or aggregate."
        )
    return job.total_bytes_processed


def execute(sql: str) -> tuple[list[str], list[dict], dict]:
    try:
        job = client().query(
            sql,
            job_config=bigquery.QueryJobConfig(
                maximum_bytes_billed=settings.max_bytes_billed, use_query_cache=True
            ),
            retry=_RETRY,
        )
        result = job.result(timeout=settings.query_timeout_s, max_results=settings.row_limit)
    except exceptions.BadRequest as exc:
        raise QueryError(exc.message.split("\n\n")[0]) from exc
    except exceptions.Forbidden as exc:
        raise QueryError(f"BigQuery denied the request: {exc.message}") from exc
    except (exceptions.GoogleAPIError, TimeoutError) as exc:
        raise QueryError(f"BigQuery is unavailable right now: {exc}") from exc

    columns = [field.name for field in result.schema]
    rows = [dict(zip(columns, row.values())) for row in result]
    meta = {
        "job_id": job.job_id,
        "gb_scanned": round((job.total_bytes_processed or 0) / 1e9, 3),
        "cache_hit": bool(job.cache_hit),
        "rows": len(rows),
    }
    event("bq_execute", **meta)
    return columns, rows, meta


def schema() -> dict[str, dict[str, str]]:
    if _CACHE.exists():
        return json.loads(_CACHE.read_text())
    names = ", ".join(f"'{t}'" for t in TABLES)
    _, rows, _ = execute(
        f"SELECT table_name, column_name, data_type "
        f"FROM `{settings.bq_dataset}.INFORMATION_SCHEMA.COLUMNS` "
        f"WHERE table_name IN ({names}) LIMIT {settings.row_limit}"
    )
    out: dict[str, dict[str, str]] = {}
    for row in rows:
        out.setdefault(row["table_name"], {})[row["column_name"]] = row["data_type"]
    _CACHE.write_text(json.dumps(out, indent=2))
    return out
