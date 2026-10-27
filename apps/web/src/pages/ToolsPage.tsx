import { useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, Database, ExternalLink, RefreshCw, XCircle } from "lucide-react";
import { useState } from "react";
import { useTools } from "@/components/tools/useTools";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { ErrorNote, PageHeader, Skeleton } from "@/components/ui/misc";
import { useT } from "@/i18n";
import { api } from "@/lib/api";
import type { Tool } from "@/lib/types";

const STATUS: Record<Tool["status"], { label: string; tone: "success" | "neutral" | "warning" | "danger" }> = {
  available: { label: "Available", tone: "success" },
  not_installed: { label: "Not installed", tone: "neutral" },
  incompatible: { label: "Incompatible version", tone: "warning" },
  failed: { label: "Detection failed", tone: "danger" },
};

const INSTALL_LABEL: Record<string, string> = { conda: "Conda / Bioconda (macOS & Linux)", apt: "Debian / Ubuntu" };

function installCommand(kind: string, pkg: string) {
  if (kind === "conda") return `mamba install -c conda-forge -c bioconda ${pkg.replace("bioconda::", "")}`;
  if (kind === "apt") return `sudo apt install ${pkg}`;
  return pkg;
}

export function ToolsPage() {
  const t = useT();
  const qc = useQueryClient();
  const tools = useTools();
  const [refreshing, setRefreshing] = useState(false);

  const refresh = async () => {
    setRefreshing(true);
    try {
      qc.setQueryData(["tools"], await api.tools(true));
    } finally {
      setRefreshing(false);
    }
  };

  return (
    <div className="animate-fade-in space-y-6">
      <PageHeader
        title={t("nav.tools")}
        subtitle="External tools ARVA can run. ARVA detects them but never installs anything by itself."
        actions={
          <Button variant="outline" onClick={refresh} disabled={refreshing}>
            <RefreshCw className={refreshing ? "h-4 w-4 animate-spin" : "h-4 w-4"} /> Re-detect
          </Button>
        }
      />
      <ErrorNote error={tools.error} />
      {tools.isLoading ? (
        <Skeleton className="h-64" />
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          {tools.data?.map((tool) => (
            <ToolCard key={tool.id} tool={tool} />
          ))}
        </div>
      )}
      <Card>
        <CardHeader
          title={
            <span className="flex items-center gap-2">
              <Database className="h-4 w-4 text-arva-royal dark:text-arva-cyan" /> Reference databases
            </span>
          }
          description="Planned (Phase 5): CARD, VFDB, PubMLST schemes, GTDB, Bakta databases… Size, licence and disk space will always be shown before any download."
        />
        <CardBody className="pt-2 text-sm text-muted-foreground">No databases are needed by the analyses available today.</CardBody>
      </Card>
      <p className="text-xs text-muted-foreground">
        Tools are found on the system PATH, in folders listed in <code>ARVA_TOOLS_PATH</code>, or at an explicit path given by{" "}
        <code>ARVA_TOOL_&lt;ID&gt;</code> (e.g. <code>ARVA_TOOL_FASTP=/opt/fastp/bin/fastp</code>). Results already produced are never affected by
        installing a different version: every analysis records the version it used.
      </p>
    </div>
  );
}

function ToolCard({ tool }: { tool: Tool }) {
  const st = STATUS[tool.status];
  return (
    <Card className="flex flex-col">
      <div className="flex items-start justify-between gap-3 px-5 pt-5">
        <div>
          <h3 className="flex items-center gap-2 font-semibold">
            {tool.name}
            {tool.version && <span className="text-sm font-normal text-muted-foreground">v{tool.version}</span>}
          </h3>
          <p className="mt-1 text-sm text-muted-foreground">{tool.description}</p>
        </div>
        <Badge tone={st.tone}>
          {tool.status === "available" ? <CheckCircle2 className="h-3 w-3" /> : tool.status === "not_installed" ? null : <XCircle className="h-3 w-3" />}
          {st.label}
        </Badge>
      </div>
      <CardBody className="flex-1 space-y-3 pt-3 text-sm">
        {tool.status === "available" && !tool.version_validated && (
          <div className="flex gap-2 rounded-lg border border-warning/40 bg-warning/5 p-2.5 text-xs">
            <AlertTriangle className="h-4 w-4 shrink-0 text-warning" /> {tool.message}
          </div>
        )}
        {tool.status !== "available" && tool.message && <p className="text-xs text-muted-foreground">{tool.message}</p>}
        <dl className="grid grid-cols-[110px_1fr] gap-x-3 gap-y-1 text-xs">
          <dt className="text-muted-foreground">Executable</dt>
          <dd className="break-all font-mono">{tool.path ?? "—"}</dd>
          <dt className="text-muted-foreground">Validated with</dt>
          <dd>{tool.tested_versions.join(", ")} (min. {tool.min_version})</dd>
          <dt className="text-muted-foreground">Licence</dt>
          <dd>{tool.license}</dd>
          <dt className="text-muted-foreground">Input / output</dt>
          <dd>
            {tool.input_formats.join(", ")} → {tool.output_formats.join(", ")}
          </dd>
          <dt className="text-muted-foreground">Cite</dt>
          <dd>
            {tool.citation}{" "}
            <a href={tool.citation_url} target="_blank" rel="noreferrer noopener" className="inline-flex items-center gap-0.5 text-arva-royal hover:underline dark:text-arva-cyan">
              link <ExternalLink className="h-3 w-3" />
            </a>
          </dd>
        </dl>
        {tool.status !== "available" && (
          <div className="space-y-1.5">
            <div className="text-xs font-medium">Install (run it yourself):</div>
            {Object.entries(tool.install).map(([kind, pkg]) => (
              <div key={kind} className="text-xs">
                <span className="text-muted-foreground">{INSTALL_LABEL[kind] ?? kind}: </span>
                <code className="rounded bg-muted px-1.5 py-0.5">{installCommand(kind, pkg)}</code>
              </div>
            ))}
          </div>
        )}
        <a href={tool.homepage} target="_blank" rel="noreferrer noopener" className="inline-flex items-center gap-1 text-xs text-arva-royal hover:underline dark:text-arva-cyan">
          Official documentation <ExternalLink className="h-3 w-3" />
        </a>
      </CardBody>
    </Card>
  );
}
