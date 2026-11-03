# Medaka 2.1.1 fixtures

Recorded with ARVA's Bioconda environment of Medaka 2.1.1 (`docker/conda-locks/medaka/linux-64.lock`, build
`py312ha65e1bd_1`), HOME set to an empty folder:

* `version_2.1.1.txt`: `medaka --version`.
* `medaka_consensus_help_2.1.1.txt`: `medaka_consensus -h` (with the environment's `bin/` first on PATH; the script
  runs `medaka tools list_models` to print the model choices).
* `list_models_2.1.1.txt`: `medaka tools list_models`.
* `run_synthetic.stdout.log`, `run_synthetic.stderr.log`: `medaka_consensus -i ont.fastq.gz -d draft.fasta -o out
  -m r1041_e82_400bps_sup_v5.2.0 -t 2` on the synthetic genome of `scripts/make_synthetic_genome.py` (100 kb
  chromosome, 8 kb plasmid, `--ont-depth 30`) and the draft of `scripts/make_polishing_draft.py`. The consensus had
  no difference from the reference (MUMmer dnadiff: 0 SNPs, 0 indels); the gaps BED was empty.
* `run_unrelated.stdout.log`, `run_unrelated.stderr.log`, `gaps_unrelated.bed`: the same reads against a random
  20 kb contig `x` that no read aligns to: medaka exits 0, logs "Copying contig 'x' verbatim from input." and lists
  the whole contig in `consensus.fasta.gaps_in_draft_coords.bed`.

Folder names in the logs were replaced with `/work`, `/work/input` and `/opt/arva-tools/conda/medaka`.
