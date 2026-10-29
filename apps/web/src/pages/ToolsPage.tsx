import { useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, ExternalLink, Package, RefreshCw, XCircle } from "lucide-react";
import { useState } from "react";
import { useLibraries } from "@/components/domain/RawSignal";
import { DatabasesSection } from "@/components/tools/DatabasesSection";
import { useTools } from "@/components/tools/useTools";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody } from "@/components/ui/card";
import { ErrorNote, PageHeader, Skeleton } from "@/components/ui/misc";
import { useT, type TranslationKey } from "@/i18n";
import { api } from "@/lib/api";
import { toolDescription, toolMessage } from "@/lib/messages";
import type { Library, Tool } from "@/lib/types";

const STATUS: Record<Tool["status"], { label: TranslationKey; tone: "success" | "neutral" | "warning" | "danger" }> = {
  available: { label: "dashboard.available", tone: "success" },
  not_installed: { label: "tools.status.not_installed", tone: "neutral" },
  incompatible: { label: "tools.status.incompatible", tone: "warning" },
  failed: { label: "tools.status.failed", tone: "danger" },
};

const INSTALL_LABEL: Record<string, TranslationKey> = { conda: "tools.install.conda", apt: "tools.install.apt", conda_lock: "tools.install.condaLock" };

function installCommand(kind: string, pkg: string) {
  if (kind === "conda") return `mamba install -c conda-forge -c bioconda ${pkg.replace("bioconda::", "")}`;
  if (kind === "apt") return `sudo apt install ${pkg}`;
  return pkg;
}

export function ToolsPage() {
  const t = useT();
  const qc = useQueryClient();
  const tools = useTools();
  const libraries = useLibraries();
  const [refreshing, setRefreshing] = useState(false);

  const refresh = async () => {
    setRefreshing(true);
    try {
      qc.setQueryData(["tools"], await api.tools(true));
      qc.setQueryData(["libraries"], await api.libraries());
    } finally {
      setRefreshing(false);
    }
  };

  return (
    <div className="animate-fade-in space-y-6">
      <PageHeader
        title={t("nav.tools")}
        subtitle={t("tools.subtitle")}
        actions={
          <Button variant="outline" onClick={refresh} disabled={refreshing}>
            <RefreshCw className={refreshing ? "h-4 w-4 animate-spin" : "h-4 w-4"} /> {t("tools.redetect")}
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
      <section aria-labelledby="python-libraries" className="space-y-3">
        <div>
          <h2 id="python-libraries" className="flex items-center gap-2 text-base font-semibold">
            <Package className="h-4 w-4 text-arva-royal dark:text-arva-cyan" aria-hidden /> {t("libraries.title")}
          </h2>
          <p className="mt-0.5 text-sm text-muted-foreground">{t("libraries.subtitle")}</p>
        </div>
        <ErrorNote error={libraries.error} />
        {libraries.isLoading ? (
          <Skeleton className="h-40" />
        ) : (
          <div className="grid gap-4 lg:grid-cols-2">
            {libraries.data?.map((lib) => (
              <LibraryCard key={lib.id} lib={lib} />
            ))}
          </div>
        )}
      </section>
      <DatabasesSection />
      <p className="text-xs text-muted-foreground">
        {t("tools.pathNote1")} <code>ARVA_TOOLS_PATH</code>, {t("tools.pathNote2")} <code>ARVA_TOOL_&lt;ID&gt;</code> ({t("tools.pathNote3")}{" "}
        <code>ARVA_TOOL_FASTP=/opt/fastp/bin/fastp</code>). {t("tools.pathNote4")}
      </p>
    </div>
  );
}

function ToolCard({ tool }: { tool: Tool }) {
  const t = useT();
  const st = STATUS[tool.status];
  return (
    <Card className="flex flex-col">
      <div className="flex items-start justify-between gap-3 px-5 pt-5">
        <div>
          <h3 className="flex items-center gap-2 font-semibold">
            {tool.name}
            {tool.version && <span className="text-sm font-normal text-muted-foreground">v{tool.version}</span>}
          </h3>
          <p className="mt-1 text-sm text-muted-foreground">{toolDescription(t, tool)}</p>
        </div>
        <Badge tone={st.tone}>
          {tool.status === "available" ? <CheckCircle2 className="h-3 w-3" /> : tool.status === "not_installed" ? null : <XCircle className="h-3 w-3" />}
          {t(st.label)}
        </Badge>
      </div>
      <CardBody className="flex-1 space-y-3 pt-3 text-sm">
        {tool.status === "available" && !tool.version_validated && (
          <div className="flex gap-2 rounded-lg border border-warning/40 bg-warning/5 p-2.5 text-xs">
            <AlertTriangle className="h-4 w-4 shrink-0 text-warning" /> {toolMessage(t, tool)}
          </div>
        )}
        {tool.status !== "available" && tool.message && <p className="text-xs text-muted-foreground">{toolMessage(t, tool)}</p>}
        {tool.status === "available" && tool.version_validated && tool.reason && (
          <div className="flex gap-2 rounded-lg border border-warning/40 bg-warning/5 p-2.5 text-xs">
            <AlertTriangle className="h-4 w-4 shrink-0 text-warning" aria-hidden /> {toolMessage(t, tool)}
          </div>
        )}
        <dl className="grid grid-cols-[110px_1fr] gap-x-3 gap-y-1 text-xs">
          <dt className="text-muted-foreground">{t("tools.executable")}</dt>
          <dd className="break-all font-mono">{tool.path ?? "—"}</dd>
          <dt className="text-muted-foreground">{t("libraries.validatedWith")}</dt>
          <dd>
            {tool.tested_versions.join(", ")} ({t("tools.minVersion", { version: tool.min_version })})
          </dd>
          <dt className="text-muted-foreground">{t("libraries.licence")}</dt>
          <dd>{tool.license}</dd>
          <dt className="text-muted-foreground">{t("tools.io")}</dt>
          <dd>
            {tool.input_formats.join(", ")} → {tool.output_formats.join(", ")}
          </dd>
          <dt className="text-muted-foreground">{t("libraries.cite")}</dt>
          <dd>
            {tool.citation}{" "}
            <a href={tool.citation_url} target="_blank" rel="noreferrer noopener" className="inline-flex items-center gap-0.5 text-arva-royal hover:underline dark:text-arva-cyan">
              {t("libraries.link")} <ExternalLink className="h-3 w-3" />
            </a>
          </dd>
        </dl>
        {tool.status !== "available" && (
          <div className="space-y-1.5">
            <div className="text-xs font-medium">{t("tools.installYourself")}</div>
            {Object.entries(tool.install).map(([kind, pkg]) =>
              kind === "pip" ? (
                <div key={kind} className="text-xs">
                  <span className="text-muted-foreground">{t("tools.installPip")}: </span>
                  <code className="mt-1 block whitespace-pre-wrap break-all rounded bg-muted px-1.5 py-1">{pkg}</code>
                </div>
              ) : (
                <div key={kind} className="text-xs">
                  <span className="text-muted-foreground">{INSTALL_LABEL[kind] ? t(INSTALL_LABEL[kind]) : kind}: </span>
                  <code className="rounded bg-muted px-1.5 py-0.5">{installCommand(kind, pkg)}</code>
                </div>
              ),
            )}
          </div>
        )}
        <a href={tool.homepage} target="_blank" rel="noreferrer noopener" className="inline-flex items-center gap-1 text-xs text-arva-royal hover:underline dark:text-arva-cyan">
          {t("libraries.docs")} <ExternalLink className="h-3 w-3" />
        </a>
      </CardBody>
    </Card>
  );
}

const LIBRARY_TEXT: Record<string, { description: TranslationKey; platforms: TranslationKey }> = {
  pod5: { description: "libraries.pod5.description", platforms: "libraries.pod5.platforms" },
};

function LibraryCard({ lib }: { lib: Library }) {
  const t = useT();
  const text = LIBRARY_TEXT[lib.id];
  const installed = lib.status === "available";
  return (
    <Card className="flex flex-col">
      <div className="flex items-start justify-between gap-3 px-5 pt-5">
        <div className="min-w-0">
          <h3 className="flex flex-wrap items-center gap-2 font-semibold">
            {lib.name}
            {lib.version && <span className="text-sm font-normal text-muted-foreground">v{lib.version}</span>}
          </h3>
          {text && <p className="mt-1 text-sm text-muted-foreground">{t(text.description)}</p>}
        </div>
        <Badge tone={installed ? "success" : "neutral"}>
          {installed && <CheckCircle2 className="h-3 w-3" aria-hidden />}
          {installed ? t("libraries.available") : t("libraries.notInstalled")}
        </Badge>
      </div>
      <CardBody className="flex-1 space-y-3 pt-3 text-sm">
        {installed && !lib.version_validated && (
          <div className="flex gap-2 rounded-lg border border-warning/40 bg-warning/5 p-2.5 text-xs">
            <AlertTriangle className="h-4 w-4 shrink-0 text-warning" aria-hidden />
            {t("libraries.notValidated", { version: lib.version ?? "", required: lib.required_version })}
          </div>
        )}
        <dl className="grid grid-cols-[110px_1fr] gap-x-3 gap-y-1 text-xs">
          <dt className="text-muted-foreground">{t("libraries.available")}</dt>
          <dd>
            {lib.version
              ? [`${lib.name} ${lib.version}`, ...Object.entries(lib.companion_versions).filter(([, v]) => v).map(([name, v]) => `${name} ${v}`)].join(" · ")
              : "—"}
          </dd>
          <dt className="text-muted-foreground">{t("libraries.validatedWith")}</dt>
          <dd>{lib.required_version}</dd>
          <dt className="text-muted-foreground">{t("libraries.licence")}</dt>
          <dd>{lib.license}</dd>
          <dt className="text-muted-foreground">{t("libraries.cite")}</dt>
          <dd className="min-w-0 break-words">
            {lib.citation}{" "}
            <a href={lib.citation_url} target="_blank" rel="noreferrer noopener" className="inline-flex items-center gap-0.5 text-arva-royal hover:underline dark:text-arva-cyan">
              {t("libraries.link")} <ExternalLink className="h-3 w-3" aria-hidden />
            </a>
          </dd>
        </dl>
        <div className="space-y-1.5">
          <div className="text-xs font-medium">{t("libraries.install")}</div>
          <code className="block break-all rounded bg-muted px-1.5 py-0.5 text-xs">{lib.install}</code>
          {text && <p className="text-xs text-muted-foreground">{t(text.platforms)}</p>}
        </div>
        <a href={lib.homepage} target="_blank" rel="noreferrer noopener" className="inline-flex items-center gap-1 text-xs text-arva-royal hover:underline dark:text-arva-cyan">
          {t("libraries.docs")} <ExternalLink className="h-3 w-3" aria-hidden />
        </a>
      </CardBody>
    </Card>
  );
}
