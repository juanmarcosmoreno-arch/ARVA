import { AlertTriangle, RefreshCw, X } from "lucide-react";
import { CopyErrorDetails } from "@/components/diagnostics/CopyErrorDetails";
import { Button } from "@/components/ui/button";
import { useT } from "@/i18n";
import { useRetryQueries } from "@/lib/unreachable";
import { useToasts } from "@/store/toasts";

export function Toaster() {
  const t = useT();
  const { toasts, dismiss } = useToasts();
  const retry = useRetryQueries();
  if (!toasts.length) return null;
  return (
    <div className="fixed bottom-4 right-4 z-50 flex w-[min(28rem,calc(100vw-2rem))] flex-col gap-2" aria-live="polite">
      {toasts.map((toast) => (
        <div key={toast.id} role="alert" className="rounded-xl border border-danger/30 bg-surface p-3 text-sm shadow-card">
          <div className="flex items-start gap-2">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-danger" aria-hidden />
            <div className="min-w-0 flex-1 space-y-2">
              <p>{toast.kind === "unreachable" ? t("error.unreachable") : toast.message}</p>
              {toast.kind === "unreachable" && (
                <Button size="sm" variant="outline" onClick={retry}>
                  <RefreshCw className="h-3.5 w-3.5" aria-hidden /> {t("error.retry")}
                </Button>
              )}
              {toast.errorId && (
                <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                  <span className="font-mono">{t("error.id", { id: toast.errorId })}</span>
                  <CopyErrorDetails errorId={toast.errorId} />
                </div>
              )}
            </div>
            <button className="rounded p-1 hover:bg-muted" onClick={() => dismiss(toast.id)} aria-label={t("common.close")}>
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}
