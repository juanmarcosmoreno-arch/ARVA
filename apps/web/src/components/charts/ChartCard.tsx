import type { EChartsOption } from "echarts";
import ReactEChartsCore from "echarts-for-react/lib/core";
import { Download, Table2 } from "lucide-react";
import { useRef, useState, type ReactNode } from "react";
import { Explain } from "@/components/guide/Explain";
import { Card } from "@/components/ui/card";
import type { GuideId } from "@/guide/metrics";
import { cn } from "@/lib/utils";
import { echarts } from "./echarts";
import { useChartTheme } from "./theme";

export interface TableView {
  columns: string[];
  rows: (string | number)[][];
}

function slug(s: string) {
  return s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "");
}

function download(url: string, filename: string) {
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
}

export function ChartCard({
  title,
  subtitle,
  explain,
  option,
  table,
  controls,
  height = 280,
  filePrefix = "arva",
}: {
  title: string;
  subtitle?: ReactNode;
  explain?: GuideId;
  option: EChartsOption;
  table?: TableView;
  controls?: ReactNode;
  height?: number;
  filePrefix?: string;
}) {
  const ref = useRef<ReactEChartsCore>(null);
  const theme = useChartTheme();
  const [showTable, setShowTable] = useState(false);
  const name = `${filePrefix}_${slug(title)}`;

  const exportSvg = () => {
    const url = ref.current?.getEchartsInstance().getDataURL({ type: "svg" });
    if (url) download(url, `${name}.svg`);
  };

  const exportPng = () => {
    const inst = ref.current?.getEchartsInstance();
    const url = inst?.getDataURL({ type: "svg" });
    if (!inst || !url) return;
    const img = new Image();
    img.onload = () => {
      const scale = 3;
      const canvas = document.createElement("canvas");
      canvas.width = inst.getWidth() * scale;
      canvas.height = inst.getHeight() * scale;
      const ctx = canvas.getContext("2d")!;
      ctx.fillStyle = theme.surface;
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
      download(canvas.toDataURL("image/png"), `${name}.png`);
    };
    img.src = url;
  };

  return (
    <Card className="flex flex-col">
      <div className="flex flex-wrap items-start justify-between gap-2 px-5 pt-4">
        <div className="min-w-0">
          <h3 className="text-sm font-semibold">{title}</h3>
          {subtitle && <p className="mt-0.5 text-xs text-muted-foreground">{subtitle}</p>}
        </div>
        <div className="flex items-center gap-1">
          {explain && <Explain id={explain} compact className="p-1.5" />}
          {table && (
            <button
              onClick={() => setShowTable((v) => !v)}
              className={cn("rounded-md p-1.5 text-muted-foreground hover:bg-muted", showTable && "bg-muted text-foreground")}
              aria-pressed={showTable}
              aria-label="Show data table"
              title="Data table"
            >
              <Table2 className="h-3.5 w-3.5" />
            </button>
          )}
          <div className="group relative">
            <button className="rounded-md p-1.5 text-muted-foreground hover:bg-muted" aria-label="Export figure" title="Export figure">
              <Download className="h-3.5 w-3.5" />
            </button>
            <div className="invisible absolute right-0 z-10 mt-1 w-32 rounded-lg border bg-surface py-1 text-xs opacity-0 shadow-lg transition group-focus-within:visible group-focus-within:opacity-100 group-hover:visible group-hover:opacity-100">
              <button className="block w-full px-3 py-1.5 text-left hover:bg-muted" onClick={exportSvg}>
                SVG (vector)
              </button>
              <button className="block w-full px-3 py-1.5 text-left hover:bg-muted" onClick={exportPng}>
                PNG (3×)
              </button>
            </div>
          </div>
        </div>
      </div>
      {controls && <div className="flex flex-wrap gap-2 px-5 pt-3">{controls}</div>}
      <div className="px-2 pb-3 pt-1">
        {showTable && table ? (
          <div className="max-h-[280px] overflow-auto px-3">
            <table className="w-full text-xs">
              <thead className="sticky top-0 bg-surface">
                <tr>
                  {table.columns.map((c) => (
                    <th key={c} className="border-b py-1.5 pr-3 text-left font-medium text-muted-foreground">
                      {c}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {table.rows.map((r, i) => (
                  <tr key={i} className="border-b border-border/50">
                    {r.map((v, j) => (
                      <td key={j} className="py-1 pr-3 tabular-nums">
                        {typeof v === "number" ? v.toLocaleString("en-US") : v}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <ReactEChartsCore
            ref={ref}
            echarts={echarts}
            option={option}
            notMerge
            opts={{ renderer: "svg" }}
            style={{ height, width: "100%" }}
            aria-label={title}
          />
        )}
      </div>
    </Card>
  );
}

export function Segmented<T extends string>({
  value,
  onChange,
  options,
  label,
}: {
  value: T;
  onChange: (v: T) => void;
  options: { value: T; label: string }[];
  label: string;
}) {
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex rounded-lg bg-muted p-0.5 text-xs">
      {options.map((o) => (
        <button
          key={o.value}
          role="radio"
          aria-checked={value === o.value}
          onClick={() => onChange(o.value)}
          className={cn(
            "rounded-md px-2.5 py-1",
            value === o.value ? "bg-surface font-medium shadow-sm" : "text-muted-foreground hover:text-foreground",
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}
