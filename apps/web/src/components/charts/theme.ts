import { useEffect, useState } from "react";
import { resolveDark, useSettings } from "@/store/settings";

/**
 * Chart mark colours, validated with the dataviz palette validator
 * (lightness band, chroma, CVD separation, contrast >= 3:1) against each
 * mode's chart surface. Brand hues, stepped per mode — not auto-inverted.
 */
const LIGHT = {
  primary: "#2B54C4",
  secondary: "#008C82",
  surface: "#FFFFFF",
  text: "#0B132B",
  muted: "#64748B",
  grid: "#EEF2F7",
  axis: "#CBD5E1",
};

const DARK = {
  primary: "#4A88EC",
  secondary: "#00AA90",
  surface: "#0E1631",
  text: "#E2E8F0",
  muted: "#94A3B8",
  grid: "#1E2A47",
  axis: "#334155",
};

export type ChartTheme = typeof LIGHT;

export function useChartTheme(): ChartTheme {
  const theme = useSettings((s) => s.theme);
  const [dark, setDark] = useState(() => resolveDark(theme));
  useEffect(() => {
    const update = () => setDark(document.documentElement.classList.contains("dark"));
    update();
    const obs = new MutationObserver(update);
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
    return () => obs.disconnect();
  }, [theme]);
  return dark ? DARK : LIGHT;
}

export function baseOption(t: ChartTheme) {
  return {
    backgroundColor: "transparent",
    textStyle: { fontFamily: "Inter Variable, Inter, system-ui, sans-serif", color: t.muted, fontSize: 11 },
    grid: { left: 56, right: 16, top: 16, bottom: 44, containLabel: false },
    tooltip: {
      backgroundColor: t.surface,
      borderColor: t.axis,
      borderWidth: 1,
      textStyle: { color: t.text, fontSize: 12 },
      extraCssText: "border-radius:8px;box-shadow:0 4px 16px rgba(11,19,43,.12);",
    },
    animationDuration: 300,
  };
}

export function axisStyle(t: ChartTheme, name: string, extra: Record<string, unknown> = {}) {
  return {
    name,
    nameLocation: "middle" as const,
    nameTextStyle: { color: t.muted, fontSize: 11 },
    axisLine: { lineStyle: { color: t.axis } },
    axisTick: { show: false },
    axisLabel: { color: t.muted, fontSize: 10, hideOverlap: true },
    splitLine: { lineStyle: { color: t.grid } },
    ...extra,
  };
}
