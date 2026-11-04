import { useQuery } from "@tanstack/react-query";
import { ChevronRight, Dna, ShieldCheck } from "lucide-react";
import { useState } from "react";
import { Explain } from "@/components/guide/Explain";
import { Badge } from "@/components/ui/badge";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { ErrorNote, Skeleton } from "@/components/ui/misc";
import { useT } from "@/i18n";
import { api } from "@/lib/api";
import { fmtDate, fmtInt } from "@/lib/format";
import { hitName, type GenomeBrief, type IdentificationBrief } from "@/lib/sanger";
import { cn } from "@/lib/utils";
import { ConsensusBuilder } from "./ConsensusBuilder";
import { IdentificationView } from "./IdentificationView";
import { pct } from "./SangerResults";
import { SangerReads } from "./SangerReads";

/** Sanger reads of single genes of this sample (the strain they were amplified from): upload and review the reads,
 * build the consensus, say what you suspect, search every local source and read the results next to this sample's
 * genome, when it has one in ARVA. */
export function SangerTab({ sampleId }: { sampleId: string }) {
  const t = useT();
  const overview = useQuery({
    queryKey: ["sanger", sampleId],
    queryFn: () => api.sangerOverview(sampleId),
    refetchInterval: (q) => (q.state.data?.identifications.some((i) => i.running > 0) ? 3000 : false),
  });
  const [selected, setSelected] = useState<string | null>(null);
  const o = overview.data;
  if (overview.error) return <ErrorNote error={overview.error} />;
  if (!o) return <Skeleton className="h-64" />;
  return (
    <div className="space-y-4">
      <p className="flex items-start gap-2 rounded-lg border border-arva-teal/30 bg-arva-teal/5 px-3 py-2 text-xs">
        <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-arva-teal" aria-hidden />
        <span>
          {t("sanger.tab.intro")} <Explain id="sanger_reads" titled className="ml-1" />
        </span>
      </p>
      <GenomesNote genomes={o.genomes} />
      <SangerReads sampleId={sampleId} overview={o} />
      <ConsensusBuilder sampleId={sampleId} overview={o} onCreated={(r) => setSelected(r.identification.id)} />
      {o.identifications.length > 0 && (
        <Card>
          <CardHeader title={t("sanger.idents.title", { n: o.identifications.length })} description={t("sanger.idents.subtitle")} />
          <CardBody className="pt-3">
            <ul className="space-y-1.5">
              {o.identifications.map((i) => (
                <IdentRow key={i.id} ident={i} selected={i.id === selected} onSelect={() => setSelected(i.id === selected ? null : i.id)} />
              ))}
            </ul>
          </CardBody>
        </Card>
      )}
      {selected && <IdentificationView key={selected} id={selected} onDeleted={() => setSelected(null)} />}
    </div>
  );
}

function GenomesNote({ genomes }: { genomes: GenomeBrief[] }) {
  const t = useT();
  if (genomes.length === 0) return <p className="text-xs text-muted-foreground">{t("sanger.tab.noGenome")}</p>;
  const g = genomes[0];
  return (
    <p className="flex items-center gap-2 text-xs text-muted-foreground">
      <Dna className="h-3.5 w-3.5" aria-hidden />
      {t("sanger.tab.genome", { assembler: `${g.assembler} ${g.assembler_version}`, date: fmtDate(g.created_at), annotation: g.annotation ? `${g.annotation.tool} ${g.annotation.tool_version}` : t("sanger.tab.notAnnotated") })}
    </p>
  );
}

function IdentRow({ ident, selected, onSelect }: { ident: IdentificationBrief; selected: boolean; onSelect: () => void }) {
  const t = useT();
  return (
    <li>
      <button type="button" onClick={onSelect} aria-expanded={selected} className={cn("flex w-full flex-wrap items-center gap-2 rounded-lg border px-3 py-2 text-left text-xs hover:bg-muted/40", selected && "border-arva-teal bg-arva-teal/5")}>
        <span className="font-medium">{ident.label}</span>
        <Badge>{t(`sanger.mode.${ident.mode}` as const)}</Badge>
        <span className="text-muted-foreground">{t("sanger.idents.length", { n: fmtInt(ident.length) })}</span>
        {ident.suspected && <Badge tone="blue">{t("sanger.idents.suspected", { value: ident.suspected.value })}</Badge>}
        {ident.running > 0 && <Badge tone="blue">{t("sanger.idents.running", { n: ident.running })}</Badge>}
        {ident.reading_16s && (
          <Badge tone={ident.reading_16s.level === "species" ? "success" : ident.reading_16s.level === "genus" ? "teal" : "warning"}>
            {t(`sanger.idents.reading16s.${ident.reading_16s.level}` as const, { name: ident.reading_16s.species ?? ident.reading_16s.genus ?? "", n: ident.reading_16s.within_separation })}
          </Badge>
        )}
        {ident.best ? (
          <span>
            {t("sanger.idents.best", { name: hitName(ident.best) ?? t("sanger.ranked.unnamed"), identity: pct(ident.best.identity), coverage: pct(ident.best.query_coverage) })}
            {ident.best_tied_names > 1 && <span className="text-amber-700 dark:text-warning"> · {t("sanger.idents.tied", { n: ident.best_tied_names - 1 })}</span>}
          </span>
        ) : (
          <span className="text-muted-foreground">{ident.searched.length ? t("sanger.ranked.none") : t("sanger.idents.notSearched")}</span>
        )}
        <ChevronRight className={cn("ml-auto h-4 w-4 text-muted-foreground transition-transform", selected && "rotate-90")} aria-hidden />
      </button>
    </li>
  );
}
