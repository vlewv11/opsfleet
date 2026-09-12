import logging
from typing import Optional, List, Dict, Any
import pandas as pd
from google.cloud import bigquery


class BigQueryRunner:
    """A lean BigQuery client for executing SQL queries and returning DataFrame results."""

    def __init__(self, project_id: Optional[str] = None, dataset_id: Optional[str] = "bigquery-public-data.thelook_ecommerce", credentials: Optional[Any] = None) -> None:
        """Initialize BigQuery client.

        Args:
            project_id: Google Cloud project ID. If None, uses default credentials.
            dataset_id: BigQuery dataset ID. If None, uses default dataset.
            credentials: Explicit credentials object. If None, Application Default
                Credentials are discovered from the environment.
        """
        logging.info("Initializing BigQuery client")
        try:
            self.client = bigquery.Client(project=project_id, credentials=credentials)
            self.dataset_id = dataset_id
            logging.info(f"BigQuery client initialized for dataset: {self.dataset_id}")
        except Exception as e:
            logging.error(f"Failed to initialize BigQuery client: {str(e)}")
            raise

    def execute_query(self, sql_query: str) -> pd.DataFrame:
        """Execute a SQL query and return results as a DataFrame.

        Args:
            sql_query: The SQL query to execute.

        Returns:
            DataFrame containing the query results.

        Raises:
            Exception: If query execution fails.
        """
        try:
            logging.info(f"Executing BigQuery query")
            query_job = self.client.query(sql_query)
            df = query_job.result().to_dataframe()
            logging.info(f"Query completed successfully, returned {len(df)} rows")
            return df
        except Exception as e:
            logging.error(f"BigQuery execution failed: {str(e)}")
            raise

    def execute_query_rows(
        self,
        sql_query: str,
        job_config: Optional[bigquery.QueryJobConfig] = None,
        timeout: Optional[float] = None,
    ) -> tuple[List[str], List[Dict[str, Any]], bigquery.QueryJob]:
        """Execute a SQL query and return column names, row dicts and the completed job.

        Materialises rows straight from the result iterator rather than via a DataFrame,
        which avoids a full copy of the result set and preserves BigQuery's native types.

        Args:
            sql_query: The SQL query to execute.
            job_config: Job configuration, carrying the server-side byte cap.
            timeout: Seconds to wait for completion. The job is cancelled on expiry so a
                hung query stops accruing cost instead of running on unobserved.

        Returns:
            Tuple of the column names in schema order, the rows as dictionaries, and the
            QueryJob, whose metadata carries job_id, total_bytes_processed and cache_hit.

        Raises:
            Exception: If query execution fails.
        """
        try:
            logging.info("Executing BigQuery query")
            query_job = self.client.query(sql_query, job_config=job_config)
            try:
                result = query_job.result(timeout=timeout)
            except TimeoutError:
                query_job.cancel()
                raise
            columns = [field.name for field in result.schema]
            rows = [dict(row) for row in result]
            logging.info(f"Query completed successfully, returned {len(rows)} rows")
            return columns, rows, query_job
        except Exception as e:
            logging.error(f"BigQuery execution failed: {str(e)}")
            raise

    def get_table_schema(self, table_name: str) -> List[Dict[str, Any]]:
        """Get schema information for a specific table.

        Args:
            table_name: Name of the table (orders, order_items, products, users).

        Returns:
            List of dictionaries containing column information.
        """
        try:
            table_ref = f"{self.dataset_id}.{table_name}"
            table = self.client.get_table(table_ref)
            schema_info = []
            for field in table.schema:
                schema_info.append({
                    "name": field.name,
                    "type": field.field_type,
                    "mode": field.mode,
                    "description": field.description or ""
                })
            logging.info(f"Retrieved schema for table {table_name}")
            return schema_info
        except Exception as e:
            logging.error(f"Failed to get schema for table {table_name}: {str(e)}")
            raise
