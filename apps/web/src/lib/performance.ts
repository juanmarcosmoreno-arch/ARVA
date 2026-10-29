import type { TranslationKey, TranslationVars } from "@/i18n";
import { fmtBytes } from "@/lib/format";
import type { HostFact, JobResources, PerformanceChoice, PerformanceOverview, PerformanceUpdate } from "@/lib/types";

type T = (key: TranslationKey, vars?: TranslationVars) => string;

export const PROFILE_CHOICES: PerformanceChoice[] = ["auto", "light", "balanced", "maximum", "custom"];

export function profileName(t: T, profile: PerformanceChoice) {
  return t(`perf.profile.${profile}` as TranslationKey);
}

export function factSource(t: T, fact: HostFact | undefined) {
  if (!fact || fact.value === null || fact.value === undefined) return t("perf.source.unknown");
  return t(fact.source === "macos" ? "perf.source.macos" : "perf.source.launcher");
}

/** The custom profile's bounds: the CPUs and memory ARVA can use here. */
export function customBounds(p: PerformanceOverview) {
  return { threads: p.container.usable_cpus, memory: Math.max(1, Math.floor(p.effective.usable_memory_gb)) };
}

export interface ProfileForm {
  profile: PerformanceChoice;
  threads: string;
  memory: string;
}

export function initialForm(p: PerformanceOverview): ProfileForm {
  const custom = p.choice.profile === "custom";
  return {
    profile: p.choice.profile,
    threads: String(custom && p.choice.threads ? p.choice.threads : p.effective.threads),
    memory: String(custom && p.choice.memory_gb ? p.choice.memory_gb : p.effective.memory_gb),
  };
}

const whole = (s: string) => (/^\d+$/.test(s.trim()) ? Number(s.trim()) : null);

/** The request to save, or the problems that prevent it (translation keys). */
export function profileRequest(form: ProfileForm, p: PerformanceOverview): { body: PerformanceUpdate | null; problems: TranslationKey[] } {
  if (form.profile !== "custom") return { body: { profile: form.profile }, problems: [] };
  const bounds = customBounds(p);
  const threads = whole(form.threads);
  const memory = whole(form.memory);
  const problems: TranslationKey[] = [];
  if (threads === null || threads < 1 || threads > bounds.threads) problems.push("perf.problem.threads");
  if (memory === null || memory < 1 || memory > bounds.memory) problems.push("perf.problem.memory");
  return problems.length || threads === null || memory === null
    ? { body: null, problems }
    : { body: { profile: "custom", threads, memory_gb: memory }, problems };
}

/** One line describing the resources a job was given. */
export function resourcesLine(t: T, r: JobResources) {
  const parts = [
    t("jobres.profile", { profile: profileName(t, r.profile), how: t(r.choice === "auto" ? "jobres.auto" : "jobres.chosen") }),
  ];
  if (r.threads) parts.push(t("jobres.threads", { n: r.threads }));
  if (r.memory_limit_gb) parts.push(t("jobres.memoryLimit", { gb: r.memory_limit_gb, option: r.memory_option ?? "" }));
  parts.push(r.nice_executable === null ? t("jobres.niceMissing", { nice: r.nice }) : t("jobres.nice", { nice: r.nice }));
  parts.push(t("jobres.usable", { cpus: r.usable_cpus, memory: r.usable_memory_gb }));
  parts.push(t("jobres.host", { host: r.host === "unknown computer" ? t("perf.source.unknown") : r.host }));
  return parts.join(" · ");
}

export function memoryText(bytes: number | null | undefined) {
  return typeof bytes === "number" ? fmtBytes(bytes) : "?";
}
