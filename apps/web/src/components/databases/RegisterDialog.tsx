import { useMutation, useQuery } from "@tanstack/react-query";
import { CheckCircle2, ChevronLeft, File, Folder, FolderPlus, Search, XCircle } from "lucide-react";
import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Input, Select } from "@/components/ui/form";
import { ErrorNote, Skeleton } from "@/components/ui/misc";
import { useT, type TranslationKey } from "@/i18n";
import { api } from "@/lib/api";
import { joinHost, validDate, validDeclaredVersion, validFolder } from "@/lib/databases";
import { fmtBytes, fmtInt } from "@/lib/format";
import type { Detection } from "@/lib/types";
import { useRefreshDatabases } from "./RecordRow";
import { CompatibilityBadge, compatibilityText, problemText } from "./shared";

type T = ReturnType<typeof useT>;

export function RegisterDialog({ onClose }: { onClose: () => void }) {
  const t = useT();
  const locations = useQuery({ queryKey: ["database-locations"], queryFn: api.databaseLocations });
  const roots = locations.data?.browse ?? [];
  const [root, setRoot] = useState<string | null>(null);
  const [rel, setRel] = useState("");
  const [typed, setTyped] = useState("");
  const [target, setTarget] = useState<string | null>(null);
  const activeRoot = root ?? roots.find((r) => r.available)?.path ?? null;
  const listing = useQuery({
    queryKey: ["database-browse", activeRoot, rel],
    queryFn: () => api.browseDatabases(activeRoot ?? "", rel),
    enabled: !!activeRoot && target === null,
  });
  const detection = useQuery({ queryKey: ["database-detect", target], queryFn: () => api.detectDatabase(target ?? ""), enabled: !!target, staleTime: 0 });
  const choose = (path: string) => setTarget(path);

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()} title={t("databases.registerTitle")} description={t("databases.registerHint")} className="max-w-3xl">
      <div className="space-y-4 text-sm">
        {target === null ? (
          <>
            <div className="flex flex-wrap items-end gap-2">
              <label className="min-w-0 flex-1 space-y-1 text-xs">
                <span className="font-medium">{t("databases.browseIn")}</span>
                <Select
                  value={activeRoot ?? ""}
                  onChange={(e) => {
                    setRoot(e.target.value);
                    setRel("");
                  }}
                  aria-label={t("databases.browseIn")}
                >
                  {roots.map((r) => (
                    <option key={r.path} value={r.path} disabled={!r.available}>
                      {r.host_path ?? r.path} · {r.read_only ? t("databases.readOnly") : t("databases.writable")}
                      {!r.available ? ` · ${t("databases.unavailable.disk_not_connected")}` : ""}
                    </option>
                  ))}
                </Select>
              </label>
            </div>
            {roots.length === 0 && !locations.isLoading && <p className="text-xs text-muted-foreground">{t("databases.noBrowseRoots")}</p>}
            <ErrorNote error={locations.error ?? listing.error} />
            {listing.data && (
              <div className="rounded-lg border">
                <div className="flex items-center justify-between gap-2 border-b px-3 py-2 text-xs">
                  <span className="flex min-w-0 items-center gap-2">
                    {listing.data.parent !== null && (
                      <Button size="sm" variant="ghost" onClick={() => setRel(listing.data.parent ?? "")} aria-label={t("databases.up")}>
                        <ChevronLeft className="h-3.5 w-3.5" aria-hidden />
                      </Button>
                    )}
                    <code className="truncate">{listing.data.host_path}</code>
                  </span>
                  <Button size="sm" variant="outline" onClick={() => choose(listing.data.host_path)}>
                    <Search className="h-3.5 w-3.5" aria-hidden /> {t("databases.detectThisFolder")}
                  </Button>
                </div>
                <ul className="max-h-72 divide-y overflow-y-auto">
                  {listing.data.entries.length === 0 && <li className="px-3 py-2 text-xs text-muted-foreground">{t("databases.emptyFolder")}</li>}
                  {listing.data.entries.map((e) => (
                    <li key={e.name} className="flex items-center justify-between gap-2 px-3 py-1.5 text-xs">
                      {e.type === "folder" ? (
                        <button type="button" className="flex min-w-0 items-center gap-2 text-left hover:underline" onClick={() => setRel(listing.data.path ? `${listing.data.path}/${e.name}` : e.name)}>
                          <Folder className="h-3.5 w-3.5 shrink-0 text-arva-royal dark:text-arva-cyan" aria-hidden />
                          <span className="truncate">{e.name}</span>
                        </button>
                      ) : (
                        <span className="flex min-w-0 items-center gap-2">
                          <File className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden />
                          <span className="truncate">{e.name}</span>
                          <span className="shrink-0 text-muted-foreground">{fmtBytes(e.size_bytes ?? 0)}</span>
                        </span>
                      )}
                      <Button size="sm" variant="ghost" onClick={() => choose(joinHost(listing.data.host_path, e.name))}>
                        {t("databases.detect")}
                      </Button>
                    </li>
                  ))}
                </ul>
                {listing.data.truncated && <p className="border-t px-3 py-1.5 text-xs text-muted-foreground">{t("databases.truncated")}</p>}
              </div>
            )}
            {listing.isLoading && <Skeleton className="h-40" />}
            <form
              className="flex gap-2"
              onSubmit={(e) => {
                e.preventDefault();
                if (typed.trim()) choose(typed.trim());
              }}
            >
              <label className="sr-only" htmlFor="register-db-path">
                {t("databases.registerPath")}
              </label>
              <Input id="register-db-path" value={typed} onChange={(e) => setTyped(e.target.value)} placeholder={t("databases.registerPathExample")} className="font-mono text-xs" />
              <Button type="submit" size="sm" variant="outline" disabled={!typed.trim()}>
                <Search className="h-3.5 w-3.5" aria-hidden /> {t("databases.detect")}
              </Button>
            </form>
            <p className="text-xs text-muted-foreground">{t("databases.addFolderHint")}</p>
          </>
        ) : (
          <>
            <div className="flex items-center justify-between gap-2">
              <code className="min-w-0 break-all text-xs">{detection.data?.host_path ?? target}</code>
              <Button size="sm" variant="ghost" onClick={() => setTarget(null)}>
                <ChevronLeft className="h-3.5 w-3.5" aria-hidden /> {t("databases.chooseAnother")}
              </Button>
            </div>
            <ErrorNote error={detection.error} />
            {detection.isLoading && <Skeleton className="h-40" />}
            {detection.data && detection.data.candidates.length === 0 && <ErrorNote error={t("api.error.not_recognised", { path: detection.data.host_path ?? target })} />}
            {detection.data?.candidates.map((d) =>
              d.kind === "unknown" ? (
                <NestedHint key={d.kind} detection={d} onPick={(name) => setTarget(joinHost(detection.data.host_path ?? target, name))} />
              ) : (
                <CandidatePanel key={d.kind} detection={d} path={detection.data.host_path ?? target} onDone={onClose} />
              ),
            )}
          </>
        )}
      </div>
    </Dialog>
  );
}

function NestedHint({ detection, onPick }: { detection: Detection; onPick: (name: string) => void }) {
  const t = useT();
  return (
    <div className="space-y-2 rounded-lg border p-3 text-xs">
      <p>{detection.problems.map((p) => problemText(t, p)).join(" ")}</p>
      <div className="flex flex-wrap gap-2">
        {(detection.facts.nested ?? []).map((name) => (
          <Button key={name} size="sm" variant="outline" onClick={() => onPick(name)}>
            <Folder className="h-3.5 w-3.5" aria-hidden /> {name}
          </Button>
        ))}
      </div>
    </div>
  );
}

const VARIANTS = ["light", "full", "ncbi_package", "ncbi_package_zip", "fastani_list", "fasta_folder"];

export function variantName(t: T, variant: string) {
  return VARIANTS.includes(variant) ? t(`databases.variant.${variant}` as TranslationKey) : variant;
}

function suggestedFrom(t: T, d: Detection) {
  return d.suggested_from ? t(`databases.suggestedFrom.${d.suggested_from}` as TranslationKey) : "";
}

function CandidatePanel({ detection: d, path, onDone }: { detection: Detection; path: string; onDone: () => void }) {
  const t = useT();
  const refresh = useRefreshDatabases();
  const collection = d.kind === "reference_genomes";
  const [declared, setDeclared] = useState(collection ? "" : (d.suggested_version ?? ""));
  const [day, setDay] = useState(collection ? (d.suggested_version ?? "") : "");
  const [fullChecksum, setFullChecksum] = useState(false);
  const register = useMutation({
    mutationFn: () =>
      api.registerDatabase({
        path,
        kind: d.kind,
        declared_version: !collection && d.needs_declared_version ? declared.trim() : null,
        collection_date: collection ? day : null,
        full_checksum: fullChecksum,
      }),
    onSuccess: () => {
      refresh();
      onDone();
    },
  });
  const blocking = d.problems.filter((p) => p.blocking && p.code !== "zip_package");
  const needsVersion = !collection && d.needs_declared_version;
  const inputsOk = collection ? validDate(day) : !needsVersion || validDeclaredVersion(declared);
  const c = d.facts.collection;
  return (
    <div className="space-y-3 rounded-lg border p-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-semibold">{d.kind_name}</span>
        {d.variant && <Badge>{variantName(t, d.variant)}</Badge>}
        {d.ok ? (
          <Badge tone="success">
            <CheckCircle2 className="h-3 w-3" aria-hidden /> {t("databases.detectOk")}
          </Badge>
        ) : (
          <Badge tone="danger">
            <XCircle className="h-3 w-3" aria-hidden /> {t("databases.detectProblems")}
          </Badge>
        )}
        <CompatibilityBadge compatibility={d.compatibility} />
      </div>
      <dl className="grid grid-cols-[180px_1fr] gap-x-3 gap-y-1 text-xs">
        <dt className="text-muted-foreground">{t("databases.versionLabel")}</dt>
        <dd>
          {d.version ? (
            <>
              {d.version} <span className="text-muted-foreground">{t("databases.versionReadFrom", { file: d.version_file ?? "?" })}</span>
            </>
          ) : d.version_by_checksum ? (
            t("databases.versionByChecksum")
          ) : (
            <span className="text-amber-700 dark:text-warning">{collection ? t("databases.collectionVersion") : t("databases.versionNotStated")}</span>
          )}
        </dd>
        {d.compatibility && (
          <>
            <dt className="text-muted-foreground">{t("databases.compatibility")}</dt>
            <dd>{compatibilityText(t, d.compatibility)}</dd>
          </>
        )}
        <dt className="text-muted-foreground">{t("databases.filesChecked")}</dt>
        <dd>
          <ul className="space-y-0.5">
            {d.files.slice(0, 12).map((f) => (
              <li key={f.path} className="flex items-center gap-1.5">
                {f.present ? <CheckCircle2 className="h-3 w-3 shrink-0 text-success" aria-hidden /> : <XCircle className="h-3 w-3 shrink-0 text-danger" aria-hidden />}
                <code className="break-all">{f.path}</code>
                <span className="text-muted-foreground">
                  {t(`databases.role.${f.role}` as TranslationKey)}
                  {f.size != null ? ` · ${fmtBytes(f.size)}` : ""}
                </span>
              </li>
            ))}
            {d.files.length > 12 && <li className="text-muted-foreground">{t("databases.moreFiles", { n: d.files.length - 12 })}</li>}
          </ul>
        </dd>
      </dl>
      {c && (
        <div className="rounded bg-muted/40 p-2 text-xs">
          <p className="font-medium">{t("databases.coverage", { genomes: c.genomes, species: c.species })}</p>
          <p className="text-muted-foreground">
            {t("databases.typeAndReference", { type: c.type_material.reduce((n, x) => n + (x.label === "TYPE_MATERIAL" ? x.genomes : 0), 0), reference: c.reference_genomes })}
          </p>
          <p className="mt-1 text-muted-foreground">
            {c.by_species
              .slice(0, 8)
              .map((s) => `${s.species === "unclassified" ? t("databases.unclassifiedName") : s.species} (${fmtInt(s.genomes)})`)
              .join(" · ")}
          </p>
          <p className="mt-1 font-mono text-[11px] text-muted-foreground">{t("databases.fingerprint", { fp: c.fingerprint.slice(0, 12) })}</p>
        </div>
      )}
      {d.problems.length > 0 && (
        <ul className="space-y-1 text-xs">
          {d.problems.map((p, i) => (
            <li key={i} className={p.blocking && p.code !== "zip_package" ? "text-danger" : "text-amber-700 dark:text-warning"}>
              {problemText(t, p)}
            </li>
          ))}
        </ul>
      )}
      {d.already_registered && <ErrorNote error={t("api.error.already_registered", { path })} />}
      {d.path_type === "zip" ? (
        <ExtractPanel detection={d} path={path} onDone={onDone} />
      ) : (
        !d.already_registered &&
        blocking.length === 0 && (
          <div className="space-y-2 border-t pt-3">
            {needsVersion && (
              <label className="block space-y-1 text-xs">
                <span className="font-medium">{t("databases.declaredVersion")}</span>
                <Input value={declared} onChange={(e) => setDeclared(e.target.value)} aria-invalid={!inputsOk} />
                <span className="block text-muted-foreground">
                  {d.suggested_version ? t("databases.suggestedHint", { version: d.suggested_version, from: suggestedFrom(t, d) }) : t("databases.declaredHint")}
                </span>
              </label>
            )}
            {collection && (
              <label className="block space-y-1 text-xs">
                <span className="font-medium">{t("databases.collectionDate")}</span>
                <Input type="date" value={day} onChange={(e) => setDay(e.target.value)} aria-invalid={!inputsOk} />
                <span className="block text-muted-foreground">
                  {d.suggested_version ? t("databases.collectionDateSuggested", { date: d.suggested_version, from: suggestedFrom(t, d) }) : t("databases.collectionDateHint")}
                </span>
              </label>
            )}
            <label className="flex items-start gap-2 text-xs">
              <input type="checkbox" className="mt-0.5" checked={fullChecksum} onChange={(e) => setFullChecksum(e.target.checked)} />
              <span>{t("databases.fullChecksumNow")}</span>
            </label>
            <p className="text-xs text-muted-foreground">{t("databases.readOnlyPromise")}</p>
            <ErrorNote error={register.error} />
            <div className="flex justify-end">
              <Button onClick={() => register.mutate()} disabled={!inputsOk || register.isPending}>
                <FolderPlus className="h-4 w-4" aria-hidden /> {t("databases.register")}
              </Button>
            </div>
          </div>
        )
      )}
    </div>
  );
}

function ExtractPanel({ detection: d, path, onDone }: { detection: Detection; path: string; onDone: () => void }) {
  const t = useT();
  const refresh = useRefreshDatabases();
  const [destination, setDestination] = useState<string | null>(null);
  const [folder, setFolder] = useState("");
  const [day, setDay] = useState(d.suggested_version ?? "");
  const folderOk = folder === "" || validFolder(folder);
  const plan = useQuery({
    queryKey: ["extract-plan", path, destination, folder],
    queryFn: () => api.extractPlan(path, destination, folder || null),
    enabled: folderOk,
    staleTime: 0,
  });
  const p = plan.data;
  const extract = useMutation({
    mutationFn: () => api.extractDatabase({ path, confirm_bytes: p?.required_bytes ?? 0, collection_date: day, destination, folder: folder || null }),
    onSuccess: () => {
      refresh();
      onDone();
    },
  });
  return (
    <div className="space-y-2 border-t pt-3 text-xs">
      <p className="font-medium">{t("databases.extractTitle")}</p>
      <p className="text-muted-foreground">{t("databases.extractHint")}</p>
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="space-y-1">
          <span className="font-medium">{t("databases.destination")}</span>
          <Select value={destination ?? p?.db_dir ?? ""} onChange={(e) => setDestination(e.target.value)} aria-label={t("databases.destination")}>
            {(p?.destinations ?? []).map((loc) => (
              <option key={loc.path} value={loc.path} disabled={!loc.available}>
                {loc.host_path ?? loc.path}
              </option>
            ))}
          </Select>
        </label>
        <label className="space-y-1">
          <span className="font-medium">{t("databases.folderName")}</span>
          <Input value={folder} onChange={(e) => setFolder(e.target.value)} placeholder={p?.folder} className="font-mono text-xs" aria-invalid={!folderOk} />
        </label>
      </div>
      <label className="block space-y-1">
        <span className="font-medium">{t("databases.collectionDate")}</span>
        <Input type="date" value={day} onChange={(e) => setDay(e.target.value)} />
        <span className="block text-muted-foreground">{t("databases.collectionDateSuggested", { date: d.suggested_version ?? "?", from: suggestedFrom(t, d) })}</span>
      </label>
      <ErrorNote error={plan.error ?? extract.error} />
      {p && (
        <dl className="grid grid-cols-[180px_1fr] gap-x-3 gap-y-1">
          <dt className="text-muted-foreground">{t("databases.copySize")}</dt>
          <dd>{fmtBytes(p.required_bytes)}</dd>
          <dt className="text-muted-foreground">{t("databases.usableSpace")}</dt>
          <dd>
            {fmtBytes(p.available_bytes)} <span className="text-muted-foreground">{t("databases.usableSpaceHint", { free: fmtBytes(p.free_bytes), reserve: fmtBytes(p.reserve_bytes) })}</span>
          </dd>
          <dt className="text-muted-foreground">{t("databases.installInto")}</dt>
          <dd>
            <code className="break-all">{p.host_target_path}</code>
          </dd>
        </dl>
      )}
      {p?.blocked_by && <ErrorNote error={p.blocked_by} />}
      {p && !p.enough && <ErrorNote error={t("databases.notEnough", { required: fmtBytes(p.required_bytes), available: fmtBytes(p.available_bytes) })} />}
      <div className="flex justify-end">
        <Button onClick={() => extract.mutate()} disabled={!p || !p.enough || !!p.blocked_by || !validDate(day) || extract.isPending || !folderOk}>
          <FolderPlus className="h-4 w-4" aria-hidden /> {t("databases.extractAction", { size: fmtBytes(p?.required_bytes ?? 0) })}
        </Button>
      </div>
    </div>
  );
}
