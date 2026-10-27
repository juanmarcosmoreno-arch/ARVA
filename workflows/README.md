# Workflows

- `tool-adapters/` — the `arva_tools` package: one adapter per external tool (SeqKit, FastQC, fastp,
  Filtlong) with executable discovery, version detection and validation, argument-vector commands
  (never shell strings), safe execution and output parsers. `environment.yml` installs the tools with
  conda/mamba. See `docs/developer-guide.md` → "Integrating an external tool".
- `nextflow/` — Nextflow DSL2 pipelines for multi-step analyses (assembly, annotation, batch runs);
  planned for Phase 3.
