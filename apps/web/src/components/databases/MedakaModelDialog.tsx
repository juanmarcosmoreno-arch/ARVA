import { useMutation, useQuery } from "@tanstack/react-query";
import { Download, Loader2 } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Input, Select } from "@/components/ui/form";
import { ErrorNote } from "@/components/ui/misc";
import { useT } from "@/i18n";
import { api } from "@/lib/api";
import { validFolder } from "@/lib/databases";
import { fmtBytes, fmtInt } from "@/lib/format";
import type { MedakaModelInfo, MedakaModelPlan } from "@/lib/types";
import { useRefreshDatabases } from "./RecordRow";
import { ExtLink } from "./shared";

const CHECK = "mt-0.5 h-4 w-4 shrink-0 accent-[#00B4A6]";

/** One Medaka model that medaka's package does not ship, downloaded only after an explicit confirmation of the model,
 * what it was trained for, the address (medaka's repository at the installed version's tag), its size and published
 * SHA-256, and Medaka's licence. Nothing is sent before the user starts it. */
export function MedakaModelDialog({ model, onClose }: { model: MedakaModelInfo; onClose: () => void }) {
  const t = useT();
  const refresh = useRefreshDatabases();
  const [destination, setDestination] = useState<string | null>(null);
  const [folder, setFolder] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const folderOk = folder === "" || validFolder(folder);
  const plan = useQuery({
    queryKey: ["medakaModelPlan", model.name, destination, folder],
    queryFn: () => api.medakaModelPlan({ model: model.name, destination, folder: folder || null }),
    enabled: folderOk,
    retry: false,
    staleTime: 0,
  });
  const p: MedakaModelPlan | undefined = plan.data;
  const start = useMutation({
    mutationFn: () =>
      api.medakaModelDownload({ model: model.name, destination, folder: folder || null, confirm_sha256: p!.sha256, confirm_bytes: p!.bytes, accept_licence: true }),
    onSuccess: () => {
      refresh();
      onClose();
    },
  });
  const change = <V,>(setter: (v: V) => void) => (v: V) => {
    setter(v);
    setConfirmed(false);
  };
  const blocked = !p || Boolean(p.blocked_by) || !p.enough;
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()} title={t("medakaModels.title", { model: model.name })} description={t("medakaModels.description")} className="max-w-2xl">
      <div className="space-y-4 text-sm">
        <div className="grid gap-3 text-xs sm:grid-cols-2">
          <label className="space-y-1">
            <span className="font-medium">{t("databases.destination")}</span>
            <Select value={destination ?? p?.db_dir ?? ""} onChange={(e) => change(setDestination)(e.target.value)} aria-label={t("databases.destination")}>
              {(p?.destinations ?? []).map((d) => (
                <option key={d.path} value={d.path} disabled={!d.available}>
                  {d.host_path ?? d.path} · {d.free_bytes != null ? t("databases.freeShort", { free: fmtBytes(d.free_bytes) }) : t("databases.unavailable.disk_not_connected")}
                </option>
              ))}
            </Select>
          </label>
          <label className="space-y-1">
            <span className="font-medium">{t("databases.folderName")}</span>
            <Input value={folder} onChange={(e) => change(setFolder)(e.target.value)} placeholder={p?.folder ?? `medaka-models/${model.name}`} className="font-mono text-xs" aria-invalid={!folderOk} />
            <span className={folderOk ? "block text-muted-foreground" : "block text-danger"}>{folderOk ? t("databases.folderNameHint") : t("api.error.bad_folder")}</span>
          </label>
        </div>
        {plan.isFetching && <p className="text-xs text-muted-foreground">{t("medakaModels.checking")}</p>}
        <ErrorNote error={plan.error} />
        {p && (
          <dl className="grid grid-cols-[170px_1fr] gap-x-3 gap-y-1.5 text-xs">
            <dt className="text-muted-foreground">{t("medakaModels.model")}</dt>
            <dd>
              <code>{p.model}</code> · <code className="break-all">{p.file}</code>
            </dd>
            <dt className="text-muted-foreground">{t("medakaModels.trainedFor")}</dt>
            <dd>{t("medakaModels.trainedForValue", { chemistry: p.chemistry, device: p.device ?? "—", accuracy: p.accuracy, basecaller: p.basecaller })}</dd>
            <dt className="text-muted-foreground">{t("vfdb.sizeLabel")}</dt>
            <dd>
              {fmtBytes(p.bytes)} ({fmtInt(p.bytes)} {t("databases.bytes")})
            </dd>
            <dt className="text-muted-foreground">{t("databases.checksum")}</dt>
            <dd>
              <code className="break-all">{p.sha256}</code>
              <span className="block text-muted-foreground">{t("medakaModels.checksumFrom", { tag: p.tag })}</span>
            </dd>
            <dt className="text-muted-foreground">{t("databases.source")}</dt>
            <dd className="min-w-0">
              <ExtLink href={p.url}>{p.url}</ExtLink>
              <span className="block text-muted-foreground">{t("medakaModels.sourceNote", { tag: p.tag, medakaUrl: p.medaka_url })}</span>
            </dd>
            <dt className="text-muted-foreground">{t("databases.licence")}</dt>
            <dd>
              <ExtLink href={p.licence_url}>{p.licence}</ExtLink>
            </dd>
            <dt className="text-muted-foreground">{t("vfdb.citeLabel")}</dt>
            <dd>{p.citation}</dd>
            <dt className="text-muted-foreground">{t("databases.installInto")}</dt>
            <dd>
              <code className="break-all">{p.host_target_path ?? p.target_path}</code>
            </dd>
          </dl>
        )}
        {p && (
          <ul className="list-disc space-y-1 pl-4 text-xs text-muted-foreground">
            <li>{t("medakaModels.step.download")}</li>
            <li>{t("medakaModels.step.checksum")}</li>
            <li>{t("medakaModels.step.archive")}</li>
            <li>{t("medakaModels.step.load")}</li>
            <li>{t("medakaModels.step.use")}</li>
          </ul>
        )}
        {p?.notes.includes("fast") && <p className="text-xs text-amber-700 dark:text-warning">{t("medakaModels.fastNote")}</p>}
        {p?.notes.includes("plant") && <p className="text-xs text-amber-700 dark:text-warning">{t("medakaModels.plantNote")}</p>}
        {p?.blocked_by && <ErrorNote error={p.blocked_code ? t(`databases.blocked.${p.blocked_code}` as "databases.blocked.already_known") : p.blocked_by} />}
        {p && !p.enough && !p.blocked_by && <ErrorNote error={t("databases.notEnough", { required: fmtBytes(p.required_bytes), available: fmtBytes(p.available_bytes) })} />}
        <label className="flex items-start gap-2 text-xs">
          <input type="checkbox" className={CHECK} checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} disabled={!p} />
          <span>{t("medakaModels.confirm", { model: model.name, size: p ? fmtBytes(p.bytes) : "?", licence: p?.licence ?? "?" })}</span>
        </label>
        <ErrorNote error={start.error} />
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button onClick={() => start.mutate()} disabled={blocked || !confirmed || start.isPending || plan.isFetching}>
            {start.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />} {t("medakaModels.start", { size: p ? fmtBytes(p.bytes) : "?" })}
          </Button>
        </div>
      </div>
    </Dialog>
  );
}
