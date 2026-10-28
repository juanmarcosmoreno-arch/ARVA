# fastp fixtures

Written by fastp 0.23.4 (Ubuntu package 0.23.4+dfsg-1) with ARVA's default parameters
(`FastpParams()`, including `--thread 3`) on `examples/synthetic`:

- `SYNTHETIC_illumina_PE.fastp.json`: SYNTHETIC_illumina_R1_001 + R2_001 (paired end).
- `SYNTHETIC_illumina_R1_SE.fastp.json`: SYNTHETIC_illumina_R1_001 alone (single end). fastp detected
  no adapter, so the file has no `adapter_cutting` block, and single-end runs have no `insert_size`.

Two edits, nothing else: the `kmer_count` blocks (unused by ARVA, 1,024 entries per read section) were
removed, and the local folders in `command` were replaced with `/data/` and `/out/`.
