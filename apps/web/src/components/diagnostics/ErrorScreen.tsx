import { AlertTriangle, RefreshCw, WifiOff } from "lucide-react";
import { Component, useEffect, useState, type ErrorInfo, type ReactNode } from "react";
import { useRouteError } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { useT } from "@/i18n";
import { localErrorDetails } from "@/lib/diagnostics";
import { reportException } from "@/lib/errorReporting";
import { isUnreachable } from "@/lib/unreachable";
import { CopyErrorDetails } from "./CopyErrorDetails";

/** The global error screen: the error is kept in ARVA's error log and its id shown, with the details to copy. When the
 * API gave no answer (Docker Desktop closed), it says so instead, with a button that loads the page again. */
export function ErrorScreen({ error, componentStack }: { error: unknown; componentStack?: string | null }) {
  const unreachable = isUnreachable(error);
  const t = useT();
  // undefined while the error is being recorded, null when the API could not record it.
  const [errorId, setErrorId] = useState<string | null | undefined>(undefined);
  useEffect(() => {
    // An API that does not answer cannot record the error either.
    if (unreachable) return;
    let live = true;
    void reportException("boundary", error, componentStack).then((id) => live && setErrorId(id));
    return () => {
      live = false;
    };
  }, [error, componentStack, unreachable]);
  if (unreachable) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background p-6">
        <div role="alert" className="max-w-lg space-y-4 rounded-xl border border-danger/30 bg-surface p-6 shadow-card">
          <h1 className="flex items-center gap-2 text-lg font-semibold">
            <WifiOff className="h-5 w-5 text-danger" aria-hidden /> {t("error.unreachable.title")}
          </h1>
          <p className="text-sm text-muted-foreground">{t("error.unreachable")}</p>
          <Button size="sm" onClick={() => window.location.reload()}>
            <RefreshCw className="h-3.5 w-3.5" aria-hidden /> {t("error.retry")}
          </Button>
        </div>
      </div>
    );
  }
  return (
    <div className="flex min-h-screen items-center justify-center bg-background p-6">
      <div role="alert" className="max-w-lg space-y-4 rounded-xl border border-danger/30 bg-surface p-6 shadow-card">
        <h1 className="flex items-center gap-2 text-lg font-semibold">
          <AlertTriangle className="h-5 w-5 text-danger" aria-hidden /> {t("error.screen.title")}
        </h1>
        <p className="text-sm text-muted-foreground">{t("error.screen.body")}</p>
        {errorId && <p className="font-mono text-xs">{t("error.id", { id: errorId })}</p>}
        {errorId === null && <p className="text-xs text-amber-700 dark:text-warning">{t("error.screen.notRecorded")}</p>}
        <div className="flex flex-wrap items-center gap-2">
          <CopyErrorDetails errorId={errorId ?? undefined} fallback={() => localErrorDetails(error)} />
          <Button size="sm" onClick={() => window.location.reload()}>
            {t("error.screen.reload")}
          </Button>
        </div>
      </div>
    </div>
  );
}

export function RouteErrorScreen() {
  return <ErrorScreen error={useRouteError()} />;
}

/** Errors outside the router's pages (the router catches those in its routes). */
export class ErrorBoundary extends Component<{ children: ReactNode }, { error: unknown; stack: string | null }> {
  state = { error: null as unknown, stack: null as string | null };

  static getDerivedStateFromError(error: unknown) {
    return { error };
  }

  componentDidCatch(_: unknown, info: ErrorInfo) {
    this.setState({ stack: info.componentStack ?? null });
  }

  render() {
    return this.state.error ? <ErrorScreen error={this.state.error} componentStack={this.state.stack} /> : this.props.children;
  }
}
