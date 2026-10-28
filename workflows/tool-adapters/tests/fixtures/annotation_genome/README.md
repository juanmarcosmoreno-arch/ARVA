# SYNTHETIC annotation test genome — not biological data

`genome.fna` (18,960 bp, two sequences) is the input of the Bakta and Prokka fixtures in `../bakta` and
`../prokka`. Nothing an annotator reports for it describes an organism.

It was written by `scripts/make_synthetic_annotation_genome.py` (seed 20261028):

```bash
python3 scripts/make_synthetic_annotation_genome.py out --chromosome-genes 12 --plasmid-genes 2 \
    --insert rna_model_samples.fasta --back-translate swissprot_proteins.fasta
awk '/^>/{print $1; next} {print}' out/genome.fasta > genome.fna   # FASTA descriptions removed, as ARVA stages it
```

`planted_features.tsv` lists what was planted (1-based, inclusive):

- 14 random ORFs (ATG, random sense codons, a stop; a Shine-Dalgarno-like motif upstream), on either strand;
- `rna_model_samples.fasta`: five sequences **sampled** from covariance models with Infernal 1.1.5's `cmemit`
  (U written as T), not copied from any genome:
  - `cmemit -N 2 --seed 11 /usr/share/trnascan-se/models/TRNAinf-bact.cm` (tRNAscan-SE 2.0.12's bacterial tRNA model),
  - `cmemit -N 1 --seed 12` on `5S_rRNA`, `--seed 13` on `SSU_rRNA_bacteria` (both `cmfetch`ed from the Bakta light
    database 6.0's `rRNA.i1m`), `--seed 14` on `RNaseP_bact_a` (from its `ncRNA-genes.i1m`);
- `swissprot_proteins.fasta`: three protein sequences (UniProtKB/Swiss-Prot P04395, P05100, Q59087) taken from
  `/usr/share/prokka/db/kingdom/Bacteria/sprot` of Ubuntu's prokka 1.14.6+dfsg-6 (built from UniProt release
  2023_04, CC BY 4.0, © UniProt Consortium), each encoded as an ORF with a random synonymous codon per residue, so
  Prokka's similarity search has something to find;
- a CRISPR-like array (a random 30 bp repeat seven times with random 35 bp spacers) and a run of 100 N.

So the tRNAs, rRNAs, the ncRNA and the three named proteins that the tools report exist because they were
constructed in; the other ORFs are random and every tool calls them hypothetical.
