import { useState } from "react";
import { Input, Select } from "@/components/ui/form";
import { useT } from "@/i18n";
import { isoFromParts, partsFromIso } from "@/lib/databases";
import { fmtDayInWords, monthName } from "@/lib/format";
import { useSettings } from "@/store/settings";

const MONTHS = Array.from({ length: 12 }, (_, i) => i + 1);

/** A calendar day typed as day, month (by name) and year, never as one text that a browser could read with day and
 * month swapped (Safari's date field followed the system's order, and "27/05" was stored as 2026-05-07). The day it
 * stands for is written out in words, in the interface language, before anything is registered. `onChange` gets
 * YYYY-MM-DD, or "" while the fields do not make a real day. */
export function DayFields({ value, onChange, label, hint }: { value: string; onChange: (iso: string) => void; label: string; hint?: string }) {
  const t = useT();
  const language = useSettings((s) => s.language);
  const [parts, setParts] = useState(() => partsFromIso(value));
  const iso = isoFromParts(parts.day, parts.month, parts.year);
  const typed = parts.day !== "" || parts.month !== "" || parts.year !== "";
  const set = (part: "day" | "month" | "year", text: string) => {
    const next = { ...parts, [part]: text.replace(/\D/g, "") };
    setParts(next);
    onChange(isoFromParts(next.day, next.month, next.year) ?? "");
  };
  const day = (
    <label key="day" className="w-16 space-y-0.5">
      <span className="block text-muted-foreground">{t("databases.dateDay")}</span>
      <Input inputMode="numeric" maxLength={2} value={parts.day} onChange={(e) => set("day", e.target.value)} aria-invalid={typed && !iso} />
    </label>
  );
  const month = (
    <label key="month" className="min-w-0 flex-1 space-y-0.5 sm:max-w-[11rem]">
      <span className="block text-muted-foreground">{t("databases.dateMonth")}</span>
      <Select value={parts.month} onChange={(e) => set("month", e.target.value)} aria-invalid={typed && !iso}>
        <option value="">—</option>
        {MONTHS.map((m) => (
          <option key={m} value={String(m)}>
            {monthName(m)}
          </option>
        ))}
      </Select>
    </label>
  );
  const year = (
    <label key="year" className="w-24 space-y-0.5">
      <span className="block text-muted-foreground">{t("databases.dateYear")}</span>
      <Input inputMode="numeric" maxLength={4} value={parts.year} onChange={(e) => set("year", e.target.value)} aria-invalid={typed && !iso} />
    </label>
  );
  return (
    <fieldset className="space-y-1 text-xs">
      <legend className="font-medium">{label}</legend>
      <div className="flex flex-wrap items-end gap-2">{language === "en" ? [month, day, year] : [day, month, year]}</div>
      {iso ? (
        <p className="font-medium" aria-live="polite">
          {t("databases.dateReadAs", { date: fmtDayInWords(iso) })}
        </p>
      ) : (
        typed && <p className="text-amber-700 dark:text-warning">{t("databases.dateIncomplete")}</p>
      )}
      {hint && <span className="block text-muted-foreground">{hint}</span>}
    </fieldset>
  );
}
