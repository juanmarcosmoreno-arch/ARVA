# Reference databases

Reference databases are installed and recorded by ARVA's **Database Manager** (Tools & Databases page;
API under `/api/v1/databases`), not stored in this repository. They live in `ARVA_DB_DIR` (default
`<ARVA_STORAGE_ROOT>/databases`; Docker Compose: the `arva-databases` volume at `/databases`).

The catalogue of supported databases, with the facts checked against their official sources (version,
size, checksum, licence, source URL, release date), is `apps/api/app/services/database_catalogue.py`.
No database is downloaded without first showing its size, licence, source and the space it needs, and an
explicit confirmation. See [docs/installation.md](../docs/installation.md#reference-databases-database-manager)
and [docs/scientific-methods.md](../docs/scientific-methods.md#reference-databases-phase-4).
