#!/bin/bash
# Rebuilds the per-isolate table (Supplementary Table S1 source) and Figs. 1, 3 and 4 of the manuscript from the
# result files in ../results and from PubMLST. Needs Python 3 and Node.js with Playwright (Chromium).
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p out
python3 -I per_isolate_table.py .. out
python3 -I fig_benchmark.py out/per_isolate.tsv out/fig3_benchmark.html
python3 -I fetch_alleles.py out
python3 -I fig_alleles.py out && mv out/alleles.html out/fig4_alleles.html
python3 -I fig_architecture.py out/fig1_architecture.html
for f in fig1_architecture fig3_benchmark fig4_alleles; do node render.cjs "$PWD/out/$f.html" "$PWD/out/$f" 3; done
