import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Info } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { FileDropzone } from "@/components/domain/FileDropzone";
import { ServerImportCard } from "@/components/domain/ServerImportCard";
import { StorageCard } from "@/components/domain/StorageCard";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Field, Select } from "@/components/ui/form";
import { PageHeader } from "@/components/ui/misc";
import { useT, type TranslationKey } from "@/i18n";
import { api } from "@/lib/api";
import type { UploadResult } from "@/lib/types";

const FORMATS: { name: string; supported: boolean; note: TranslationKey }[] = [
  { name: "FASTQ / FASTQ.gz", supported: true, note: "import.format.fastq" },
  { name: "FASTA / FASTA.gz", supported: true, note: "import.format.fasta" },
  { name: "POD5", supported: true, note: "import.formatPod5" },
  { name: "BAM / CRAM / SAM", supported: false, note: "import.format.bam" },
  { name: "GFF3 / GTF / GenBank / EMBL", supported: false, note: "import.format.gff" },
  { name: "VCF / BED / Newick", supported: false, note: "import.format.vcf" },
];

export function ImportPage() {
  const t = useT();
  const [projectId, setProjectId] = useState("");
  const [sampleId, setSampleId] = useState("");
  const [last, setLast] = useState<UploadResult | null>(null);
  const projects = useQuery({ queryKey: ["projects"], queryFn: api.projects });
  const samples = useQuery({ queryKey: ["samples", projectId], queryFn: () => api.samples(projectId), enabled: !!projectId });
  const sampleCode = samples.data?.find((s) => s.id === sampleId)?.sample_code;

  return (
    <div className="animate-fade-in">
      <PageHeader title={t("nav.import")} subtitle={t("import.subtitle")} />
      <div className="grid gap-6 lg:grid-cols-3">
        <div className="min-w-0 space-y-6 lg:col-span-2">
          <Card>
            <CardHeader title={t("import.step1")} description={t("import.step1Hint")} />
            <CardBody className="space-y-4">
              <div className="grid gap-4 sm:grid-cols-2">
                <Field label={t("samples.col.project")}>
                  <Select
                    value={projectId}
                    onChange={(e) => {
                      setProjectId(e.target.value);
                      setSampleId("");
                    }}
                  >
                    <option value="">{t("import.selectProject")}</option>
                    {projects.data?.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.name}
                      </option>
                    ))}
                  </Select>
                </Field>
                <Field label={t("import.sample")}>
                  <Select value={sampleId} onChange={(e) => setSampleId(e.target.value)} disabled={!projectId}>
                    <option value="">{projectId && samples.data?.length === 0 ? t("import.noSamples") : t("import.selectSample")}</option>
                    {samples.data?.map((s) => (
                      <option key={s.id} value={s.id}>
                        {s.sample_code}
                        {s.organism ? ` · ${s.organism}` : ""}
                      </option>
                    ))}
                  </Select>
                </Field>
              </div>
              {projects.data?.length === 0 && (
                <p className="text-sm text-muted-foreground">
                  {t("import.noProjects")}{" "}
                  <Link className="text-arva-royal underline dark:text-arva-cyan" to="/projects">
                    {t("import.createProject")}
                  </Link>{" "}
                  {t("import.andSampleFirst")}
                </p>
              )}
              {projectId && samples.data?.length === 0 && (
                <p className="text-sm text-muted-foreground">
                  <Link className="text-arva-royal underline dark:text-arva-cyan" to={`/projects/${projectId}`}>
                    {t("import.openProject")}
                  </Link>{" "}
                  {t("import.toCreateSample")}
                </p>
              )}
              <div>
                <h3 className="mb-2 text-sm font-semibold">{t("import.step2")}</h3>
                {sampleId ? (
                  <FileDropzone sampleId={sampleId} onUploaded={setLast} />
                ) : (
                  <div className="rounded-xl border-2 border-dashed px-6 py-10 text-center text-sm text-muted-foreground">{t("import.selectToUpload")}</div>
                )}
              </div>
              {sampleId && last && last.files.length > 0 && (
                <div className="flex justify-end">
                  <Link to={`/samples/${sampleId}?tab=qc`}>
                    <Button>
                      {t("import.continue")} <ArrowRight className="h-4 w-4" />
                    </Button>
                  </Link>
                </div>
              )}
            </CardBody>
          </Card>
          <ServerImportCard sampleId={sampleId} sampleCode={sampleCode} />
        </div>

        <div className="min-w-0 space-y-6">
          <StorageCard />
          <Card>
            <CardHeader title={t("import.formats")} description={t("import.formatsHint")} />
            <CardBody>
              <ul className="space-y-3 text-sm">
                {FORMATS.map((f) => (
                  <li key={f.name}>
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-medium">{f.name}</span>
                      <span className={f.supported ? "text-xs text-success" : "text-xs text-muted-foreground"}>{f.supported ? t("import.supported") : t("common.planned")}</span>
                    </div>
                    <div className="text-xs text-muted-foreground">{t(f.note)}</div>
                  </li>
                ))}
              </ul>
              <div className="mt-5 flex gap-2 rounded-lg bg-muted p-3 text-xs text-muted-foreground">
                <Info className="mt-0.5 h-4 w-4 shrink-0" />
                <span>
                  {t("import.note.mates")} <code>_R1_001</code> / <code>_2.fq.gz</code>. {t("import.note.duplicates")}
                </span>
              </div>
            </CardBody>
          </Card>
        </div>
      </div>
    </div>
  );
}
