import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    openrouter_api_key: str = ""
    google_api_key: str = ""
    embedding_model: str = "models/gemini-embedding-001"

    gcp_project: str = ""
    google_application_credentials: str = ""
    google_credentials_b64: str = ""
    bq_location: str = "US"
    bq_dataset: str = "bigquery-public-data.thelook_ecommerce"
    max_bytes_billed: int = 2_000_000_000
    row_limit: int = 500
    query_timeout_s: int = 120

    app_user: str = "alex"
    app_password: str = ""
    session_secret: str = ""

    max_sql_repairs: int = 3
    max_steps: int = 12
    golden_top_k: int = 3
    pii_salt: str = "change-me-in-production"

    data_dir: Path = ROOT / "data"
    log_dir: Path = ROOT / "logs"


settings = Settings()

if settings.google_application_credentials:
    _key = Path(settings.google_application_credentials).expanduser()
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(_key if _key.is_absolute() else ROOT / _key)
