import { Check, ClipboardCopy } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { useT } from "@/i18n";
import { copyFetched, fetchReport, reportUrl } from "@/lib/diagnostics";
import { cn } from "@/lib/utils";
import { useSettings } from "@/store/settings";

/** Copies the diagnostic report scoped to a job or an error id (Markdown, ready to paste into a chat), with names
 * anonymised when Settings → Diagnostics says so. `fallback` is copied when the API cannot build the report. */
export function CopyErrorDetails({ jobId, errorId, fallback, className }: { jobId?: string; errorId?: string; fallback?: () => string; className?: string }) {
  const t = useT();
  const anonymise = useSettings((s) => s.diagnosticsAnonymise);
  const [state, setState] = useState<"idle" | "busy" | "copied" | "failed">("idle");
  const [problem, setProblem] = useState("");

  async function copy() {
    // The clipboard write must start while the click is handled (WebKit), so it is started before anything is awaited.
    const copying = copyFetched(async () => {
      try {
        return await fetchReport({ anonymise, jobId, errorId });
      } catch (err) {
        if (!fallback) throw err;
        return fallback();
      }
    });
    setState("busy");
    try {
      await copying;
      setState("copied");
      window.setTimeout(() => setState("idle"), 2500);
    } catch (err) {
      setProblem(err instanceof Error ? err.message : String(err));
      setState("failed");
    }
  }

  return (
    <span className={cn("inline-flex flex-wrap items-center gap-2", className)}>
      <Button variant="outline" size="sm" onClick={copy} disabled={state === "busy"}>
        {state === "copied" ? <Check className="h-3.5 w-3.5 text-success" aria-hidden /> : <ClipboardCopy className="h-3.5 w-3.5" aria-hidden />}
        {state === "copied" ? t("error.copied") : t("error.copyDetails")}
      </Button>
      {state === "failed" && (
        <span role="alert" className="text-xs text-danger">
          {t("diagnostics.copyFailed", { error: problem })}{" "}
          {(jobId || errorId) && (
            <a className="font-medium underline" href={reportUrl({ anonymise, jobId, errorId, format: "markdown" })} download>
              {t("diagnostics.downloadInstead")}
            </a>
          )}
        </span>
      )}
    </span>
  );
}
