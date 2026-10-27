import { describe, expect, it } from "vitest";
import { groupFilesBySample, inferSampleName, isSequenceFile } from "@/lib/sampleNames";

const groups = (names: string[]) => groupFilesBySample(names).map((g) => [g.sampleName, g.files.map((f) => [f.name, f.mate])]);

describe("inferSampleName", () => {
  it.each([
    // bcl2fastq (lane-split) and BCL Convert (--no-lane-splitting) names
    ["SA-001_S1_L001_R1_001.fastq.gz", "SA-001"],
    ["SA-001_S12_L004_R2_001.fastq.gz", "SA-001"],
    ["SA-001_S1_R1_001.fastq.gz", "SA-001"],
    ["SA-001_L001_R2_001.fq.gz", "SA-001"],
    ["SA-001_R1_001.fastq", "SA-001"],
    ["SA-001_R2.fastq.gz", "SA-001"],
    ["sa-001_s1_l001_r1_001.FASTQ.GZ", "sa-001"],
    ["sample.R1.fq", "sample"],
    ["sample-R2.fastq", "sample"],
    // the sample name itself may contain mate-like text before the real suffix
    ["Run_R1_S3_L001_R1_001.fastq.gz", "Run_R1"],
    // names with dots
    ["E.coli.K-12_R1_001.fastq.gz", "E.coli.K-12"],
    ["isolate.v2.fasta", "isolate.v2"],
    ["S.aureus_ST398.contigs.fna.gz", "S.aureus_ST398.contigs"],
    // ONT and assemblies
    ["barcode01.fastq.gz", "barcode01"],
    ["FAX12345_pass_barcode05_a1b2c3d4_0.fastq.gz", "FAX12345_pass_barcode05_a1b2c3d4_0"],
    ["run7_barcode02.pod5", "run7_barcode02"],
    ["assembly.fa", "assembly"],
    ["genome.fas", "genome"],
    // unicode
    ["muestra_ñandú_R1_001.fastq.gz", "muestra_ñandú"],
    ["Ölprobe-α_S2_R2_001.fastq.gz", "Ölprobe-α"],
    // directories are ignored, the suffix alone never becomes an empty name
    ["run1/fastq/SA-002_S2_L001_R1_001.fastq.gz", "SA-002"],
    ["_R1.fastq", "_R1"],
    ["R1.fastq.gz", "R1"],
  ])("%s → %s", (name, expected) => {
    expect(inferSampleName(name, [name])).toBe(expected);
  });

  it("strips a bare _1/_2 only when the partner file exists (SRA style)", () => {
    expect(inferSampleName("SRR1234567_1.fastq.gz", ["SRR1234567_1.fastq.gz", "SRR1234567_2.fastq.gz"])).toBe("SRR1234567");
    expect(inferSampleName("SRR1234567_2.fastq.gz", ["SRR1234567_1.fastq.gz", "SRR1234567_2.fastq.gz"])).toBe("SRR1234567");
    expect(inferSampleName("SRR1234567_1.fastq.gz", ["SRR1234567_1.fastq.gz"])).toBe("SRR1234567_1");
  });

  it("keeps a sample named isolate_2 when it is alone", () => {
    expect(inferSampleName("isolate_2.fastq.gz", ["isolate_2.fastq.gz"])).toBe("isolate_2");
    expect(inferSampleName("isolate_2.fastq.gz", ["isolate_2.fastq.gz", "isolate_3.fastq.gz"])).toBe("isolate_2");
  });

  it("accepts the partner with another separator only if it is the same one", () => {
    expect(inferSampleName("x.1.fq", ["x.1.fq", "x.2.fq"])).toBe("x");
    expect(inferSampleName("x.1.fq", ["x.1.fq", "x_2.fq"])).toBe("x.1");
  });

  it("pairs partners whose extensions differ", () => {
    expect(inferSampleName("x_1.fastq.gz", ["x_1.fastq.gz", "x_2.fq"])).toBe("x");
  });

  it("does not treat numbered chunks as mates", () => {
    const chunks = ["reads_0.fastq.gz", "reads_1.fastq.gz", "reads_2.fastq.gz", "reads_3.fastq.gz"];
    expect(chunks.map((c) => inferSampleName(c, chunks))).toEqual(["reads_0", "reads_1", "reads_2", "reads_3"]);
  });

  it("limits proposals to the 255 characters a sample ID allows", () => {
    expect(inferSampleName(`${"a".repeat(300)}_R1.fastq`, [])).toHaveLength(255);
  });
});

describe("groupFilesBySample", () => {
  it("groups Illumina pairs and orders R1 before R2", () => {
    const names = ["B_S2_L001_R2_001.fastq.gz", "A_S1_L001_R1_001.fastq.gz", "B_S2_L001_R1_001.fastq.gz", "A_S1_L001_R2_001.fastq.gz"];
    expect(groups(names)).toEqual([
      ["A", [["A_S1_L001_R1_001.fastq.gz", "R1"], ["A_S1_L001_R2_001.fastq.gz", "R2"]]],
      ["B", [["B_S2_L001_R1_001.fastq.gz", "R1"], ["B_S2_L001_R2_001.fastq.gz", "R2"]]],
    ]);
    expect(groupFilesBySample(names).every((g) => g.warnings.length === 0)).toBe(true);
  });

  it("sorts sample names naturally", () => {
    const names = ["S10_R1.fq", "S2_R1.fq", "S1_R1.fq", "S10_R2.fq", "S2_R2.fq", "S1_R2.fq"];
    expect(groupFilesBySample(names).map((g) => g.sampleName)).toEqual(["S1", "S2", "S10"]);
  });

  it("groups SRA-style mates and keeps single-end and ONT files on their own", () => {
    const names = ["SRR1_1.fastq.gz", "SRR1_2.fastq.gz", "barcode01.fastq.gz", "barcode02.fastq.gz", "isolate_2.fastq"];
    expect(groups(names)).toEqual([
      ["barcode01", [["barcode01.fastq.gz", null]]],
      ["barcode02", [["barcode02.fastq.gz", null]]],
      ["isolate_2", [["isolate_2.fastq", null]]],
      ["SRR1", [["SRR1_1.fastq.gz", "R1"], ["SRR1_2.fastq.gz", "R2"]]],
    ]);
    expect(groupFilesBySample(names).flatMap((g) => g.warnings)).toEqual([]);
  });

  it("puts several lanes of one sample in one group without a warning", () => {
    const names = ["A_S1_L001_R1_001.fastq.gz", "A_S1_L001_R2_001.fastq.gz", "A_S1_L002_R1_001.fastq.gz", "A_S1_L002_R2_001.fastq.gz"];
    const [g] = groupFilesBySample(names);
    expect(g.sampleName).toBe("A");
    expect(g.files.map((f) => f.mate)).toEqual(["R1", "R1", "R2", "R2"]);
    expect(g.warnings).toEqual([]);
  });

  it("warns about R1 without R2 and the reverse", () => {
    expect(groupFilesBySample(["A_R1_001.fastq.gz"])[0].warnings).toEqual(["R1 without its R2 file: A_R1_001.fastq.gz"]);
    expect(groupFilesBySample(["A_R2.fq"])[0].warnings).toEqual(["R2 without its R1 file: A_R2.fq"]);
  });

  it("warns about a lane missing its mate even when other lanes are paired", () => {
    const names = ["A_S1_L001_R1_001.fastq.gz", "A_S1_L001_R2_001.fastq.gz", "A_S1_L002_R1_001.fastq.gz"];
    expect(groupFilesBySample(names)[0].warnings).toEqual(["R1 without its R2 file: A_S1_L002_R1_001.fastq.gz"]);
  });

  it("warns when a mate has more than two files", () => {
    const names = [1, 2, 3].flatMap((l) => [`A_S1_L00${l}_R1_001.fastq.gz`, `A_S1_L00${l}_R2_001.fastq.gz`]);
    expect(groupFilesBySample(names)[0].warnings).toEqual([
      "3 R1 files in one sample: check that they belong together (e.g. several lanes or runs)",
      "3 R2 files in one sample: check that they belong together (e.g. several lanes or runs)",
    ]);
  });

  it("keeps duplicate names (from different folders) in the same group", () => {
    const [g] = groupFilesBySample(["run1/A_R1.fq", "run2/A_R1.fq"]);
    expect(g.sampleName).toBe("A");
    expect(g.files).toHaveLength(2);
  });

  it("returns nothing for no files", () => {
    expect(groupFilesBySample([])).toEqual([]);
  });
});

describe("isSequenceFile", () => {
  it("recognises FASTQ/FASTA with optional gzip only", () => {
    expect(["a.fastq", "a.FQ.GZ", "a.fasta.gz", "a.fna", "a.fas", "dir/a.fa"].every(isSequenceFile)).toBe(true);
    expect(["a.pod5", "SampleSheet.csv", "a.fastq.bz2", "a.gz", "report.html"].some(isSequenceFile)).toBe(false);
  });
});
