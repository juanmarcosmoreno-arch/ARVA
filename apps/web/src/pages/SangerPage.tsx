import { useQuery } from "@tanstack/react-query";
import { Activity } from "lucide-react";
import { Link } from "react-router-dom";
import { Explain } from "@/components/guide/Explain";
import { Card, CardBody } from "@/components/ui/card";
import { EmptyState, ErrorNote, PageHeader, Skeleton } from "@/components/ui/misc";
import { useT } from "@/i18n";
import { api } from "@/lib/api";
import { SamplesTable } from "./SamplesPage";

/** Sanger reads of single genes: they belong to the sample (strain) they were amplified from, so the area starts
 * from the samples; each sample's Sanger tab holds its reads, consensus, identifications and results. */
export function SangerPage() {
  const t = useT();
  const { data, isLoading, error } = useQuery({ queryKey: ["samples", "all"], queryFn: api.allSamples });
  return (
    <div className="animate-fade-in space-y-4">
      <PageHeader title={t("sanger.page.title")} subtitle={t("sanger.page.subtitle")} actions={<><Explain id="sanger_reads" /><Explain id="sanger_16s" titled /></>} />
      <Card>
        <CardBody className="space-y-2 text-sm">
          <ol className="ml-5 list-decimal space-y-1 text-muted-foreground">
            <li>{t("sanger.page.step1")}</li>
            <li>{t("sanger.page.step2")}</li>
            <li>{t("sanger.page.step3")}</li>
            <li>{t("sanger.page.step4")}</li>
          </ol>
          <p className="text-xs text-muted-foreground">{t("sanger.page.local")}</p>
        </CardBody>
      </Card>
      <ErrorNote error={error} />
      <Card>
        {isLoading ? (
          <Skeleton className="m-5 h-24" />
        ) : data?.length === 0 ? (
          <div className="p-5">
            <EmptyState icon={<Activity className="h-7 w-7" />} title={t("samples.noneYet")}>
              {t("sanger.page.noSamples")}{" "}
              <Link to="/projects" className="text-arva-royal underline dark:text-arva-cyan">
                {t("samples.goToProjects")}
              </Link>
            </EmptyState>
          </div>
        ) : (
          <SamplesTable samples={data ?? []} tab="sanger" />
        )}
      </Card>
    </div>
  );
}
