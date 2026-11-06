import { useMutation, useQuery } from "@tanstack/react-query";
import { Download, FolderPlus, Loader2 } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Input, Select } from "@/components/ui/form";
import { ErrorNote } from "@/components/ui/misc";
import { useT } from "@/i18n";
import { api } from "@/lib/api";
import { validDate, validFolder } from "@/lib/databases";
import { fmtBytes, fmtInt } from "@/lib/format";
import type { VfdbPlan } from "@/lib/types";
import { useRefreshDatabases } from "./RecordRow";
import { ExtLink } from "./shared";

const CHECK = "mt-0.5 h-4 w-4 shrink-0 accent-[#00B4A6]";

/** VFDB's full dataset (set B) as an ABRicate database for the virulence screen. "download": the current
 * VFDB_setB_nt.fas.gz as VFDB's server states it (one HEAD request; nothing else is sent), with its size, date, source,
 * VFDB's licence (CC BY-NC 4.0) and citation, the folder and the space, downloaded only after an explicit
 * confirmation. "build": the same database from a VFDB nucleotide file you already have (the file is only read). */
export function VfdbDialog({ mode, initialPath = "", onClose }: { mode: "download" | "build"; initialPath?: string; onClose: () => void }) {
  const t = useT();
  const refresh = useRefreshDatabases();
  const [destination, setDestination] = useState<string | null>(null);
  const [folder, setFolder] = useState("");
  const [path, setPath] = useState(initialPath);
  const [typed, setTyped] = useState(initialPath);
  const [set, setSet] = useState<"" | "A" | "B">("");
  const [declared, setDeclared] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const folderOk = folder === "" || validFolder(folder);
  const declaredOk = declared === "" || validDate(declared);
  const build = mode === "build";
  const plan = useQuery({
    queryKey: ["vfdbPlan", mode, destination, folder, path, set, declared],
    queryFn: () =>
      build
        ? api.vfdbBuildPlan({ path, vfdb_set: set || null, declared_version: declared || null, destination, folder: folder || null })
        : api.vfdbPlan({ destination, folder: folder || null }),
    enabled: folderOk && declaredOk && (!build || path !== ""),
    retry: false,
    staleTime: 0,
  });
  const p: VfdbPlan | undefined = plan.data;
  const start = useMutation({
    mutationFn: () =>
      build
        ? api.vfdbBuild({ path, vfdb_set: set || null, declared_version: declared || null, destination, folder: folder || null, confirm_bytes: p!.bytes, accept_terms: true })
        : api.vfdbDownload({ destination, folder: folder || null, confirm_version: p!.version, confirm_bytes: p!.bytes, accept_terms: true }),
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
    <Dialog open onOpenChange={(o) => !o && onClose()} title={t(build ? "vfdb.buildTitle" : "vfdb.title")} description={t(build ? "vfdb.buildDescription" : "vfdb.description")} className="max-w-2xl">
      <div className="space-y-4 text-sm">
        {build && (
          <form
            className="space-y-2 text-xs"
            onSubmit={(e) => {
              e.preventDefault();
              change(setPath)(typed.trim());
            }}
          >
            <label className="block space-y-1">
              <span className="font-medium">{t("vfdb.path")}</span>
              <span className="flex gap-2">
                <Input value={typed} onChange={(e) => setTyped(e.target.value)} placeholder="/…/VFDB_setB_nt.fas.gz" className="font-mono text-xs" />
                <Button type="submit" size="sm" variant="outline" disabled={!typed.trim()}>
                  {t("vfdb.check")}
                </Button>
              </span>
              <span className="block text-muted-foreground">{t("vfdb.pathHint")}</span>
            </label>
            <div className="grid gap-3 sm:grid-cols-2">
              <label className="block space-y-1">
                <span className="font-medium">{t("vfdb.set")}</span>
                <Select value={set} onChange={(e) => change(setSet)(e.target.value as "" | "A" | "B")} aria-label={t("vfdb.set")}>
                  <option value="">{t("vfdb.setFromFile")}</option>
                  <option value="B">{t("virulence.set.B")}</option>
                  <option value="A">{t("virulence.set.A")}</option>
                </Select>
              </label>
              <label className="block space-y-1">
                <span className="font-medium">{t("vfdb.declared")}</span>
                <Input value={declared} onChange={(e) => change(setDeclared)(e.target.value)} placeholder={t("vfdb.datePlaceholder")} aria-invalid={!declaredOk} />
                <span className={declaredOk ? "block text-muted-foreground" : "block text-danger"}>{t("vfdb.declaredHint")}</span>
              </label>
            </div>
          </form>
        )}
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
            <Input value={folder} onChange={(e) => change(setFolder)(e.target.value)} placeholder={p ? `${p.key}/${p.version}` : "vfdb-setB/…"} className="font-mono text-xs" aria-invalid={!folderOk} />
            <span className={folderOk ? "block text-muted-foreground" : "block text-danger"}>{folderOk ? t("databases.folderNameHint") : t("api.error.bad_folder")}</span>
          </label>
        </div>
        {plan.isFetching && <p className="text-xs text-muted-foreground">{t("vfdb.checking")}</p>}
        <ErrorNote error={plan.error} />
        {p && (
          <dl className="grid grid-cols-[170px_1fr] gap-x-3 gap-y-1.5 text-xs">
            <dt className="text-muted-foreground">{t("vfdb.fileLabel")}</dt>
            <dd>
              {build ? <code className="break-all">{p.host_source ?? p.source}</code> : <code>{p.file}</code>} · {t(p.set === "A" ? "virulence.set.A" : "virulence.set.B")}
              <span className="block text-muted-foreground">{t(p.set === "A" ? "virulence.setCore" : "virulence.setFull", { version: p.version })}</span>
            </dd>
            <dt className="text-muted-foreground">{t("vfdb.sizeLabel")}</dt>
            <dd>
              {fmtBytes(p.bytes)} ({fmtInt(p.bytes)} {t("databases.bytes")})
            </dd>
            <dt className="text-muted-foreground">{t("vfdb.dateLabel")}</dt>
            <dd>
              {p.version}{" "}
              <span className="text-muted-foreground">
                {build ? t(p.version_source === "file" ? "vfdb.dateFromGzip" : "vfdb.dateDeclared") : t("vfdb.dateFromServer", { modified: p.last_modified ?? "?" })}
              </span>
            </dd>
            {!build && (
              <>
                <dt className="text-muted-foreground">{t("databases.source")}</dt>
                <dd className="min-w-0">
                  <ExtLink href={p.url ?? p.source_page}>{p.url ?? p.source_page}</ExtLink>
                  <span className="block text-muted-foreground">{t("vfdb.onlyCurrent")}</span>
                </dd>
              </>
            )}
            <dt className="text-muted-foreground">{t("databases.licence")}</dt>
            <dd>
              {p.licence_url ? <ExtLink href={p.licence_url}>{p.licence}</ExtLink> : p.licence}{" "}
              <ExtLink href={p.terms_url}>{t("vfdb.terms")}</ExtLink>
            </dd>
            <dt className="text-muted-foreground">{t("vfdb.citeLabel")}</dt>
            <dd>{p.citation}</dd>
            <dt className="text-muted-foreground">{t("databases.checksum")}</dt>
            <dd>{t("vfdb.noChecksum")}</dd>
            <dt className="font-medium">{t("databases.required")}</dt>
            <dd className="font-medium">{fmtBytes(p.required_bytes)}</dd>
            <dt className="text-muted-foreground">{t("databases.usableSpace")}</dt>
            <dd>{fmtBytes(p.available_bytes)}</dd>
            <dt className="text-muted-foreground">{t("databases.installInto")}</dt>
            <dd>
              <code className="break-all">{p.host_target_path ?? p.target_path}</code>
              <span className="block text-muted-foreground">{t("vfdb.abricateArgs", { db: p.abricate_db })}</span>
            </dd>
          </dl>
        )}
        {p && (
          <ul className="list-disc space-y-1 pl-4 text-xs text-muted-foreground">
            {!build && <li>{t("vfdb.step.download")}</li>}
            <li>{t("vfdb.step.check")}</li>
            <li>{t("vfdb.step.convert")}</li>
            <li>{t("vfdb.step.index")}</li>
            <li>{t("vfdb.step.record")}</li>
            <li>{t("vfdb.step.default")}</li>
          </ul>
        )}
        {p?.blocked_by && <ErrorNote error={p.blocked_code ? t(`databases.blocked.${p.blocked_code}` as "databases.blocked.already_known") : p.blocked_by} />}
        {p && !p.enough && !p.blocked_by && <ErrorNote error={t("databases.notEnough", { required: fmtBytes(p.required_bytes), available: fmtBytes(p.available_bytes) })} />}
        <label className="flex items-start gap-2 text-xs">
          <input type="checkbox" className={CHECK} checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} disabled={!p} />
          <span>{t(build ? "vfdb.confirmBuild" : "vfdb.confirm", { version: p?.version ?? "?", size: p ? fmtBytes(p.bytes) : "?" })}</span>
        </label>
        <ErrorNote error={start.error} />
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button onClick={() => start.mutate()} disabled={blocked || !confirmed || start.isPending || plan.isFetching}>
            {start.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : build ? <FolderPlus className="h-4 w-4" /> : <Download className="h-4 w-4" />}{" "}
            {t(build ? "vfdb.startBuild" : "vfdb.start", { size: p ? fmtBytes(p.bytes) : "?" })}
          </Button>
        </div>
      </div>
    </Dialog>
  );
}
