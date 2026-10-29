"""Central application configuration, loaded from environment variables."""
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Empty variables count as unset: docker-compose.yml passes optional ones as ${ARVA_...:-}.
    model_config = SettingsConfigDict(env_file=".env", env_prefix="ARVA_", extra="ignore", env_ignore_empty=True)

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
    # Reference databases (Bakta, ...) installed by the Database Manager; unset: <storage_root>/databases.
    db_dir: Path | None = None

    # CORS
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:4173"]

    # Upload limits
    max_upload_size_bytes: int = 20 * 1024 * 1024 * 1024  # 20 GB per file
    # Uploads and imports must leave at least this much free space on the storage filesystem.
    min_free_bytes: int = Field(default=1024 * 1024 * 1024, ge=0)

    # Server folders that may be browsed and imported from (JSON list). Empty disables the feature.
    import_roots: list[Path] = []

    # Sample metadata tables (CSV or .xlsx) imported into a project.
    metadata_max_bytes: int = Field(default=10 * 1024 * 1024, gt=0)
    metadata_max_rows: int = Field(default=10_000, gt=0)
    metadata_max_columns: int = Field(default=256, gt=0)
    metadata_max_cell_chars: int = Field(default=10_000, gt=0)

    # External tools. Threads and memory come from the performance profile (app.services.performance); these two,
    # when set, are administrator caps on it: no tool run gets more threads, or more memory (SPAdes' -m, Pilon's
    # -Xmx), whatever the profile or a request says.
    tool_threads: int | None = Field(default=None, ge=1)
    tool_memory_gb: int | None = Field(default=None, ge=1)
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

    @property
    def databases_dir(self) -> Path:
        return self.db_dir or self.storage_root / "databases"


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    for d in (
        settings.raw_dir,
        settings.processed_dir,
        settings.results_dir,
        settings.reports_dir,
        settings.logs_dir,
        settings.databases_dir,
    ):
        d.mkdir(parents=True, exist_ok=True)
    return settings
