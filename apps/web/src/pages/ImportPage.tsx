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

const FORMATS: { name: string; status: string; note?: string; noteKey?: TranslationKey }[] = [
  { name: "FASTQ / FASTQ.gz", status: "Supported", note: "Illumina, Nanopore, PacBio reads (Phred+33)" },
  { name: "FASTA / FASTA.gz", status: "Supported", note: "Nucleotide sequences (e.g. assemblies, references)" },
  { name: "POD5", status: "Supported", noteKey: "import.formatPod5" },
  { name: "BAM / CRAM / SAM", status: "Planned", note: "Alignments; needs samtools-based import" },
  { name: "GFF3 / GTF / GenBank / EMBL", status: "Planned", note: "Annotations (Phase 4)" },
  { name: "VCF / BED / Newick", status: "Planned", note: "Variants, intervals and trees (Phases 7–8)" },
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
      <PageHeader title={t("nav.import")} subtitle="Register raw sequencing files against a sample. Files are checksummed, validated and stored read-only." />
      <div className="grid gap-6 lg:grid-cols-3">
        <div className="min-w-0 space-y-6 lg:col-span-2">
          <Card>
            <CardHeader title="1 · Choose destination" description="Every file belongs to exactly one sample." />
            <CardBody className="space-y-4">
              <div className="grid gap-4 sm:grid-cols-2">
                <Field label="Project">
                  <Select
                    value={projectId}
                    onChange={(e) => {
                      setProjectId(e.target.value);
                      setSampleId("");
                    }}
                  >
                    <option value="">Select a project…</option>
                    {projects.data?.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.name}
                      </option>
                    ))}
                  </Select>
                </Field>
                <Field label="Sample">
                  <Select value={sampleId} onChange={(e) => setSampleId(e.target.value)} disabled={!projectId}>
                    <option value="">{projectId && samples.data?.length === 0 ? "No samples — create one first" : "Select a sample…"}</option>
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
                  No projects yet. <Link className="text-arva-royal underline dark:text-arva-cyan" to="/projects">Create a project</Link> and a sample first.
                </p>
              )}
              {projectId && samples.data?.length === 0 && (
                <p className="text-sm text-muted-foreground">
                  <Link className="text-arva-royal underline dark:text-arva-cyan" to={`/projects/${projectId}`}>Open the project</Link> to create a sample.
                </p>
              )}
              <div>
                <h3 className="mb-2 text-sm font-semibold">2 · Add files</h3>
                {sampleId ? (
                  <FileDropzone sampleId={sampleId} onUploaded={setLast} />
                ) : (
                  <div className="rounded-xl border-2 border-dashed px-6 py-10 text-center text-sm text-muted-foreground">Select a sample to enable upload</div>
                )}
              </div>
              {sampleId && last && last.files.length > 0 && (
                <div className="flex justify-end">
                  <Link to={`/samples/${sampleId}?tab=qc`}>
                    <Button>
                      Continue to read statistics <ArrowRight className="h-4 w-4" />
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
            <CardHeader title="Supported formats" description="Formats are added progressively; nothing is converted silently." />
            <CardBody>
              <ul className="space-y-3 text-sm">
                {FORMATS.map((f) => (
                  <li key={f.name}>
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-medium">{f.name}</span>
                      <span className={f.status === "Supported" ? "text-xs text-success" : "text-xs text-muted-foreground"}>{f.status}</span>
                    </div>
                    <div className="text-xs text-muted-foreground">{f.noteKey ? t(f.noteKey) : f.note}</div>
                  </li>
                ))}
              </ul>
              <div className="mt-5 flex gap-2 rounded-lg bg-muted p-3 text-xs text-muted-foreground">
                <Info className="mt-0.5 h-4 w-4 shrink-0" />
                <span>
                  Compression is detected from file content. Paired-end mates are recognised from names such as <code>_R1_001</code> /{" "}
                  <code>_2.fq.gz</code>. Identical files are rejected as duplicates within a sample; identical content already in another
                  sample of the project is accepted with a note.
                </span>
              </div>
            </CardBody>
          </Card>
        </div>
      </div>
    </div>
  );
}
