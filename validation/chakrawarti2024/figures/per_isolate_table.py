"""Per-isolate table of the benchmark (source of Supplementary Table S1) and the summary figures quoted in the paper.

Usage: per_isolate_table.py <validation folder> <output folder>
Reads expected.tsv, isolates.tsv and results/<isolate>.json; writes <output folder>/per_isolate.tsv.
"""

import csv
import json
import statistics
import sys
from pathlib import Path

STEPS_TYPING = ("mlst", "typing_sccmec", "typing_spa", "typing_agr", "amrfinderplus")


def row(root: Path, isolate: str, expected: dict) -> dict:
    d = json.loads((root / "results" / f"{isolate}.json").read_text())
    summary, polished, draft = d["summary"], d["assembly_polished"]["stats"], d["assembly_flye"]["stats"]
    steps, amr = d["steps"], d["amrfinderplus"]
    genes = sorted({h["element_symbol"] for h in amr["hits"] if h["type"] == "AMR"})
    profile = d["provenance"]["performance_profile"]
    return {
        "isolate": isolate,
        "source": d["input"]["source"],
        "run": d["input"]["ont_run"],
        "reads": int(d["input"]["ont_read_count"]),
        "bases_mb": round(int(d["input"]["ont_base_count"]) / 1e6, 1),
        "depth_x": round(polished["coverage"]["length_weighted_median"]),
        "contigs": polished["contig_count"],
        "circular": polished["circularity"]["circular_contigs"],
        "length_bp": polished["total_length"],
        "n50": polished["n50"],
        "gc": round(polished["gc_percent"], 2),
        "len_change_medaka": polished["total_length"] - draft["total_length"],
        "sanger_st": expected["sanger_st"],
        "paper_ont_st": expected["ont_asm_st_paper"],
        "arva_st": summary["st"] or "",
        "mlst_status": summary["mlst_status"],
        "alleles": " ".join(f"{locus}({call})" for locus, call in summary["alleles"].items()),
        "spa_ref": expected["spa_hyb_asm"],
        "spa_arva": summary["spa"],
        "agr": summary["agr"] or "",
        "sccmec": d["typing"]["sccmec"][0]["status"],
        "pen": expected["ast_penicillin"],
        "oxa": expected["ast_oxacillin"],
        "fox": expected["ast_cefoxitin"],
        "tet": expected["ast_tetracycline"],
        "ery": expected["ast_erythromycin"],
        "lin": expected["ast_lincomycin"],
        "amr_genes": ",".join(genes),
        "t_filtlong": steps["filtlong"]["duration_seconds"],
        "t_flye": steps["flye"]["duration_seconds"],
        "t_medaka": steps["polishing_medaka"]["duration_seconds"],
        "t_typing": sum(steps[k]["duration_seconds"] for k in STEPS_TYPING),
        "wall_s": d["wall_seconds"],
        "peak_mem_gib": round(d["resources"]["peak_memory_used_bytes"] / 2**30, 1),
        "largest_rss_gib": round(d["resources"]["largest_process_rss_bytes"] / 2**30, 1),
        "largest_proc": d["resources"]["largest_process_name"],
        "threads": profile["usable_cpus"],
        "usable_mem_gib": round(profile["usable_memory_gb"], 1),
        "image": d["provenance"]["arva_image"],
        "amr_db": amr["database_version"],
        "mlst_db": d["mlst"]["database_version"],
    }


def main() -> None:
    root, out = Path(sys.argv[1]), Path(sys.argv[2])
    with (root / "expected.tsv").open() as f:
        expected = {r["isolate"]: r for r in csv.DictReader(f, delimiter="\t")}
    with (root / "isolates.tsv").open() as f:
        order = [r["isolate"] for r in csv.DictReader(f, delimiter="\t")]
    rows = [row(root, isolate, expected[isolate]) for isolate in order]
    with (out / "per_isolate.tsv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]), delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)
    print("isolates", len(rows))
    for key in ("reads", "bases_mb", "depth_x", "contigs", "length_bp", "wall_s", "t_flye", "t_medaka", "peak_mem_gib"):
        values = [r[key] for r in rows]
        print(f"{key}: median {statistics.median(values)}, range {min(values)}-{max(values)}")


if __name__ == "__main__":
    main()
