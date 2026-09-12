import argparse
import base64
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from google.api_core.exceptions import Forbidden
from google.cloud import bigquery
from google.oauth2 import service_account

from src.utils.config import ROOT, settings

TABLES = ("users", "products", "orders", "order_items")
WAREHOUSE = ROOT / "data" / "warehouse"


def credentials(explicit: str | None):
    if explicit:
        return service_account.Credentials.from_service_account_file(explicit)
    if settings.google_credentials_b64:
        return service_account.Credentials.from_service_account_info(
            json.loads(base64.b64decode(settings.google_credentials_b64))
        )
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Load the generated warehouse into BigQuery")
    parser.add_argument("--credentials", help="service-account JSON with bigquery.dataEditor")
    parser.add_argument("--dataset", default="retail_demo")
    parser.add_argument("--project", default=settings.gcp_project)
    parser.add_argument("--location", default=settings.bq_location)
    args = parser.parse_args()

    if not args.project:
        raise SystemExit("Set GCP_PROJECT in .env or pass --project")

    client = bigquery.Client(project=args.project, credentials=credentials(args.credentials))
    dataset = bigquery.Dataset(f"{args.project}.{args.dataset}")
    dataset.location = args.location
    try:
        client.create_dataset(dataset, exists_ok=True)
    except Forbidden as exc:
        raise SystemExit(
            f"{exc.message}\n\nThe credential in .env is read-only by design. Pass a key holding "
            "roles/bigquery.dataEditor via --credentials for this one-time load."
        ) from exc
    print(f"dataset {args.project}.{args.dataset} ready in {args.location}")

    for table in TABLES:
        schema = [
            bigquery.SchemaField(f["name"], f["type"], mode=f["mode"])
            for f in json.loads((WAREHOUSE / f"{table}.schema.json").read_text())
        ]
        job_config = bigquery.LoadJobConfig(
            schema=schema,
            source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
            write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        )
        with open(WAREHOUSE / f"{table}.ndjson", "rb") as fh:
            client.load_table_from_file(
                fh, f"{args.project}.{args.dataset}.{table}", job_config=job_config
            ).result()
        print(f"  loaded {table:12} {client.get_table(f'{args.project}.{args.dataset}.{table}').num_rows:>8,} rows")

    target = f"{args.project}.{args.dataset}"
    env = ROOT / ".env"
    if env.exists():
        text = env.read_text()
        env.write_text(
            re.sub(r"^BQ_DATASET=.*$", f"BQ_DATASET={target}", text, flags=re.M)
            if re.search(r"^BQ_DATASET=", text, flags=re.M)
            else text.rstrip() + f"\nBQ_DATASET={target}\n"
        )
        print(f"\n.env updated: BQ_DATASET={target}")
    (ROOT / "data" / "schema.json").unlink(missing_ok=True)


if __name__ == "__main__":
    main()
