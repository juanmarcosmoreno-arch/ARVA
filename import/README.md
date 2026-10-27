# ARVA import folder

Put sequencing files here (or in sub-folders, e.g. one folder per run) to import them from the
ARVA web interface without uploading them through the browser. This is the recommended way to add
large runs (many gigabytes).

With Docker Compose this folder is mounted **read-only** at `/import` in the `api` and `worker`
containers, and `ARVA_IMPORT_ROOTS` is set to `["/import"]`. To use another host folder instead, set
`ARVA_IMPORT_DIR=/absolute/path` in `.env` and run `docker compose up -d` again.

In ARVA: **Import Data → Import from a server folder**, choose the project and sample, tick the files
and start the import. ARVA then:

- copies each file into its data directory (`ARVA_STORAGE_ROOT`), computing its SHA-256 while
  copying, and stores the copy read-only;
- validates the start of the file, detects R1/R2 mates and rejects files whose identical content is
  already registered in the same sample;
- records the original location in the file description ("Imported from server: …") and logs every
  step in the import job (Analysis history of the sample).

The files in this folder are only read: ARVA never modifies, moves or deletes them. Once imported,
you may remove them from here yourself.

Notes:

- The containers run as an unprivileged user, so files must be readable by others
  (`chmod -R a+rX import/`).
- Hidden files and folders (names starting with `.`) are not shown, and symbolic links that point
  outside this folder are ignored.
- Only the folder itself is tracked by git (everything placed here is ignored), and it is excluded
  from Docker build contexts.
