"""Central application configuration, loaded from environment variables."""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="ARVA_", extra="ignore")

    app_name: str = "ARVA"
    environment: str = "development"
    api_v1_prefix: str = "/api/v1"

    database_url: str = "postgresql+psycopg://postgres:arva_dev_password@localhost:5432/arva"

    redis_url: str = "redis://localhost:6379/0"
    task_queue_name: str = "arva"
    # When false, jobs execute synchronously at enqueue time (tests only).
    task_queue_async: bool = True

    # Root directory for all managed scientific data (raw, processed, results, logs, ...).
    storage_root: Path = Path("./data")

    # CORS
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:4173"]

    # Upload limits
    max_upload_size_bytes: int = 20 * 1024 * 1024 * 1024  # 20 GB per file

    # External tools
    tool_threads: int = 4
    tool_timeout_seconds: int = 12 * 3600

    @property
    def raw_dir(self) -> Path:
        return self.storage_root / "raw"

    @property
    def processed_dir(self) -> Path:
        return self.storage_root / "processed"

    @property
    def results_dir(self) -> Path:
        return self.storage_root / "results"

    @property
    def reports_dir(self) -> Path:
        return self.storage_root / "reports"

    @property
    def logs_dir(self) -> Path:
        return self.storage_root / "logs"


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    for d in (
        settings.raw_dir,
        settings.processed_dir,
        settings.results_dir,
        settings.reports_dir,
        settings.logs_dir,
    ):
        d.mkdir(parents=True, exist_ok=True)
    return settings
