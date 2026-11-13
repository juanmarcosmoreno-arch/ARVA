# Figures and tables of the benchmark

Scripts that rebuild, from the result files in `../results/`, the per-isolate table and the figures used to report
this benchmark:

- `per_isolate_table.py`: one row per isolate (reads, depth, contigs, lengths, sequence types, alleles, *spa*, *agr*,
  phenotypes, resistance genes, time per step, memory) in `out/per_isolate.tsv`.
- `fig_benchmark.py`: agreement of each isolate with the study's reference results, and run time per step.
- `fetch_alleles.py` and `fig_alleles.py`: the one-base differences in adenine runs between the Sanger alleles and
  the alleles found in the assemblies (*arcC* 3/90, *arcC* 1/484, *aroE* 35/1216), from the PubMLST *S. aureus*
  database.
- `fig_architecture.py`: diagram of ARVA's architecture (drawn as code).
- `render.cjs`: renders each HTML/SVG figure to PNG and PDF with Playwright.

Run `./make_figures.sh`; the outputs go to `out/`. The scripts were written with Claude Code (Anthropic).
