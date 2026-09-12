import base64
import json
from functools import lru_cache

from google.api_core import exceptions, retry
from google.cloud import bigquery
from google.oauth2 import service_account

from src.tools.bq_runner import BigQueryRunner
from src.utils.config import settings
from src.utils.logger import event, trace_id

TABLES = ("orders", "order_items", "products", "users")
_CACHE = settings.data_dir / "schema.json"
_RETRY = retry.Retry(
    predicate=retry.if_exception_type(
        exceptions.ServerError, exceptions.TooManyRequests, ConnectionError
    ),
    initial=1.0,
    maximum=8.0,
    timeout=45.0,
)


class QueryError(RuntimeError):
    pass


@lru_cache(maxsize=1)
def client() -> BigQueryRunner:
    credentials, project = None, settings.gcp_project or None
    if settings.google_credentials_b64:
        info = json.loads(base64.b64decode(settings.google_credentials_b64))
        credentials = service_account.Credentials.from_service_account_info(info)
        project = project or info["project_id"]
    return BigQueryRunner(
        project_id=project, dataset_id=settings.bq_dataset, credentials=credentials
    )


def dry_run(sql: str) -> int:
    try:
        job = client().client.query(
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
        columns, rows, job = _RETRY(client().execute_query_rows)(
            sql,
            job_config=bigquery.QueryJobConfig(
                maximum_bytes_billed=settings.max_bytes_billed,
                use_query_cache=True,
                labels={"trace": trace_id.get().lower()[:63]},
            ),
            timeout=settings.query_timeout_s,
        )
    except TimeoutError as exc:
        raise QueryError(
            f"The query was still running after {settings.query_timeout_s}s and was cancelled. "
            "Narrow the date range or aggregate further."
        ) from exc
    except exceptions.BadRequest as exc:
        raise QueryError(exc.message.split("\n\n")[0]) from exc
    except exceptions.Forbidden as exc:
        raise QueryError(f"BigQuery denied the request: {exc.message}") from exc
    except exceptions.GoogleAPIError as exc:
        raise QueryError(f"BigQuery is unavailable right now: {exc}") from exc

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
    runner = client()
    out = {
        table: {field["name"]: field["type"] for field in runner.get_table_schema(table)}
        for table in TABLES
    }
    _CACHE.write_text(json.dumps(out, indent=2))
    return out
