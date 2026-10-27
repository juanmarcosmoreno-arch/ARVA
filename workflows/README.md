# Workflows (Phase 3+)

- `nextflow/` — Nextflow DSL2 pipelines for multi-step analyses (assembly, annotation, batch runs).
- `tool-adapters/` — one adapter per external tool: version detection, typed inputs/outputs,
  parameters validated against the tool's official documentation, and commands built as argument
  vectors (never shell strings). Each adapter execution is recorded as an `AnalysisJob`.

Empty in v0.1.0: the only analysis so far (`arva-core.seqstats`) is implemented in
`scientific-core/`. See `docs/developer-guide.md` for the integration checklist.
