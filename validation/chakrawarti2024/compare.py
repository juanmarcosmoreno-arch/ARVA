#!/usr/bin/env python3
"""Compare ARVA's results (results/<isolate>.json from run_validation.py) with the paper's values (expected.tsv).

Writes results/concordance.tsv (one row per isolate) and results/concordance.md (counts and notes). Every count says
what it is out of: isolates without an ARVA result are listed as missing, never counted as matches or mismatches.

Comparisons:
- ST: ARVA's mlst ST against the Sanger ST (gold standard) and against the paper's ONT-only (ONT-Asm) call. A novel or
  partial profile (mlst reports no ST) counts as "no ST", which is not a match.
- spa: ARVA's spaTyper call against the hybrid-assembly spa type (Table S5).
- blaZ against penicillin (Table S7; blaZ_inferred is our inference from Table 1, see README) and mecA against
  oxacillin and cefoxitin (all S: mecA is expected absent).
- Soft checks from the paper's text: tet(K) / tetracycline, erm(A|B|C|T) / erythromycin, lnu(G) / lincomycin.

Run: apps/api/.venv/bin/python -I validation/chakrawarti2024/compare.py
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent


def st_of(value: str | None) -> str | None:
    """'398' -> '398'; anything else (None, '-', 'novel', 'Undetermined') -> None."""
    return value if value is not None and re.fullmatch(r"\d+", str(value)) else None


def profiles(path: Path) -> dict[str, dict[str, str]]:
    """ST -> {locus: allele} from mlst's PubMLST profile table (saureus.txt), empty when the file is missing."""
    if not path.is_file():
        return {}
    with open(path, newline="") as fh:
        return {r["ST"]: {k: v for k, v in r.items() if k != "ST"} for r in csv.DictReader(fh, delimiter="\t")}


def allele_diff(alleles: dict[str, str], profile: dict[str, str] | None) -> str:
    """Loci where ARVA's call differs from the Sanger ST's profile, e.g. 'arcC 484 (Sanger ST: 1)'."""
    if not profile or not alleles:
        return ""
    return "; ".join(f"{locus} {alleles.get(locus, '?')} (Sanger ST: {allele})" for locus, allele in profile.items()
                     if alleles.get(locus) != allele)


def has(genes: list[str], pattern: str) -> bool:
    rx = re.compile(pattern)
    return any(rx.fullmatch(g) for g in genes)


def verdict(ok: bool | None) -> str:
    return "NA" if ok is None else "match" if ok else "MISMATCH"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--results", type=Path, default=HERE / "results")
    ap.add_argument("--expected", type=Path, default=HERE / "expected.tsv")
    ap.add_argument("--isolates", type=Path, default=HERE / "isolates.tsv")
    ap.add_argument("--mlst-profiles", type=Path, default=Path.home() / ".arva-tools/conda/mlst/db/pubmlst/saureus/"
                    "saureus.txt", help="mlst's S. aureus profile table, to name the loci that differ from Sanger")
    args = ap.parse_args()
    with open(args.expected, newline="") as fh:
        expected = list(csv.DictReader(fh, delimiter="\t"))
    sts = profiles(args.mlst_profiles)

    rows, missing, failed = [], [], []
    for exp in expected:
        name = exp["isolate"]
        path = args.results / f"{name}.json"
        if not path.exists():
            (failed if (args.results / f"{name}.failed.json").exists() else missing).append(name)
            continue
        res = json.loads(path.read_text())
        s = res.get("summary") or {}
        genes = s.get("amr_genes") or []
        arva_st = st_of(s.get("st"))
        sanger = st_of(exp["sanger_st"])
        paper_ont = exp["ont_asm_st_paper"]
        blaz = has(genes, r"blaZ")
        meca = has(genes, r"mecA|mecC")
        pen_r = exp["ast_penicillin"] == "R"
        oxa_r = exp["ast_oxacillin"] == "R" or exp["ast_cefoxitin"] == "R"
        rows.append({
            "isolate": name,
            "source": exp["source"],
            "sanger_st": exp["sanger_st"],
            "paper_ont_st": paper_ont,
            "arva_st": s.get("st") or "",
            "arva_mlst_status": s.get("mlst_status") or "",
            "arva_alleles": " ".join(f"{k}({v})" for k, v in (s.get("alleles") or {}).items()),
            "loci_differing_from_sanger_profile": allele_diff(s.get("alleles") or {}, sts.get(exp["sanger_st"])),
            "st_vs_sanger": verdict(arva_st is not None and arva_st == sanger),
            "st_vs_paper_ont": ("both_undetermined" if arva_st is None and st_of(paper_ont) is None else
                                verdict(arva_st == st_of(paper_ont))),
            "spa_paper_hyb": exp["spa_hyb_asm"],
            "arva_spa": s.get("spa") or "",
            "spa_vs_paper": verdict(None if not exp["spa_hyb_asm"] else (s.get("spa") or "") == exp["spa_hyb_asm"]),
            "penicillin": exp["ast_penicillin"],
            "arva_blaZ": "present" if blaz else "absent",
            "blaZ_vs_penicillin": verdict(blaz == pen_r),
            "oxacillin_cefoxitin": f"{exp['ast_oxacillin']}/{exp['ast_cefoxitin']}",
            "arva_mecA": "present" if meca else "absent",
            "mecA_vs_oxacillin": verdict(meca == oxa_r),
            "tetracycline": exp["ast_tetracycline"],
            "arva_tetK": "present" if has(genes, r"tet\(K\)") else "absent",
            "erythromycin": exp["ast_erythromycin"],
            "arva_erm": ",".join(g for g in genes if g.startswith("erm")) or "absent",
            "lincomycin": exp["ast_lincomycin"],
            "arva_lnuG": "present" if has(genes, r"lnu\(G\)") else "absent",
            "arva_sccmec": s.get("sccmec") or next((f"{t.get('status')} (mecA {'yes' if (t.get('details') or {}).get('mecA')
                                                    else 'no'})" for t in (res.get("typing") or {}).get("sccmec") or []),
                                                   ""),
            "arva_agr": s.get("agr") or "",
            "arva_amr_genes": ",".join(genes),
            "polisher": s.get("polisher") or "",
            "contigs": s.get("contigs") or "",
            "total_length": s.get("total_length") or "",
            "wall_minutes": round((res.get("wall_seconds") or 0) / 60, 1),
        })

    out_tsv = args.results / "concordance.tsv"
    if rows:
        with open(out_tsv, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]), delimiter="\t")
            w.writeheader()
            w.writerows(rows)

    def count(col: str, value: str = "match") -> str:
        scored = [r for r in rows if r[col] in ("match", "MISMATCH")]
        return f"{sum(r[col] == value for r in scored)}/{len(scored)}"

    disc = [r for r in rows if st_of(r["paper_ont_st"]) != st_of(r["sanger_st"])]
    lines = [
        "# ARVA vs Chakrawarti et al. 2024: concordance",
        "",
        f"Isolates with ARVA results: {len(rows)} of {len(expected)}."
        + (f" Failed: {', '.join(failed)}." if failed else "")
        + (f" Not run yet: {', '.join(missing)}." if missing else ""),
        "",
        "| Comparison | ARVA matches | Notes |",
        "|---|---|---|",
        f"| ST vs Sanger (gold standard) | {count('st_vs_sanger')} | no ST from ARVA counts as a mismatch |",
        f"| ST vs paper's ONT-only call | {count('st_vs_paper_ont')} | "
        f"{sum(r['st_vs_paper_ont'] == 'both_undetermined' for r in rows)} more where both gave no ST |",
        f"| ST vs Sanger, isolates the paper's ONT-only assembly got wrong | "
        f"{sum(r['st_vs_sanger'] == 'match' for r in disc)}/{len(disc)} | ONT-only 'Undetermined' or wrong in Table S3 |",
        f"| spa vs hybrid assembly (Table S5) | {count('spa_vs_paper')} | |",
        f"| blaZ vs penicillin phenotype | {count('blaZ_vs_penicillin')} | blaZ expected exactly in penicillin R "
        "(Table 1; Table 1 and Table S7 disagree on the R count, see README) |",
        f"| mecA vs oxacillin/cefoxitin | {count('mecA_vs_oxacillin')} | all isolates are S: mecA expected absent |",
        "",
        "## Per isolate",
        "",
        "| Isolate | Sanger ST | Paper ONT ST | ARVA ST | Loci differing from the Sanger profile | spa paper / ARVA "
        "| Pen / blaZ | Oxa / mecA | Polisher |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(f"| {r['isolate']} | {r['sanger_st']} | {r['paper_ont_st']} | {r['arva_st'] or r['arva_mlst_status'] or '-'} "
                     f"({r['st_vs_sanger']}) | {r['loci_differing_from_sanger_profile'] or '-'} | {r['spa_paper_hyb']} / {r['arva_spa'] or '-'} ({r['spa_vs_paper']}) | "
                     f"{r['penicillin']} / {r['arva_blaZ']} | {r['oxacillin_cefoxitin']} / {r['arva_mecA']} | "
                     f"{r['polisher']} |")
    lines += ["", "## Soft checks (genes named in the paper's text)", "",
              "| Isolate | Tet / tet(K) | Ery / erm | Lin / lnu(G) | SCCmec | agr | AMR genes (AMRFinderPlus, type AMR) |",
              "|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['isolate']} | {r['tetracycline']} / {r['arva_tetK']} | {r['erythromycin']} / "
                     f"{r['arva_erm']} | {r['lincomycin']} / {r['arva_lnuG']} | {r['arva_sccmec'] or '-'} | "
                     f"{r['arva_agr'] or '-'} | {r['arva_amr_genes'] or '-'} |")
    lines += ["", "Values from the paper: expected.tsv (Tables S3, S5, S7 of the supplement; CC BY 4.0). "
              "blaZ_inferred and the mecA expectation are inferences, see README.md.", ""]
    (args.results / "concordance.md").write_text("\n".join(lines))
    print("\n".join(lines))


if __name__ == "__main__":
    main()
