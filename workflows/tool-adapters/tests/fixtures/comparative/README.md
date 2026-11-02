# Comparative genomics fixtures — real skani, FastANI, minimap2, NUCmer and dnadiff output

Written on 2026-11-02 by skani 0.4.0 and FastANI 1.34 (ARVA's Bioconda locks), minimap2 2.26-r1175 (Ubuntu
2.26+dfsg-1build1) and MUMmer 3.23 (Ubuntu 3.23+dfsg-8: NUCmer 3.1, DNAdiff 1.3), with the options ARVA passes, from
a folder holding `in/` (local folders were removed from the paths):

```bash
ls in/*.fna > list.txt   # in/mu50.fna in/n315.fna in/sepi.fna in/usa300.fna
skani triangle -l list.txt -o skani_triangle_staph.tsv -t 2 -c 125 -m 1000 -s 80 --min-af 15 -E
fastANI --ql list.txt --rl list.txt -o fastani_all_staph.tsv -t 2 -k 16 --fragLen 3000 --minFraction 0.2 --maxRatioDiff 10.0
minimap2 -x asm5 -c -t 2 -o minimap2_asm5_n315_usa300.paf in/n315.fna in/usa300.fna
minimap2 -x asm20 -c -t 2 -o minimap2_asm20_n315_sepi.paf in/n315.fna in/sepi.fna
nucmer --mumreference -c 65 -l 20 -b 200 -g 90 -p n315_sepi ref.fna qry.fna      # ref = N315, qry = S. epidermidis
show-coords -rclTH n315_sepi.delta > nucmer_n315_sepi.coords
dnadiff -p n315_mu50 ref.fna qry.fna                                              # ref = N315, qry = Mu50
```

`*_help_*.txt` are the tools' usage texts. The dnadiff report's first line (the input paths) was shortened.

## Genomes (NCBI RefSeq, NCBI Datasets v2 API; kept outside the repository)

`POST https://api.ncbi.nlm.nih.gov/datasets/v2/genome/download` with the four accessions and
`"include_annotation_type": ["GENOME_FASTA"]`; package zip 3,270,233 bytes (sha256
`a4ce073bc5db164c05077915084862ac5677755b4879b3116b57c6c0be8aa15c`), every file matched its `md5sum.txt`. The FASTA
files are cached in `/root/.arva-testdata/genomes/<accession>.fna` (with `SHA256SUMS` and the package metadata) for
the real-tool tests (`ARVA_TEST_GENOMES`, default that folder); they are never committed.

| Accession | Organism (NCBI) | Sequences | FASTA sha256 |
| --- | --- | --- | --- |
| GCF_000009645.1 | *S. aureus* subsp. *aureus* N315 | chromosome + pN315 | `d7b93eeed77ce08d041f597d28fe3d7310fead42f9f790b6325539fb70c458f9` |
| GCF_000009665.1 | *S. aureus* subsp. *aureus* Mu50 | chromosome + VRSAp | `d2406423371e0a6f9f7334762d06e92c17ee5eb779257000e2c6ea989a1201ea` |
| GCF_000013465.1 | *S. aureus* subsp. *aureus* USA300_FPR3757 | chromosome + pUSA01-03 | `d5fec7a60a33287ea755c98754d9ca477341eede7aa9ab514cc0088a7458dd35` |
| GCF_000007645.1 | *S. epidermidis* ATCC 12228 | chromosome + 6 plasmids | `48377d375406d7e288a365c7d889a6cf2c9dbdc51048572ac8f8721aa923ed40` |

## What the outputs show

* skani triangle: the three *S. aureus* pairs only (Mu50-N315 99.90 %, N315-USA300 98.97 %, Mu50-USA300 98.86 %);
  every pair with *S. epidermidis* is screened out (-s 80), so it has no row.
* FastANI: all 16 ordered pairs, self pairs at 100 %; *S. epidermidis* against *S. aureus* 79.5-79.9 %, with about a
  third of the fragments mapped. A against B and B against A differ slightly (99.9032 / 99.9143 for Mu50 / N315).
* minimap2 -c: 175 PAF rows for N315-USA300 (asm5); 120 for N315-*S. epidermidis* (asm20).
* nucmer N315-*S. epidermidis*: 268 alignments, 82-86 % identity.
* dnadiff N315-Mu50: 36 one-to-one alignments, 99.93 % average identity; 1,162 SNPs; Relocations 5 / 8, Inversions
  4 / 2, Translocations 0 / 0, Insertions 29 (59,724 bases) in N315 and 40 (123,208 bases) in Mu50 — the counts ARVA
  recomputes from `.rdiff` / `.qdiff` with dnadiff's own rules.
