import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, Loader2 } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { ErrorNote } from "@/components/ui/misc";
import { useT } from "@/i18n";
import { api } from "@/lib/api";
import { fmtBytes, fmtInt } from "@/lib/format";

const CHECK = "mt-0.5 h-4 w-4 shrink-0 accent-[#00B4A6]";

/** NCBI's current 16S ribosomal RNA BLAST database (type strains): its date, size and MD5 as NCBI publishes them
 * (only NCBI's metadata and MD5 files are read to show this), the files kept and where, and the download after an
 * explicit confirmation of the date, the size and NCBI's terms. NCBI keeps only the current build. */
export function Ncbi16sDialog({ onClose }: { onClose: () => void }) {
  const t = useT();
  const qc = useQueryClient();
  const [taxonomy, setTaxonomy] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const plan = useQuery({ queryKey: ["ncbi16sPlan", taxonomy], queryFn: () => api.ncbi16sPlan({ taxonomy }), retry: false });
  const p = plan.data;
  const start = useMutation({
    mutationFn: () => api.ncbi16sDownload({ taxonomy, confirm_version: p!.version, confirm_bytes: p!.archive_bytes, accept_terms: true }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["databases"] });
      onClose();
    },
  });
  const blocked = !p || Boolean(p.blocked_by) || !p.enough;
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()} title={t("ncbi16s.title")} description={t("ncbi16s.description")} className="max-w-2xl">
      <div className="space-y-4 text-sm">
        {plan.isFetching && <p className="text-xs text-muted-foreground">{t("ncbi16s.checking")}</p>}
        <ErrorNote error={plan.error} />
        {p && (
          <div className="space-y-2 text-xs">
            <p>{t("ncbi16s.build", { version: p.version, size: fmtBytes(p.archive_bytes), sequences: p.sequences != null ? fmtInt(p.sequences) : "?" })}</p>
            <p className="break-all text-muted-foreground">{t("ncbi16s.source", { url: p.url, md5: p.md5 })}</p>
            <details>
              <summary className="cursor-pointer text-muted-foreground">{t("ncbi16s.files", { n: p.kept_files.length })}</summary>
              <ul className="mt-1 max-h-40 overflow-y-auto font-mono text-[11px]">
                {p.kept_files.map((f) => (
                  <li key={f}>{f}</li>
                ))}
              </ul>
            </details>
            <p>{t("ncbi16s.target", { path: p.host_target_path, required: fmtBytes(p.required_bytes), available: fmtBytes(p.available_bytes) })}</p>
            <p className="text-muted-foreground">{t("ncbi16s.onlyCurrent")}</p>
            <p className="text-muted-foreground">{t("ncbi16s.licence", { licence: p.licence })}</p>
            {p.blocked_by && <p className="text-danger">{p.blocked_by}</p>}
            {!p.enough && <p className="text-danger">{t("ncbi16s.noSpace")}</p>}
          </div>
        )}
        <label className="flex items-start gap-2 text-xs">
          <input
            type="checkbox"
            className={CHECK}
            checked={taxonomy}
            onChange={(e) => {
              setTaxonomy(e.target.checked);
              setConfirmed(false);
            }}
          />
          <span>{t("ncbi16s.taxonomy")}</span>
        </label>
        <label className="flex items-start gap-2 text-xs">
          <input type="checkbox" className={CHECK} checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} disabled={!p} />
          <span>{t("ncbi16s.confirm", { version: p?.version ?? "?", size: p ? fmtBytes(p.archive_bytes) : "?" })}</span>
        </label>
        <ErrorNote error={start.error} />
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button onClick={() => start.mutate()} disabled={blocked || !confirmed || start.isPending || plan.isFetching}>
            {start.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />} {t("ncbi16s.start")}
          </Button>
        </div>
      </div>
    </Dialog>
  );
}
