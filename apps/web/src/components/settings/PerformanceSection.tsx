import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Cpu } from "lucide-react";
import { useEffect, useState } from "react";
import { Explain } from "@/components/guide/Explain";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Field, Input } from "@/components/ui/form";
import { ErrorNote, Skeleton } from "@/components/ui/misc";
import { useT, type TranslationKey } from "@/i18n";
import { api } from "@/lib/api";
import {
  PROFILE_CHOICES,
  customBounds,
  factSource,
  initialForm,
  memoryText,
  profileName,
  profileRequest,
  type ProfileForm,
} from "@/lib/performance";
import type { PerformanceOverview } from "@/lib/types";
import { cn } from "@/lib/utils";

export function PerformanceSection() {
  const t = useT();
  const query = useQuery({ queryKey: ["performance"], queryFn: api.performance });
  return (
    <Card className="lg:col-span-2">
      <CardHeader
        title={t("perf.title")}
        description={t("perf.subtitle")}
        action={
          <span className="flex items-center gap-3">
            <Explain id="performance_profile" />
            <Cpu className="h-4 w-4 text-arva-teal" aria-hidden />
          </span>
        }
      />
      <CardBody>
        {query.isLoading ? <Skeleton className="h-40" /> : query.error ? <ErrorNote error={query.error} /> : query.data && <Performance p={query.data} />}
      </CardBody>
    </Card>
  );
}

function Performance({ p }: { p: PerformanceOverview }) {
  return (
    <div className="grid gap-6 text-sm xl:grid-cols-2">
      <div className="space-y-5">
        <Detected p={p} />
        <Automatic p={p} />
      </div>
      <div className="space-y-5">
        <Chooser p={p} />
        <InUse p={p} />
        <Docker p={p} />
      </div>
      <Notes />
    </div>
  );
}

function Row({ label, value, source }: { label: string; value: string; source?: string }) {
  return (
    <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-0.5 border-b border-border/60 py-1.5 last:border-0">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="text-right">
        <span className="tabular-nums">{value}</span>
        {source && <span className="ml-2 text-[11px] text-muted-foreground">{source}</span>}
      </dd>
    </div>
  );
}

function Detected({ p }: { p: PerformanceOverview }) {
  const t = useT();
  const h = p.host;
  const known = Object.values(h).some((f) => f.value !== null);
  const model = h.model_name.value ?? h.model_id.value;
  const cores =
    h.performance_cores.value !== null
      ? t("perf.cores.pe", { p: h.performance_cores.value, e: h.efficiency_cores.value ?? 0 })
      : h.physical_cores.value !== null
        ? t("perf.cores.physical", { n: h.physical_cores.value, logical: h.logical_cpus.value ?? "?" })
        : "?";
  const c = p.container;
  const cpuSource = t(c.cpus_source.startsWith("cgroup") ? "perf.source.cpuQuota" : "perf.source.cpuAffinity");
  const memorySource = t(
    c.memory_source?.startsWith("cgroup") ? "perf.source.memoryLimit" : c.memory_source === "macos" ? "perf.source.macos" : "perf.source.memoryTotal",
  );
  return (
    <section aria-labelledby="perf-detected">
      <h3 id="perf-detected" className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">{t("perf.detected")}</h3>
      <dl>
        <Row label={t("perf.fact.model")} value={model ? `${model}${h.model_name.value && h.model_id.value ? ` (${h.model_id.value})` : ""}` : "?"} source={factSource(t, model ? h.model_name.value ? h.model_name : h.model_id : undefined)} />
        <Row label={t("perf.fact.chip")} value={String(h.chip.value ?? "?")} source={factSource(t, h.chip)} />
        <Row label={t("perf.fact.cores")} value={cores} source={factSource(t, h.performance_cores.value !== null ? h.performance_cores : h.physical_cores)} />
        <Row label={t("perf.fact.memory")} value={memoryText(h.memory_bytes.value as number | null)} source={factSource(t, h.memory_bytes)} />
        <Row label={t("perf.fact.os")} value={h.os_version.value ? `${h.os_version.value}${h.arch.value ? ` (${h.arch.value})` : ""}` : "?"} source={factSource(t, h.os_version)} />
        {h.docker_cpus.value !== null && (
          <Row label={t("perf.fact.docker")} value={t("perf.dockerValue", { cpus: h.docker_cpus.value, memory: memoryText(h.docker_memory_bytes.value as number | null) })} source={factSource(t, h.docker_cpus)} />
        )}
        <Row
          label={t("perf.fact.usable")}
          value={t("perf.usableValue", { cpus: c.usable_cpus, memory: memoryText(c.memory_bytes) })}
          source={`${cpuSource}; ${memorySource}${c.in_container ? ` · ${t("perf.inContainer", { marker: c.container_marker ?? "?" })}` : ""}`}
        />
      </dl>
      {!known && <p className="mt-2 rounded-lg bg-muted p-2.5 text-xs text-muted-foreground">{t("perf.hostUnknown")}</p>}
    </section>
  );
}

function Automatic({ p }: { p: PerformanceOverview }) {
  const t = useT();
  const a = p.automatic;
  return (
    <section aria-labelledby="perf-auto" className="space-y-1">
      <h3 id="perf-auto" className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{t("perf.automatic")}</h3>
      <p className="flex flex-wrap items-center gap-2">
        <span className="font-medium">{profileName(t, a.profile)}</span>
        <Badge tone="neutral">{t("perf.heuristic")}</Badge>
      </p>
      <p className="text-xs text-muted-foreground">{t(`perf.reason.${a.reason}` as TranslationKey)}</p>
      <p className="text-xs text-muted-foreground">{t(`perf.basis.${a.core_basis}` as TranslationKey, { n: a.cores })}</p>
    </section>
  );
}

function Chooser({ p }: { p: PerformanceOverview }) {
  const t = useT();
  const qc = useQueryClient();
  const [form, setForm] = useState<ProfileForm>(() => initialForm(p));
  const [saved, setSaved] = useState(false);
  useEffect(() => setForm(initialForm(p)), [p]);
  const save = useMutation({
    mutationFn: api.setPerformance,
    onSuccess: (data) => {
      qc.setQueryData(["performance"], data);
      setSaved(true);
    },
  });
  const { body, problems } = profileRequest(form, p);
  const bounds = customBounds(p);
  const values = Object.fromEntries(p.profiles.map((r) => [r.profile, r]));
  const set = (patch: Partial<ProfileForm>) => {
    setForm((f) => ({ ...f, ...patch }));
    setSaved(false);
  };
  return (
    <section aria-labelledby="perf-choose" className="space-y-3">
      <h3 id="perf-choose" className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{t("perf.choose")}</h3>
      <div role="radiogroup" aria-labelledby="perf-choose" className="grid gap-1.5">
        {PROFILE_CHOICES.map((choice) => {
          const row = values[choice === "auto" ? p.automatic.profile : choice];
          return (
            <label
              key={choice}
              className={cn(
                "flex cursor-pointer items-start gap-2.5 rounded-lg border px-3 py-2",
                form.profile === choice ? "border-arva-teal bg-arva-teal/5" : "hover:bg-muted/60",
              )}
            >
              <input
                type="radio"
                name="performance-profile"
                className="mt-1 accent-[#00B4A6]"
                checked={form.profile === choice}
                onChange={() => set({ profile: choice })}
              />
              <span className="min-w-0 flex-1">
                <span className="flex flex-wrap items-baseline justify-between gap-x-3">
                  <span className="font-medium">{profileName(t, choice)}</span>
                  {row && <span className="text-[11px] tabular-nums text-muted-foreground">{t("perf.profileValues", { threads: row.threads, memory: row.memory_gb, nice: row.nice })}</span>}
                </span>
                <span className="block text-[11px] text-muted-foreground">
                  {choice === "auto" ? t("perf.profileDesc.auto", { profile: profileName(t, p.automatic.profile) }) : t(`perf.profileDesc.${choice}` as TranslationKey)}
                </span>
              </span>
            </label>
          );
        })}
      </div>
      {form.profile === "custom" && (
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label={t("perf.custom.threads")} hint={t("perf.custom.threadsHint", { max: bounds.threads })}>
            <Input type="number" min={1} max={bounds.threads} value={form.threads} onChange={(e) => set({ threads: e.target.value })} />
          </Field>
          <Field label={t("perf.custom.memory")} hint={t("perf.custom.memoryHint", { max: bounds.memory })}>
            <Input type="number" min={1} max={bounds.memory} value={form.memory} onChange={(e) => set({ memory: e.target.value })} />
          </Field>
        </div>
      )}
      {problems.map((k) => (
        <p key={k} className="text-xs text-danger">{t(k, { threads: bounds.threads, memory: bounds.memory })}</p>
      ))}
      <div className="flex flex-wrap items-center gap-3">
        <Button size="sm" disabled={!body || save.isPending} onClick={() => body && save.mutate(body)}>
          {t("perf.save")}
        </Button>
        {saved && <span className="text-xs text-success">{t("perf.saved")}</span>}
      </div>
      {save.error && <ErrorNote error={save.error} />}
    </section>
  );
}

function InUse({ p }: { p: PerformanceOverview }) {
  const t = useT();
  const e = p.effective;
  const caps = [
    e.admin_threads !== null ? `ARVA_TOOL_THREADS=${e.admin_threads}` : null,
    e.admin_memory_gb !== null ? `ARVA_TOOL_MEMORY_GB=${e.admin_memory_gb}` : null,
  ].filter(Boolean);
  const usableMemory = Math.floor(e.usable_memory_gb);
  return (
    <section aria-labelledby="perf-inuse">
      <h3 id="perf-inuse" className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        {t("perf.inUse")}: {profileName(t, e.profile)}{e.choice === "auto" ? ` (${t("perf.profile.auto").toLowerCase()})` : ""}
      </h3>
      <dl>
        <Row label={t("perf.eff.threads")} value={t("perf.eff.threadsValue", { threads: e.threads, max: e.max_threads })} />
        <Row label={t("perf.eff.memory")} value={t("perf.eff.memoryValue", { memory: e.memory_gb, max: e.max_memory_gb })} />
        <Row label={t("perf.eff.priority")} value={t("perf.eff.priorityValue", { nice: e.nice })} />
      </dl>
      {caps.length > 0 && <p className="mt-1 text-xs text-muted-foreground">{t("perf.eff.caps", { caps: caps.join(", ") })}</p>}
      {e.exceeds.length > 0 && (
        <p role="alert" className="mt-2 flex gap-2 rounded-lg bg-warning/10 p-2.5 text-xs">
          <AlertTriangle className="h-4 w-4 shrink-0 text-warning" aria-hidden />
          {t("perf.exceeds", {
            what: e.exceeds
              .map((x) => (x === "threads" ? t("perf.exceeds.threads", { asked: e.requested_threads, usable: e.usable_cpus }) : t("perf.exceeds.memory", { asked: e.requested_memory_gb, usable: usableMemory })))
              .join("; "),
            threads: e.threads,
            memory: e.memory_gb,
          })}
        </p>
      )}
    </section>
  );
}

function Docker({ p }: { p: PerformanceOverview }) {
  const t = useT();
  const d = p.docker;
  const rows: string[] = [];
  if (d.cpus?.status === "increase") rows.push(t("perf.docker.cpuIncrease", { current: d.cpus.current, recommended: d.cpus.recommended }));
  if (d.memory && (d.memory.status === "increase" || d.memory.status === "decrease")) {
    const vars = { current: memoryText(d.memory.current_bytes), recommended: d.memory.recommended_gb, most: d.memory.most_gb };
    rows.push(t(d.memory.status === "increase" ? "perf.docker.memoryIncrease" : "perf.docker.memoryDecrease", vars));
  }
  return (
    <section aria-labelledby="perf-docker" className="space-y-1.5">
      <h3 id="perf-docker" className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        {t("perf.docker.title")} <Explain id="docker_resources" compact />
      </h3>
      {d.status === "ok" && (
        <p className="text-xs">{t("perf.docker.ok", { cpus: d.cpus?.current ?? "?", memory: memoryText(d.memory?.current_bytes) })}</p>
      )}
      {(d.status === "adjust" || d.status === "partial") && (
        <>
          {rows.length > 0 ? (
            <div role="alert" className="space-y-1 rounded-lg bg-warning/10 p-2.5 text-xs">
              <p className="font-medium">{t("perf.docker.adjust")}</p>
              <ul className="list-disc space-y-0.5 pl-4">
                {rows.map((r) => (
                  <li key={r}>{r}</li>
                ))}
              </ul>
              <p>{t("perf.docker.steps")}</p>
            </div>
          ) : (
            <p className="text-xs text-muted-foreground">{t("perf.docker.partial")}</p>
          )}
          <p className="text-[11px] text-muted-foreground">{t("perf.docker.moreCpus")}</p>
        </>
      )}
      {(d.status === "host_unknown" || d.status === "not_container") && (
        <p className="text-xs text-muted-foreground">{t(`perf.docker.${d.status}` as TranslationKey)}</p>
      )}
    </section>
  );
}

function Notes() {
  const t = useT();
  return (
    <ul className="space-y-1.5 text-[11px] text-muted-foreground xl:col-span-2">
      <li>{t("perf.notes.memory")}</li>
      <li>{t("perf.notes.priority")}</li>
      <li>{t("perf.notes.flye")}</li>
      <li>{t("perf.notes.applies")}</li>
    </ul>
  );
}
