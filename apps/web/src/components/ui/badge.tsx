import type { HTMLAttributes } from "react";
import { cn } from "@/lib/utils";

type Tone = "neutral" | "blue" | "teal" | "success" | "warning" | "danger";

const tones: Record<Tone, string> = {
  neutral: "bg-muted text-muted-foreground",
  blue: "bg-arva-royal/10 text-arva-royal dark:bg-arva-cyan/15 dark:text-arva-cyan",
  teal: "bg-arva-teal/10 text-arva-teal",
  success: "bg-success/10 text-success",
  warning: "bg-warning/15 text-amber-700 dark:text-warning",
  danger: "bg-danger/10 text-danger",
};

export function Badge({ tone = "neutral", className, ...props }: HTMLAttributes<HTMLSpanElement> & { tone?: Tone }) {
  return (
    <span
      className={cn("inline-flex shrink-0 items-center gap-1 whitespace-nowrap rounded-full px-2 py-0.5 text-[11px] font-medium", tones[tone], className)}
      {...props}
    />
  );
}
