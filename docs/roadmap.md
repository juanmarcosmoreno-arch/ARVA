# Roadmap and current status

## Phase 1 — Foundation ✅ (v0.1.0)

Monorepo; FastAPI + PostgreSQL + Alembic; Redis/RQ worker; React interface with ARVA identity
(light/dark, EN/ES); projects and samples with metadata; FASTQ/FASTA(.gz) import with checksums,
duplicate detection and validation; read statistics with six interactive figures; analysis history
and provenance; HTML/CSV/JSON reports; ARVA Guide; Analysis Timeline; Docker Compose deployment;
unit, API and end-to-end tests.

### Known limitations of v0.1.0

- Read statistics are computed by ARVA's own Python engine (≈ 7 Mbp/s short reads, ≈ 25 Mbp/s long
  reads on one core). Very large runs take minutes; SeqKit/NanoPlot integration is planned.
- Uploads go through the browser as multipart requests (the server spools them before storing);
  importing directly from a server-side folder is not yet available.
- No read-ID uniqueness check, adapter detection or duplication analysis.
- PDF export: print the HTML report from the browser; native PDF is planned.
- No authentication: intended for single-user local use (bound to localhost).
- CSV/Excel metadata import, sample tags/cohorts, project duplication/import/export and change
  history are not implemented yet.
- Deleting a project/sample removes database records but intentionally leaves raw files on disk.
- Demonstration mode (spec §34) is not included yet; the data model already has an `is_demo` flag and
  the UI/report label DEMO projects. Synthetic example reads are provided in `examples/synthetic`.
- Only FASTQ/FASTA(.gz) are accepted; other formats are listed in the Import screen as planned.

## Phase 2 — Raw data and QC (next)

Recommended next step. Integrate real tools through the adapter pattern:

1. Tool adapter framework (`workflows/tool-adapters/`): version detection, argument-vector commands,
   container/Bioconda resolution with architecture checks.
2. **SeqKit** stats and **NanoPlot** / **FastQC** reports attached to jobs; **MultiQC** per project.
3. Filtering: **fastp** (Illumina) and **Filtlong** (long reads) with explicit, user-visible
   parameters; before/after comparison charts; derived FASTQ stored as new files linked to their
   parent and the job.
4. Folder import from the server filesystem, CSV/Excel metadata import.
5. POD5 detection and optional **Dorado** basecalling (CPU / Apple Metal where supported).

## Later phases

| Phase | Scope |
|---|---|
| 3 | Assembly (Flye first; then SPAdes/Unicycler/Raven), QUAST, contig plots, GFA view, polishing (Medaka/Polypolish) |
| 4 | Annotation (Bakta; Prokka), Genome Explorer (linear + circular), exports (GFF3, GenBank, FASTA) |
| 5 | MLST, AMRFinderPlus, virulence (VFDB), BLAST, species identification (Mash/FastANI/Kraken2/GTDB-Tk) |
| 6 | Comparative genomics: ANI, synteny, dot plots, Genome Region Explorer |
| 7 | Pangenome (Panaroo), alignments (MAFFT), phylogeny (IQ-TREE), Tree Explorer |
| 8 | Workflow Builder (Nextflow DSL2), batch processing, mobilome, variants, ARVA Discover, full reports, optional ARVA Assist, multi-user |
