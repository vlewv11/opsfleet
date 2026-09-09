from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    llm_provider: str = "google"
    google_api_key: str = ""
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    ollama_base_url: str = "http://localhost:11434"

    reasoning_model: str = "gemini-2.5-pro"
    fast_model: str = "gemini-2.5-flash"
    embedding_model: str = "models/gemini-embedding-001"

    gcp_project: str = ""
    bq_location: str = "US"
    bq_dataset: str = "bigquery-public-data.thelook_ecommerce"
    max_bytes_billed: int = 2_000_000_000
    row_limit: int = 500
    query_timeout_s: int = 120

    max_sql_repairs: int = 3
    max_steps: int = 12
    golden_top_k: int = 3
    pii_salt: str = "change-me-in-production"

    data_dir: Path = ROOT / "data"
    log_dir: Path = ROOT / "logs"


settings = Settings()
