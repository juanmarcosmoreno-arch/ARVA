# Workflows

- `tool-adapters/` — the `arva_tools` package: one adapter per external tool (SeqKit, FastQC, fastp,
  Filtlong, MultiQC, NanoPlot, Flye, QUAST) with executable discovery, version detection and validation,
  argument-vector commands (never shell strings), safe execution and output parsers.
  `environment.yml` installs SeqKit, FastQC, fastp and Filtlong with conda/mamba; MultiQC 1.35,
  NanoPlot 1.48.0 and QUAST 5.2.0 are installed from PyPI, each in its own virtual environment, and found
  through `ARVA_TOOL_MULTIQC` / `ARVA_TOOL_NANOPLOT` / `ARVA_TOOL_QUAST` (`docs/installation.md`). See
  `docs/developer-guide.md` → "Integrating an external tool".
- `nextflow/` — Nextflow DSL2 pipelines for multi-step analyses (assembly, annotation, batch runs);
  planned for Phase 3.
