import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Explain } from "@/components/guide/Explain";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { ErrorNote } from "@/components/ui/misc";
import { useT } from "@/i18n";
import { api } from "@/lib/api";
import { fmtInt } from "@/lib/format";
import { MOBILE_METHODS } from "@/lib/mobile";
import type { MobileProjectOverview } from "@/lib/types";

const TH = "px-2 py-1.5 text-left font-medium text-muted-foreground whitespace-nowrap";
const TD = "px-2 py-1.5 align-top";

type Row = MobileProjectOverview["samples"][number];

const num = (v: unknown) => (typeof v === "number" ? v : 0);

/** Per sample, the most recent run of each plasmid and mobile-element method with its counts, the replicon types,
 * and the virulence genes VFDB and AMRFinderPlus found (each source apart); an empty cell means not searched. */
export function ProjectMobile({ projectId }: { projectId: string }) {
  const t = useT();
  const overview = useQuery({ queryKey: ["projectMobile", projectId], queryFn: () => api.mobileProject(projectId) });
  if (overview.error) return <ErrorNote error={overview.error} />;
  const o = overview.data;
  if (!o) return null;
  const anyVirulence = o.samples.some((s) => s.virulence.vfdb != null);
  if (!MOBILE_METHODS.some((m) => o.searched[m] > 0) && !anyVirulence) return null;
  const ns = t("mobile.notSearchedShort");
  const cell = (s: Row, render: (counts: Record<string, unknown>) => string, method: keyof Row["methods"]) => {
    const run = s.methods[method];
    return run ? render(run.counts as Record<string, unknown>) : ns;
  };
  return (
    <Card className="mt-6 min-w-0" id="project-mobile">
      <CardHeader title={t("projectMobile.title", { total: o.samples.length })} description={t("projectMobile.subtitle")} action={<Explain id="mobile_element" compact />} />
      <CardBody className="pt-3">
        <div className="overflow-x-auto rounded-lg border">
          <table className="w-full text-xs">
            <thead className="bg-muted/50">
              <tr>
                <th className={TH}>{t("projectMlst.sample")}</th>
                <th className={TH}>{t("projectMobile.plasmids")}</th>
                <th className={TH}>{t("projectMobile.replicons")}</th>
                <th className={TH}>{t("projectMobile.integrons")}</th>
                <th className={TH}>{t("projectMobile.is")}</th>
                <th className={TH}>{t("projectMobile.viruses")}</th>
                <th className={TH}>{t("projectMobile.vfdb")}</th>
                <th className={TH}>{t("projectMobile.amrVirulence")}</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {o.samples.map((s) => (
                <tr key={s.sample_id}>
                  <td className={TD}>
                    <Link to={`/samples/${s.sample_id}?tab=genomic`} className="font-medium text-arva-royal hover:underline dark:text-arva-cyan">
                      {s.sample_code}
                    </Link>
                  </td>
                  <td className={TD}>{cell(s, (c) => t("projectMobile.plasmidsCell", { plasmids: fmtInt(num(c.plasmids)), contigs: fmtInt(num(c.plasmid_contigs)) }), "mobsuite")}</td>
                  <td className={TD}>{s.methods.plasmidfinder ? s.replicon_types.join(", ") || t("mobile.noneFound") : ns}</td>
                  <td className={TD}>{cell(s, (c) => fmtInt(num(c.integrons)), "integronfinder")}</td>
                  <td className={TD}>{cell(s, (c) => fmtInt(num(c.elements)), "isescan")}</td>
                  <td className={TD}>{cell(s, (c) => t("projectMobile.virusesCell", { viruses: fmtInt(num(c.viruses)), proviruses: fmtInt(num(c.proviruses)) }), "genomad")}</td>
                  <td className={TD}>{s.virulence.vfdb == null ? ns : fmtInt(s.virulence.vfdb)}</td>
                  <td className={TD}>{s.virulence.amrfinderplus == null ? ns : fmtInt(s.virulence.amrfinderplus)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CardBody>
    </Card>
  );
}
