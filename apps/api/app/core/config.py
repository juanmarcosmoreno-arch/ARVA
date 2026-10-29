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
    # Existing database folders used in place, read-only (JSON list; scripts/start.sh --add-databases mounts them at
    # /databases-external/<n>). Databases there may be registered; ARVA never modifies or deletes them.
    external_db_roots: list[Path] = []

    # Metadata backups made by the backup service (docker-compose.yml) in <storage_root>/backups; shown in the
    # interface (the service reads the same variables).
    backup_interval_hours: int = Field(default=24, ge=1)
    backup_keep: int = Field(default=14, ge=1)

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

    # At API start-up, look in the background for tools that are installed but unusable, databases whose folder is
    # missing and pending migrations, and keep what is found in the error log (app.services.startup).
    startup_checks: bool = True

    # NCBI Datasets v2 API, for building reference genome collections (public metadata and genomes only; ARVA sends
    # no API key, e-mail or other personal data). Tests point it at a local server.
    ncbi_datasets_url: str = "https://api.ncbi.nlm.nih.gov/datasets/v2"

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
    def backups_dir(self) -> Path:
        return self.storage_root / "backups"

    @property
    def databases_dir(self) -> Path:
        return self.db_dir or self.storage_root / "databases"


def create_folders(settings: Settings) -> None:
    """The data folder's subfolders, and the data and database folders themselves only where their parent exists:
    a folder on an external disk that is not connected must not be created on the internal disk instead."""
    for root in (settings.storage_root, settings.databases_dir):
        if not root.is_dir() and root.parent.is_dir():
            root.mkdir(exist_ok=True)
    if settings.storage_root.is_dir():
        for d in (settings.raw_dir, settings.processed_dir, settings.results_dir, settings.reports_dir,
                  settings.logs_dir, settings.backups_dir):
            d.mkdir(exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    try:
        create_folders(settings)
    except OSError:
        # A disk that disappears while ARVA starts: the storage check reports it (app.services.locations).
        pass
    return settings
