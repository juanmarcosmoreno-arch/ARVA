"""Report sections for variant analysis and the consolidated mobilome: the sample report's sections (data and HTML)
and the project's variant report (each reference's runs and, with two samples or more, the SNP distances)."""
from __future__ import annotations

import json
from html import escape
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AnalysisJob, Project, Sample, VariantCall
from app.services import mobilome
from app.services import variants as svc

VARIANT_LIMITATIONS = [
    "Variants are differences between the reads and the chosen reference: their number depends on how close the "
    "reference is, and regions absent from the reference (or with depth below the minimum) cannot show variants.",
    "Calls are haploid (bcftools call --ploidy 1); a mixed population or a collapsed repeat shows as sites with an "
    "intermediate alternative-allele fraction, which the LowAltFraction filter flags.",
    "The filter thresholds (QUAL, depth, alternative-allele fraction, mapping quality) are Snippy 4.6.0's defaults, "
    "not values validated for every organism or technology; bcftools' QUAL is not on FreeBayes' (Snippy's) scale.",
    "Effects come from bcftools csq with the standard genetic code: a change of a GTG or TTG start codon is reported "
    "as missense or synonymous (marked 'start codon'), never as start_lost.",
    "SNP distances are counted at SNP sites against one reference, with pairwise deletion of missing sites; they are "
    "not a phylogeny and do not account for recombination, indels or regions absent from the reference.",
]
VARIANT_LIMITATIONS_ES = [
    "Las variantes son diferencias entre las lecturas y la referencia elegida: su número depende de lo cercana que "
    "sea la referencia, y las regiones ausentes de la referencia (o con profundidad inferior a la mínima) no pueden "
    "mostrar variantes.",
    "Las llamadas son haploides (bcftools call --ploidy 1); una población mixta o una repetición colapsada aparece "
    "como sitios con una fracción intermedia del alelo alternativo, que el filtro LowAltFraction marca.",
    "Los umbrales de los filtros (QUAL, profundidad, fracción del alelo alternativo, calidad de mapeo) son los "
    "predeterminados de Snippy 4.6.0, no valores validados para cada organismo o tecnología; el QUAL de bcftools no "
    "está en la escala de FreeBayes (Snippy).",
    "Los efectos proceden de bcftools csq con el código genético estándar: un cambio de un codón de inicio GTG o TTG "
    "se informa como missense o sinónimo (marcado «codón de inicio»), nunca como start_lost.",
    "Las distancias SNP se cuentan en sitios SNP frente a una referencia, con eliminación por pares de los sitios sin "
    "dato; no son una filogenia y no tienen en cuenta la recombinación, los indels ni las regiones ausentes de la "
    "referencia.",
]
MOBILOME_LIMITATIONS = [
    "Genes are placed next to plasmids and mobile elements by coordinates only (overlapping, on the same contig "
    "within the stated distance, or on a contig MOB-suite assigned to a plasmid). Physical proximity is not evidence "
    "of mobilisation or horizontal transfer.",
]
VARIANT_METHODS = (
    "<p>Variants: the sample's reads were aligned to the reference with BWA-MEM (short reads; -K fixed for "
    "reproducibility) or minimap2 (-x map-ont or map-hifi), sorted and indexed with samtools; bcftools mpileup "
    "(the options of its technology profile written out, minimum mapping and base quality, maximum depth, FORMAT/AD "
    "and DP) | call --ploidy 1 -m | norm -f -m -any (left-aligned, split) | filter (soft: LowQual, LowDepth, "
    "LowAltFraction) | csq (when the reference has an ARVA annotation; Ensembl-style GFF3 written by ARVA from its "
    "CDS) | index. Callable positions are those with depth at least the minimum depth counting only reads and bases "
    "above the quality floors (samtools depth -Q -q). The exact commands are listed with each run.</p>")


VARIANT_METHODS_ES = (
    "<p>Variantes: las lecturas de la muestra se alinearon con la referencia con BWA-MEM (lecturas cortas; -K fijo "
    "para la reproducibilidad) o minimap2 (-x map-ont o map-hifi), se ordenaron e indexaron con samtools; bcftools "
    "mpileup (con las opciones de su perfil de tecnología escritas, calidad mínima de mapeo y de base, profundidad "
    "máxima, FORMAT/AD y DP) | call --ploidy 1 -m | norm -f -m -any (alineadas a la izquierda, separadas) | filter "
    "(suave: LowQual, LowDepth, LowAltFraction) | csq (cuando la referencia tiene una anotación de ARVA; GFF3 de "
    "estilo Ensembl escrito por ARVA a partir de sus CDS) | index. Las posiciones evaluables son las que tienen al "
    "menos la profundidad mínima contando solo lecturas y bases por encima de los umbrales de calidad (samtools "
    "depth -Q -q). Los comandos exactos figuran con cada ejecución.</p>")
PROJECT_LABELS: dict[str, dict[str, str]] = {
    "en": {"title": "Variant analysis", "sample": "Sample", "technology": "Technology",
           "aligned": "Reads aligned (%)", "callable": "Callable (%)", "records": "Records", "passing": "Passing",
           "snps": "Passing SNPs", "distances": "Pairwise SNP distances",
           "distances_note": "{sites} SNP site(s), {core} with a base in every sample. Each cell counts the SNP sites "
                             "where both samples have a base and they differ (hover: the number of SNP sites with a "
                             "base in both, not the callable genome positions). Not a phylogeny.",
           "settings_differ": " The runs used different filter settings.", "with_both": "{n} SNP sites with a base in both",
           "none": "No variant-calling run in this project.", "methods": "Methods", "limitations": "Limitations"},
    "es": {"title": "Análisis de variantes", "sample": "Muestra", "technology": "Tecnología",
           "aligned": "Lecturas alineadas (%)", "callable": "Evaluable (%)", "records": "Registros",
           "passing": "Superan los filtros", "snps": "SNP que superan los filtros",
           "distances": "Distancias SNP por pares",
           "distances_note": "{sites} sitio(s) SNP, {core} con una base en todas las muestras. Cada celda cuenta los "
                             "sitios SNP en los que ambas muestras tienen una base y difieren (al pasar el ratón: el "
                             "número de sitios SNP con una base en ambas, no las posiciones evaluables del genoma). No "
                             "es una filogenia.",
           "settings_differ": " Las ejecuciones usaron ajustes de filtro distintos.",
           "with_both": "{n} sitios SNP con una base en ambas",
           "none": "No hay ninguna ejecución de llamada de variantes en este proyecto.", "methods": "Métodos",
           "limitations": "Limitaciones"},
}


def sample_data(db: Session, sample: Sample) -> dict[str, Any]:
    runs = []
    for vc in db.scalars(select(VariantCall).where(VariantCall.sample_id == sample.id)
                         .order_by(VariantCall.created_at)):
        job = db.get(AnalysisJob, vc.job_id)
        brief = svc.brief(vc, job)
        brief["commands"] = [" ".join(c) for c in (job.commands or [])] if job else []
        brief["created_at"] = vc.created_at.isoformat()
        runs.append(brief)
    m = mobilome.sample_mobilome(db, sample.id)
    return {"runs": runs, "mobilome": m if m["assemblies"] else None}


def _pct(v: Any) -> str:
    return "" if v is None else f"{v:.2f}"


def _run_html(r: dict[str, Any]) -> str:
    s = r["summary"]
    ref = r["reference"]
    settings = (r["parameters"] or {}).get("settings") or {}
    types = ", ".join(f"{k} {v}" for k, v in (s.get("by_type") or {}).items() if v)
    effects = ", ".join(f"{k} {v}" for k, v in sorted((s.get("by_effect") or {}).items(), key=lambda kv: -kv[1]))
    filters = ", ".join(f"{k} {v}" for k, v in (s.get("by_filter") or {}).items()) or "none"
    reads = ", ".join(f"{x['role']}: {x['name']}" for x in r["reads"])
    warnings = "".join(f"<li>{escape(w.get('text') or w.get('code', ''))}</li>" for w in r["warnings"])
    files = "".join(f"<tr><th>{escape(k)}</th><td>SHA-256 <code>{escape(v.get('sha256', ''))}</code></td></tr>"
                    for k, v in (r["files"] or {}).items())
    al = s.get("alignment") or {}
    return (
        f"<h3>{escape(ref.get('label') or '')} · {escape(r['technology'])}</h3>"
        f"<p class='muted'>Run <code>{escape(r['id'])}</code> · {escape(str(r['created_at']))} · "
        f"{escape(r['aligner'])} {escape(r['aligner_version'])} · bcftools {escape(r['caller_version'])}</p>"
        + (f"<div class='warn'><strong>Notes</strong><ul>{warnings}</ul></div>" if warnings else "")
        + "<table>"
        f"<tr><th>Reference</th><td>{escape(ref.get('kind') or '')}: {escape(ref.get('label') or '')}"
        f"<br>SHA-256 <code>{escape(r['reference_sha256'])}</code></td></tr>"
        f"<tr><th>Reads</th><td>{escape(reads)}</td></tr>"
        f"<tr><th>Reads aligned</th><td>{_pct(al.get('mapped_percent'))} %</td></tr>"
        f"<tr><th>Callable reference (depth &ge; {settings.get('min_depth')})</th>"
        f"<td>{_pct(s.get('callable_percent'))} %</td></tr>"
        f"<tr><th>Records / passing the filters</th><td>{s.get('records')} / {s.get('pass')}</td></tr>"
        f"<tr><th>Passing, by type</th><td>{escape(types or 'none')}</td></tr>"
        f"<tr><th>Filtered (FILTER)</th><td>{escape(filters)}</td></tr>"
        f"<tr><th>Effects (bcftools csq)</th><td>{escape(effects or 'not annotated')}</td></tr>"
        f"<tr><th>Settings</th><td><code>{escape(json.dumps(settings, sort_keys=True))}</code></td></tr>"
        + files + "</table>"
        + "".join(f"<pre>{escape(c)}</pre>" for c in r.get("commands") or []))


def _mobilome_html(m: dict[str, Any]) -> str:
    parts = [f"<p class='muted'>Genes placed by coordinates: inside an element, on the same contig within "
             f"{m['window']:,} bp of it, or on a contig MOB-suite assigned to a plasmid. Proximity is not evidence of "
             "transfer.</p>"]
    for a in m["assemblies"]:
        rows = []
        for p in a["plasmids"]:
            genes = ", ".join(sorted({g["gene"] for g in p["genes"]})) or "none found"
            rows.append(f"<tr><td>Plasmid (MOB-suite)</td><td>{escape(p['id'])}</td>"
                        f"<td>{escape(', '.join(p['contigs']))}</td><td>{escape(', '.join(p['rep_types'] or []))} · "
                        f"{escape(p['predicted_mobility'] or '')}</td><td>{escape(genes)}</td></tr>")
        for e in a["elements"]:
            loc = f"{e['contig']}" + (f":{e['start']}-{e['end']}" if e["start"] is not None else " (whole contig)")
            genes = ", ".join(f"{g['gene']} ({g['relation']}{'' if not g['distance'] else ', ' + str(g['distance']) + ' bp'})"
                              for g in e["genes"]) or "none"
            rows.append(f"<tr><td>{escape(e['category'].replace('_', ' '))} ({escape(e['tool'])})</td>"
                        f"<td>{escape(e['element'] or '')}</td><td>{escape(loc)}</td>"
                        f"<td>{escape(e['element_type'] or '')} {escape(e['completeness'] or '')}</td>"
                        f"<td>{escape(genes)}</td></tr>")
        c = a["counts"]
        parts.append(
            f"<p class='muted'>Assembly <code>{escape(a['assembly_id'])}</code> ({escape(a['assembler'])}) · "
            f"{c['plasmids']} plasmid(s), {c['insertion_sequences']} IS element(s), {c['integrons']} integron(s), "
            f"{c['viruses']} virus/provirus call(s) · {c['genes_on_plasmids']} gene(s) on plasmid contigs, "
            f"{c['genes_with_elements']} with an element</p>"
            + ("<table class='grid'><tr><th>Kind</th><th>Element</th><th>Location</th><th>Type</th>"
               "<th>Resistance and virulence genes</th></tr>" + "".join(rows) + "</table>" if rows else
               "<p>No plasmid or mobile element in the most recent runs.</p>"))
    return "<h2>Mobilome (consolidated)</h2>" + "".join(parts)


def sample_html(data: dict[str, Any]) -> str:
    v = data.get("variants") or {}
    out = ""
    if v.get("runs"):
        out += ("<h2>Variants</h2><p>SNPs and small indels of the sample's reads against each reference; records "
                "that failed a filter are kept in the VCF with the filter's name.</p>"
                + "".join(_run_html(r) for r in v["runs"]))
    if v.get("mobilome"):
        out += _mobilome_html(v["mobilome"])
    return out


def methods_html(data: dict[str, Any]) -> str:
    return VARIANT_METHODS if (data.get("variants") or {}).get("runs") else ""


def limitations(data: dict[str, Any]) -> list[str]:
    v = data.get("variants") or {}
    return (VARIANT_LIMITATIONS if v.get("runs") else []) + (MOBILOME_LIMITATIONS if v.get("mobilome") else [])


def _distance_table(m: dict[str, Any], label: str = "{n} SNP sites with a base in both") -> str:
    labels = [s["label"] for s in m["samples"]]
    top = max((max(r) for r in m["distances"]), default=0) or 1
    head = "".join(f"<th>{escape(x)}</th>" for x in labels)
    rows = []
    for i, label in enumerate(labels):
        cells = []
        for j, d in enumerate(m["distances"][i]):
            shade = int(235 - 135 * d / top)
            cells.append(f"<td style='background:rgb({shade},{shade + 10 if shade < 245 else 255},255)' "
                         f"title='{escape(label.format(n=m['compared_sites'][i][j]))}'>{d}</td>")
        rows.append(f"<tr><th>{escape(label)}</th>{''.join(cells)}</tr>")
    return f"<table class='grid'><tr><th></th>{head}</tr>{''.join(rows)}</table>"


def project_html(db: Session, project: Project, lang: str = "en") -> str:
    L = PROJECT_LABELS["es" if lang == "es" else "en"]
    overview = svc.project_overview(db, project)
    sections = []
    for g in overview["references"]:
        ref = g["reference"]
        rows = "".join(
            f"<tr><td>{escape(r['sample_code'] or '')}</td><td>{escape(r['technology'])}</td>"
            f"<td>{_pct(r['mapped_percent'])}</td><td>{_pct(r['callable_percent'])}</td><td>{r['records']}</td>"
            f"<td>{r['pass']}</td><td>{(r['by_type'] or {}).get('snp', 0)}</td></tr>" for r in g["runs"])
        block = (f"<h2>{escape(ref.get('label') or '')}</h2><p class='muted'>{escape(ref.get('kind') or '')} · "
                 f"SHA-256 <code>{escape(g['reference_sha256'])}</code></p><table class='grid'><tr>"
                 f"<th>{L['sample']}</th><th>{L['technology']}</th><th>{L['aligned']}</th><th>{L['callable']}</th>"
                 f"<th>{L['records']}</th><th>{L['passing']}</th><th>{L['snps']}</th></tr>{rows}</table>")
        if len(g["runs"]) >= 2:
            m = svc.matrix(db, project, g["reference_sha256"])
            block += (f"<h3>{L['distances']}</h3><p class='muted'>"
                      + escape(L["distances_note"].format(sites=len(m["sites"]), core=m["core_sites"]))
                      + ("" if m["same_settings"] else escape(L["settings_differ"])) + "</p>"
                      + _distance_table(m, L["with_both"]))
        sections.append(block)
    body = "".join(sections) or f"<p>{L['none']}</p>"
    es = lang == "es"
    lim = "".join(f"<li>{escape(x)}</li>" for x in (VARIANT_LIMITATIONS_ES if es else VARIANT_LIMITATIONS))
    methods = VARIANT_METHODS_ES if es else VARIANT_METHODS
    return f"""<!doctype html><html lang="{'es' if es else 'en'}"><head><meta charset="utf-8"><title>ARVA · {L['title']} ·
{escape(project.name)}</title><style>
body {{ font-family: Inter, -apple-system, Segoe UI, Arial, sans-serif; color:#0B132B; background:#F8FAFC; margin:0;
       padding:32px 16px; line-height:1.5; }}
main {{ max-width: 1000px; margin: 0 auto; background:#fff; border:1px solid #E5E7EB; border-radius:12px; padding:32px; }}
h2 {{ font-size: 18px; color:#1F3B8A; margin-top: 28px; }} table {{ border-collapse: collapse; font-size: 13px; }}
th, td {{ padding: 5px 8px; border-bottom: 1px solid #EEF2F7; text-align: left; }} code {{ font-size: 11px; }}
.muted {{ color:#64748B; font-size: 12px; }}
</style></head><body><main><div style="letter-spacing:.3em;font-weight:600;color:#1F3B8A;font-size:13px">ARVA</div>
<h1>{L['title']} · {escape(project.name)}</h1>{body}<h2>{L['methods']}</h2>{methods}
<h2>{L['limitations']}</h2><ul>{lim}</ul></main></body></html>"""
