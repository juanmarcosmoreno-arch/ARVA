# fastp fixtures

Written by fastp 0.23.4 (Ubuntu package 0.23.4+dfsg-1) with ARVA's command (`FastpAdapter.argv`,
including `--thread 3`) on `examples/synthetic`:

- `SYNTHETIC_illumina_PE.fastp.json`: SYNTHETIC_illumina_R1_001 + R2_001 (paired end), `FastpParams()`.
- `SYNTHETIC_illumina_R1_SE.fastp.json`: SYNTHETIC_illumina_R1_001 alone (single end), `FastpParams()`.
  fastp detected no adapter, so the file has no `adapter_cutting` block, and single-end runs have no
  `insert_size`.
- `SYNTHETIC_illumina_R1_SE_length_limit_140.fastp.json`: R1 alone with `FastpParams(length_limit=140)`.
  Every read is 150 bp, so fastp discarded all of them (1,844 too long, 156 low quality), wrote a
  0-byte `.fq.gz` and still exited with status 0.

Two edits, nothing else: the `kmer_count` blocks (unused by ARVA, 1,024 entries per read section) were
removed, and the local folders in `command` were replaced with `/data/` and `/out/`. The
`length_limit_140` file was re-serialised by Python's `json` module while doing so (indentation only).
