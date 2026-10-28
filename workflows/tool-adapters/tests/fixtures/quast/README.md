# QUAST fixtures

Written by QUAST 5.2.0 (PyPI sdist, installed in its own virtual environment with Python 3.12.3, setuptools
80.9.0, joblib 1.5.2 and simplejson 3.20.2) with ARVA's command (`QuastAdapter.argv`, `QuastParams(min_contig=500,
threads=2)`), run offline (no network namespace) with an empty HOME. Reference-based alignment used
`/usr/bin/minimap2` 2.26-r1175 (Ubuntu 24.04 package); QUAST therefore warns that it differs from its bundled 2.24.

Inputs: `make_assemblies.py` applied to the `reference.fasta` of `scripts/make_synthetic_genome.py` (default seed;
`--ont-depth 1 --illumina-depth 1`, which leave the reference unchanged). The two assemblies are SYNTHETIC and
their differences from the reference are known (see the docstring of `make_assemblies.py`), labelled `edited`
and `perfect`.

| Fixture | Run |
|---|---|
| `help_5.2.0.txt` | `quast.py --help` (the installation path in its usage line replaced with `quast.py`) |
| `reference/report.tsv`, `reference/transposed_report.tsv` | both assemblies with `-r reference.fasta` |
| `reference/console.log` | QUAST's console output (stdout and stderr) of that run |
| `reference/contigs_report_edited.stderr` | `contigs_reports/contigs_report_edited.stderr` of that run (minimap2's log) |
| `no_reference/*` | both assemblies without a reference |
| `failures/skipped.console.log` | a 10 bp assembly with `perfect`: QUAST skips it with a warning and exits 0 |
| `failures/none_correct.console.log` | the 10 bp assembly alone: exit status 4 |
| `failures/non_acgtn.console.log` | an assembly containing `X`: exit status 4 |

The TSV files are unchanged. In the logs, the local folders were replaced with `/job/input` (the linked
inputs), `/job/quast` (the output folder) and `/job` (the working directory).

What the reports show, as constructed:

- `edited`: 8 contigs in all (`# contigs (>= 0 bp)`), 6 of at least 500 bp (`# contigs`; the 400 and 499 bp
  pieces are left out, the 500 bp one is kept); 1 misassembly (the relocation, 20,000 bp contig); 1 unaligned
  contig, `Unaligned length` 1,950 (its 2,000 bp minus the 50 N); `# N's per 100 kbp` 14.81 = 50 / 337,500 × 10⁵;
  `# mismatches per 100 kbp` 0.89 = 3 / 335,500 aligned bases × 10⁵; duplication ratio 1.065 (the relocated and
  500 bp contigs repeat sequence of A and B).
- `perfect`: identical to the reference, yet genome fraction 99.683 %: the 299,000 bp alignment of the rotated
  chromosome covers more than 99 % of it (QUAST's fixed threshold in `ca_utils/analyze_contigs.py`), so QUAST kept
  it alone and skipped the 1,000 bp one as insignificant (`contigs_report_perfect.stdout`: "One align captures most
  of this contig").
