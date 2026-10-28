import { describe, expect, it } from "vitest";
import { GUIDE_BY_ID } from "@/guide/metrics";
import { dictionaries, interpolate } from "@/i18n";
import { shellJoin } from "@/lib/format";
import { toolMessage } from "@/lib/messages";
import {
  DEFINITION_KEY,
  FRACTION_TITLE_KEY,
  REASON_KEY,
  UNIT_KEY,
  columnGroups,
  columnTitle,
  formatStat,
  outputNamed,
  planBySample,
  reportViews,
} from "@/lib/multiqc";
import { jobLabel } from "@/lib/results";
import type { MultiqcColumn, MultiqcPlan, MultiqcPlannedInput } from "@/lib/types";

const col = (module: MultiqcColumn["module"], key: string, hidden = false): MultiqcColumn => ({
  module,
  key,
  title: key,
  description: "",
  unit: "%",
  origin: "tool",
  hidden,
});

describe("formatStat", () => {
  it("shows each raw value in its own unit without rescaling", () => {
    expect(formatStat(3688, "reads")).toBe("3,688");
    expect(formatStat(1366991, "bases")).toBe("1,366,991");
    expect(formatStat(0.698063, "fraction")).toBe("0.6981");
    expect(formatStat(7.3999999999999995, "%")).toBe("7.40");
    expect(formatStat(150, "bp")).toBe("150");
    expect(formatStat(3784.5, "bp")).toBe("3,784.5");
  });

  it("marks missing values instead of inventing them", () => {
    expect(formatStat(undefined, "reads")).toBe("—");
    expect(formatStat(Number.NaN, "%")).toBe("—");
  });
});

describe("columnGroups", () => {
  const columns = [col("seqkit", "num_seqs"), col("fastqc", "percent_fails", true), col("fastqc", "percent_gc"), col("filtlong", "Bases kept", true)];

  it("groups by tool in report order and hides MultiQC's hidden columns unless asked", () => {
    expect(columnGroups(columns, false).map((g) => [g.module, g.columns.map((c) => c.key)])).toEqual([
      ["fastqc", ["percent_gc"]],
      ["seqkit", ["num_seqs"]],
    ]);
    expect(columnGroups(columns, true).map((g) => g.module)).toEqual(["fastqc", "seqkit", "filtlong"]);
  });

  const en = (k: keyof typeof dictionaries.en) => dictionaries.en[k];

  it("drops the empty brackets left where MultiQC put its million suffix", () => {
    expect(columnTitle({ module: "filtlong", key: "Target bases", title: "Target bases ()", unit: "bases" }, en)).toBe("Target bases");
    expect(columnTitle({ module: "fastp", key: "pct_surviving_reads", title: "% PF (Reads)", unit: "%" }, en)).toBe("% PF (Reads)");
  });

  it("never puts MultiQC's percentage title above a raw fraction", () => {
    const q30 = { module: "fastp", key: "after_filtering_q30_rate", title: "% > Q30", unit: "fraction" } as const;
    expect(columnTitle(q30, en)).toBe("Q30 bases after filtering");
    expect(columnTitle(q30, (k) => dictionaries.es[k])).toBe("Bases Q30 tras el filtrado");
    expect(columnTitle({ module: "fastp", key: "other_rate", title: "% Other", unit: "fraction" }, en)).toBe("Other");
    for (const key of Object.values(FRACTION_TITLE_KEY)) {
      expect(dictionaries.en[key]).not.toContain("%");
      expect(dictionaries.es[key]).toBeTruthy();
    }
  });
});

describe("planBySample", () => {
  it("lists each sample once with what is included and what is left out", () => {
    const input: MultiqcPlannedInput = {
      module: "fastqc",
      name: "B R1",
      sample_id: "b",
      sample_code: "B",
      job_id: "j1",
      tool_name: "FastQC",
      tool_version: "0.12.1",
      finished_at: null,
      file_ids: ["f"],
      file_names: ["r1.fq.gz"],
      output_path: "x",
    };
    const plan: MultiqcPlan = {
      selection_rule: "",
      modules: ["fastqc"],
      sample_ids: ["a", "b"],
      include_derived: false,
      inputs: [input],
      excluded: [
        { sample_id: "a", sample_code: "A", reason: "no_outputs", module: null, job_id: null, file_names: [] },
        { sample_id: "b", sample_code: "B", reason: "derived_input", module: "fastqc", job_id: "j2", file_names: ["r1.fastp.fq.gz"] },
      ],
    };
    const grouped = planBySample(plan);
    expect(grouped.map((g) => [g.code, g.inputs.length, g.excluded.map((e) => e.reason)])).toEqual([
      ["A", 0, ["no_outputs"]],
      ["B", 1, ["derived_input"]],
    ]);
  });
});

describe("translations and guide", () => {
  const keys = [...Object.values(DEFINITION_KEY), ...Object.values(REASON_KEY), ...Object.values(UNIT_KEY), "multiqc.title", "multiqc.privacy"] as const;

  it("has every MultiQC string in English and Spanish", () => {
    for (const key of keys) {
      expect(dictionaries.en[key], key).toBeTruthy();
      expect(dictionaries.es[key], key).toBeTruthy();
    }
    expect(jobLabel("multiqc", (k) => dictionaries.es[k])).toBe("Informe de QC del proyecto (MultiQC)");
  });

  it("defines every general-statistics value ARVA stores for MultiQC 1.35", () => {
    // Mirrors arva_tools.multiqc.GENERAL_STATS.
    expect(Object.keys(DEFINITION_KEY)).toHaveLength(25);
    expect(DEFINITION_KEY["fastp:after_filtering_q30_rate"]).toBe("multiqc.def.fastp.q30_rate");
  });

  it("explains MultiQC in the guide with its citation", () => {
    const entry = GUIDE_BY_ID.multiqc;
    expect(entry.references.map((r) => r.url)).toContain("https://doi.org/10.1093/bioinformatics/btw354");
    expect(entry.es.limitations).toContain("IDs de muestra");
  });
});

describe("reportViews", () => {
  const job = (id: string, status: "completed" | "failed" | "running") => ({ id, status });

  it("keeps the general statistics of the most recent completed report when a newer run failed or is running", () => {
    const [running, failed, done, older] = [job("4", "running"), job("3", "failed"), job("2", "completed"), job("1", "completed")];
    expect(reportViews([running, failed, done, older])).toEqual({ latest: running, completed: done, previous: [failed, older] });
    expect(reportViews([done, older])).toEqual({ latest: done, completed: done, previous: [older] });
    expect(reportViews([failed])).toEqual({ latest: failed, completed: undefined, previous: [] });
    expect(reportViews([])).toEqual({ latest: undefined, completed: undefined, previous: [] });
  });
});

describe("tool messages", () => {
  const tool = { reason: "multiqc_too_old", message: "Version 1.18 is older than the minimum supported 1.35. Older releases…", version: "1.18", min_version: "1.35" };

  it("shows a known detection reason in the interface language", () => {
    expect(toolMessage((k, v) => interpolate(dictionaries.es[k], v), tool)).toContain("El MultiQC encontrado (1.18) no puede usarse: ARVA necesita 1.35");
    const nanomath = { reason: "nanomath_replaced", message: "x", version: "1.48.0", min_version: "1.48.0" };
    expect(toolMessage((k, v) => interpolate(dictionaries.es[k], v), nanomath)).toContain("NanoPlot 1.48.0 importa un módulo nanomath");
  });

  it("falls back to the server's text for messages without a known code", () => {
    expect(toolMessage((k, v) => interpolate(dictionaries.es[k], v), { ...tool, reason: null, message: "Executable not found" })).toBe("Executable not found");
    expect(toolMessage((k, v) => interpolate(dictionaries.es[k], v), { ...tool, reason: "unknown_code", message: "raw" })).toBe("raw");
  });
});

describe("helpers", () => {
  it("quotes only the arguments a shell would split", () => {
    expect(shellJoin(["multiqc", "--title", "Survey - ARVA project QC report", "--force"])).toBe(
      "multiqc --title 'Survey - ARVA project QC report' --force",
    );
    expect(shellJoin(["a'b"])).toBe(`'a'"'"'b'`);
  });

  it("finds a job output by file name", () => {
    expect(outputNamed({ output_paths: ["results/p/_project/j/arva_multiqc_report.html"] }, "arva_multiqc_report.html")).toBe(
      "results/p/_project/j/arva_multiqc_report.html",
    );
    expect(outputNamed({ output_paths: null }, "x")).toBeUndefined();
  });
});
