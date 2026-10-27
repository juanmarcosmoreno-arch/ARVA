import { ExternalLink } from "lucide-react";
import { localized, type GuideEntry } from "@/guide/metrics";
import { useSettings, type GuideLevel } from "@/store/settings";

const LABELS = {
  en: {
    what: "What is this?",
    why: "Why does it matter?",
    how: "How does ARVA compute it?",
    interpret: "How do I interpret the result?",
    next: "What should I do next?",
    mistakes: "Common mistakes",
    limitations: "Limitations",
    advanced: "Methodological detail",
    refs: "Learn more",
  },
  es: {
    what: "¿Qué es?",
    why: "¿Por qué importa?",
    how: "¿Cómo lo calcula ARVA?",
    interpret: "¿Cómo interpreto el resultado?",
    next: "¿Qué hago después?",
    mistakes: "Errores frecuentes",
    limitations: "Limitaciones",
    advanced: "Detalle metodológico",
    refs: "Más información",
  },
};

const RANK: Record<GuideLevel, number> = { beginner: 0, intermediate: 1, advanced: 2 };

export function GuideArticle({ entry, level: levelOverride }: { entry: GuideEntry; level?: GuideLevel }) {
  const language = useSettings((s) => s.language);
  const storedLevel = useSettings((s) => s.guideLevel);
  const level = RANK[levelOverride ?? storedLevel];
  const c = localized(entry, language);
  const L = LABELS[language];

  const Section = ({ title, children }: { title: string; children: React.ReactNode }) => (
    <section className="space-y-1">
      <h4 className="text-xs font-semibold uppercase tracking-wide text-arva-teal">{title}</h4>
      <div className="text-sm leading-relaxed text-foreground/90">{children}</div>
    </section>
  );

  return (
    <div className="space-y-4">
      <Section title={L.what}>{c.what}</Section>
      <Section title={L.why}>{c.why}</Section>
      {level >= 1 && <Section title={L.how}>{c.how}</Section>}
      <Section title={L.interpret}>{c.interpret}</Section>
      <Section title={L.next}>{c.next}</Section>
      <Section title={L.mistakes}>
        <ul className="list-disc space-y-0.5 pl-5">
          {c.mistakes.map((m) => (
            <li key={m}>{m}</li>
          ))}
        </ul>
      </Section>
      {level >= 1 && <Section title={L.limitations}>{c.limitations}</Section>}
      {level >= 2 && c.advanced && (
        <Section title={L.advanced}>
          <p className="rounded-lg bg-muted px-3 py-2 font-mono text-xs">{c.advanced}</p>
        </Section>
      )}
      {level >= 1 && (
        <Section title={L.refs}>
          <ul className="space-y-1">
            {entry.references.map((r) => (
              <li key={r.url}>
                <a
                  href={r.url}
                  target="_blank"
                  rel="noreferrer noopener"
                  className="inline-flex items-start gap-1 text-xs text-arva-royal hover:underline dark:text-arva-cyan"
                >
                  <ExternalLink className="mt-0.5 h-3 w-3 shrink-0" />
                  {r.label}
                </a>
              </li>
            ))}
          </ul>
        </Section>
      )}
    </div>
  );
}
