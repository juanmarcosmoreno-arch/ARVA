# spaTyper fixtures — real spaTyper 0.3.3 output

Written by spaTyper 0.3.3 (Bioconda `spatyper-0.3.3-pyhdfd78af_3`; ARVA's environment from
`docker/conda-locks/spatyper/linux-64.lock`) on 2026-11-02 with the command ARVA builds:

```bash
spaTyper --repeat_file <ridom>/sparepeats.fasta --repeat_order_file <ridom>/spatypes.txt --fasta contigs.fasta \
  --output spatyper.tsv
```

The Ridom SpaServer files were downloaded for these runs as a user would (non-commercial use under the SpaServer's
policy, https://spa.ridom.de/policy.shtml) from the "Download repeat sequences (FASTA)" and "Download spa-types (CSV)"
links of https://spa.ridom.de/repeats.shtml and https://spa.ridom.de/spatypes.shtml on 2026-11-02:
`sparepeats.fasta` (865 repeats, CRLF line ends, sha256 `60e52817b1fde3a60905ed8eb149c0a8de46dfc3243a2b22f05912b748299365`)
and `spatypes.txt` (22,861 types, sha256 `c2365229dd27ebf6b59755a36f22d7675bd5e1b352b5bd9f55aadc2965a65e94`). They are
**not** kept in ARVA: only spaTyper's output rows (contig, repeat succession, spa type) are.

| Fixture | Input | spaTyper's call | Published |
| --- | --- | --- | --- |
| `n315.spatyper.tsv` | *S. aureus* N315 (as in `../sccmec/README.md`) | NC_002745.2: 26-23-17-34-17-20-17-12-17-16, t002 | ST5-MRSA-II strains are commonly t002; no publication stating N315's spa type was found for this check, so this row is a confirmation by the SpaServer's own table only |
| `usa300.spatyper.tsv` | *S. aureus* USA300_FPR3757 (as in `../sccmec/README.md`) | NC_007793.1: 11-19-12-21-17-34-24-34-22-25, t008 | t008 is the spa type of the USA300 clone (e.g. Tenover F.C., Goering R.V. 2009 J Antimicrob Chemother 64:441-446); not stated in Diep et al. 2006 |
| `synthetic.spatyper.tsv` | ARVA's SYNTHETIC genome | header only: no spa repeat | none by construction |

`constructed/` is **CONSTRUCTED** test data written by `make_constructed.py`: three made-up 24-bp repeats (r91, r92,
r93) in Ridom's file formats, one made-up type (t9001 = 91-92-93) and one-contig genomes with a known succession, a
new succession (93-91), a gap (91-xx-92), two contigs, and the typed contig in lower case (spaTyper finds nothing:
it does not upper-case the query, so ARVA stages contigs in upper case). None of it is Ridom data. `help_0.3.3.txt`
is `spaTyper --help`.
