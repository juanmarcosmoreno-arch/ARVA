import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Download, Loader2 } from "lucide-react";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Select } from "@/components/ui/form";
import { ErrorNote } from "@/components/ui/misc";
import { type TranslationKey, useT } from "@/i18n";
import { api } from "@/lib/api";
import { fmtBytes, fmtInt } from "@/lib/format";

const CHECK = "mt-0.5 h-4 w-4 shrink-0 accent-[#00B4A6]";

/** Lists the dated AMRFinderPlus database releases NCBI publishes for the installed AMRFinderPlus, shows what one
 * would fetch (files and sizes from NCBI's listing, no published checksums) and where it goes, and downloads and
 * indexes it after an explicit confirmation. ARVA never fetches "latest". */
export function AmrReleaseDialog({ onClose }: { onClose: () => void }) {
  const t = useT();
  const queryClient = useQueryClient();
  const releases = useQuery({ queryKey: ["amrReleases"], queryFn: api.amrReleases, retry: false });
  const [version, setVersion] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  useEffect(() => {
    const first = releases.data?.releases.find((r) => r.compatibility === "compatible");
    if (first && !version) setVersion(first.version);
  }, [releases.data, version]);
  const plan = useQuery({ queryKey: ["amrReleasePlan", version], queryFn: () => api.amrReleasePlan(version), enabled: Boolean(version), retry: false });
  const p = plan.data;
  const start = useMutation({
    mutationFn: () => api.amrReleaseDownload(version, p?.download_bytes ?? 0),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["databases"] });
      onClose();
    },
  });
  const blocked = !p || p.missing.length > 0 || Boolean(p.blocked_by) || !p.enough || p.compatibility !== "compatible";
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()} title={t("amrRelease.title")} description={t("amrRelease.description")} className="max-w-2xl">
      <div className="space-y-4 text-sm">
        <ErrorNote error={releases.error} />
        {releases.data && (
          <label className="block space-y-1 text-xs">
            <span className="text-muted-foreground">{t("amrRelease.choose", { minor: releases.data.minor, version: releases.data.tool_version })}</span>
            <Select
              value={version}
              onChange={(e) => {
                setVersion(e.target.value);
                setConfirmed(false);
              }}
            >
              {releases.data.releases.map((r) => (
                <option key={r.version} value={r.version} disabled={r.compatibility !== "compatible"}>
                  {r.version} · {r.modified}
                  {r.compatibility !== "compatible" ? ` · ${t(`amrRelease.compat.${r.compatibility === "data_too_old" ? "data_too_old" : "other"}` as TranslationKey)}` : ""}
                </option>
              ))}
            </Select>
          </label>
        )}
        {plan.isFetching && <p className="text-xs text-muted-foreground">{t("mlst.checking")}</p>}
        <ErrorNote error={plan.error} />
        {p && (
          <div className="space-y-2 text-xs">
            <p>{t("amrRelease.files", { n: fmtInt(p.files.length), size: fmtBytes(p.download_bytes), url: p.url })}</p>
            <details>
              <summary className="cursor-pointer text-muted-foreground">{t("amrRelease.fileList")}</summary>
              <ul className="mt-1 max-h-40 overflow-y-auto font-mono text-[11px]">
                {p.files.map((f) => (
                  <li key={f.name}>
                    {f.name} · {f.approx_bytes != null ? fmtBytes(f.approx_bytes) : "?"}
                  </li>
                ))}
              </ul>
            </details>
            <p>{t("amrRelease.target", { path: p.host_target_path, required: fmtBytes(p.required_bytes), available: fmtBytes(p.available_bytes) })}</p>
            <p className="text-muted-foreground">{t("amrRelease.index", { command: p.index_command })}</p>
            <p className="flex gap-1.5 text-amber-700 dark:text-warning">
              <AlertTriangle className="h-3.5 w-3.5 shrink-0" aria-hidden /> {t("amrRelease.noChecksums")}
            </p>
            <p className="text-muted-foreground">{t("amrRelease.licence", { licence: p.licence })}</p>
            {p.missing.length > 0 && <p className="text-danger">{t("amrRelease.missing", { files: p.missing.join(", ") })}</p>}
            {p.blocked_by && <p className="text-danger">{p.blocked_by}</p>}
            {!p.enough && <p className="text-danger">{t("amrRelease.noSpace")}</p>}
          </div>
        )}
        <label className="flex items-start gap-2 text-xs">
          <input type="checkbox" className={CHECK} checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} disabled={!p} />
          <span>{t("amrRelease.confirm", { size: p ? fmtBytes(p.download_bytes) : "?" })}</span>
        </label>
        <ErrorNote error={start.error} />
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button onClick={() => start.mutate()} disabled={blocked || !confirmed || start.isPending}>
            {start.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />} {t("amrRelease.start")}
          </Button>
        </div>
      </div>
    </Dialog>
  );
}
