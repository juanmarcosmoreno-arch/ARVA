import csv
import io
from typing import Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse, Response
from sqlalchemy.orm import Session

from app.api.deps import project_or_404
from app.db.session import get_db
from app.services import discover as svc
from app.storage.local import sanitize_filename

router = APIRouter(tags=["discover"])

Analysis = Literal["associations", "cooccurrence", "lineage", "heatmap", "pca"]


@router.get("/projects/{project_id}/discover")
def discover_summary(project_id: str, db: Session = Depends(get_db)):
    """The fields and features Discover can use for this project, with their coverage and provenance."""
    return svc.summary(svc.table(db, project_or_404(db, project_id)))


def _run(db: Session, project_id: str, analysis: str, sources: list[str], one_hot: list[str], group: str | None,
         lineage: str | None, min_group: int, min_with: int, alpha: float):
    project = project_or_404(db, project_id)
    return svc.analyse(db, project, analysis, sources, one_hot, group, lineage, min_group, min_with, alpha)


@router.get("/projects/{project_id}/discover/analysis")
def discover_analysis(project_id: str, analysis: Analysis,
                      sources: list[str] = Query(default=["amr"], max_length=3),
                      one_hot: list[str] = Query(default=[], max_length=20),
                      group: str | None = Query(None, max_length=200), lineage: str | None = Query(None, max_length=200),
                      min_group: int = Query(2, ge=1, le=1000), min_with: int = Query(1, ge=1, le=10000),
                      alpha: float = Query(0.05, gt=0, lt=1), db: Session = Depends(get_db)):
    """One exploratory analysis (not confirmatory): every result carries its sample sizes, effect sizes with 95 %
    intervals where they apply, the multiple-testing correction and the caveats to show with it."""
    try:
        return _run(db, project_id, analysis, sources, one_hot, group, lineage, min_group, min_with, alpha)
    except (svc.DiscoverError, ValueError) as exc:
        code = getattr(exc, "code", "discover_invalid")
        return JSONResponse(status_code=400, content={"detail": str(exc), "code": code,
                                                      "params": getattr(exc, "params", {})})


CSV_COLUMNS = {
    "associations": ["group", "feature", "samples", "in_group_with", "in_group_without", "others_with",
                     "others_without", "share_group", "share_group_ci", "share_others", "share_others_ci",
                     "difference", "difference_ci", "odds_ratio", "odds_ratio_ci", "haldane_corrected", "p", "q",
                     "lineage_informative_strata", "lineage_cmh_p", "lineage_cmh_q", "lineage_mh_odds_ratio",
                     "lineage_mh_odds_ratio_ci"],
    "cooccurrence": ["feature_1", "feature_2", "samples", "both", "only_1", "only_2", "neither", "phi", "jaccard",
                     "odds_ratio", "odds_ratio_ci", "haldane_corrected", "p", "q", "lineage_informative_strata",
                     "lineage_cmh_p", "lineage_cmh_q"],
}


def _ci(v) -> str:
    return "" if not v else f"{v[0]}-{v[1]}"


def _safe(v) -> str:
    text = "" if v is None else str(v)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") and not text[1:2].isdigit() else text


@router.get("/projects/{project_id}/discover/analysis.csv")
def discover_csv(project_id: str, analysis: Literal["associations", "cooccurrence"],
                 sources: list[str] = Query(default=["amr"], max_length=3),
                 one_hot: list[str] = Query(default=[], max_length=20),
                 group: str | None = Query(None, max_length=200), lineage: str | None = Query(None, max_length=200),
                 min_group: int = Query(2, ge=1, le=1000), min_with: int = Query(1, ge=1, le=10000),
                 alpha: float = Query(0.05, gt=0, lt=1), db: Session = Depends(get_db)):
    try:
        r = _run(db, project_id, analysis, sources, one_hot, group, lineage, min_group, min_with, alpha)
    except (svc.DiscoverError, ValueError) as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc), "code": getattr(exc, "code", "discover_invalid"),
                                                      "params": getattr(exc, "params", {})})
    out = io.StringIO()
    out.write(f"# ARVA Discover: {analysis}. Exploratory, not confirmatory. {r['method']}\n")
    w = csv.writer(out)
    w.writerow(CSV_COLUMNS[analysis])
    for x in r["rows"]:
        st = x.get("stratified") or {}
        a, b, c, d = x["table"]
        lineage_cols = [st.get("informative_strata", ""), st.get("p", ""), st.get("q", "")]
        if analysis == "associations":
            row = [x["group"], x["feature"], x["samples"], a, b, c, d, x["share_1"], _ci(x["share_1_ci"]),
                   x["share_2"], _ci(x["share_2_ci"]), x["difference"], _ci(x["difference_ci"]), x["odds_ratio"],
                   _ci(x["odds_ratio_ci"]), x["haldane_corrected"], x["p"], x["q"], *lineage_cols,
                   st.get("odds_ratio", ""), _ci(st.get("odds_ratio_ci"))]
        else:
            row = [x["feature_1"], x["feature_2"], x["samples"], a, b, c, d, x["phi"], x["jaccard"], x["odds_ratio"],
                   _ci(x["odds_ratio_ci"]), x["haldane_corrected"], x["p"], x["q"], *lineage_cols]
        w.writerow([_safe(v) for v in row])
    name = sanitize_filename(f"ARVA_discover_{analysis}.csv")
    return Response(out.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})
