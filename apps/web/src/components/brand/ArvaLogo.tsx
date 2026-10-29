import { useT } from "@/i18n";
import { cn } from "@/lib/utils";

export function ArvaMark({ className }: { className?: string }) {
  return <img src="/arva-logo.png" alt="" aria-hidden className={cn("h-8 w-8 select-none", className)} />;
}

export function ArvaWordmark({ className, tagline = false }: { className?: string; tagline?: boolean }) {
  const t = useT();
  return (
    <div className={cn("flex items-center gap-2.5", className)}>
      <ArvaMark />
      <div className="leading-none">
        <div className="text-lg font-medium tracking-[0.28em]">ARVA</div>
        {tagline && <div className="mt-1 whitespace-nowrap text-[8px] tracking-[0.14em] opacity-70">{t("brand.tagline")}</div>}
      </div>
    </div>
  );
}
