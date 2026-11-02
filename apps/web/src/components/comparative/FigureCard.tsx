import { Download } from "lucide-react";
import { useRef, useState, type ReactNode } from "react";
import { type ChartTheme, useChartTheme } from "@/components/charts/theme";
import { Explain } from "@/components/guide/Explain";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import type { GuideId } from "@/guide/metrics";
import { useT } from "@/i18n";
import { figurePdf } from "@/lib/pdf";
import { type Figure, type FeatureRef, type FigureTheme, textWidth } from "@/lib/regions";

export function figureTheme(theme: ChartTheme): FigureTheme {
  const dark = theme.surface !== "#FFFFFF";
  return { text: theme.text, muted: theme.muted, axis: dark ? "#64748B" : "#475569", link: dark ? "#94A3B8" : "#64748B",
    outline: theme.text, neutral: dark ? "#475569" : "#CBD5E1" };
}

function save(url: string, name: string) {
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
}

/** The figure's primitives as SVG elements; shapes with a reference answer hover and click. */
export function FigureSvg({ fig, svgRef, onHover, onClick, label }: {
  fig: Figure;
  svgRef?: React.RefObject<SVGSVGElement>;
  onHover?: (ref: FeatureRef | null, x: number, y: number) => void;
  onClick?: (ref: FeatureRef) => void;
  label: string;
}) {
  return (
    <svg ref={svgRef} viewBox={`0 0 ${fig.width} ${fig.height}`} width={fig.width} height={fig.height} role="img" aria-label={label}
      fontFamily="Helvetica, Arial, sans-serif" className="h-auto w-full min-w-[760px]" style={{ maxWidth: fig.width }}
      onMouseLeave={() => onHover?.(null, 0, 0)}>
      {fig.prims.map((p, i) => {
        if (p.kind === "line") {
          return <line key={i} x1={p.x1} y1={p.y1} x2={p.x2} y2={p.y2} stroke={p.stroke} strokeWidth={p.width} strokeDasharray={p.dash ? "3 2" : undefined} />;
        }
        if (p.kind === "text") {
          return (
            <text key={i} x={p.x} y={p.y} fontSize={p.size} textAnchor={p.anchor} fill={p.fill} fontStyle={p.italic ? "italic" : undefined}
              fontWeight={p.bold ? 600 : undefined} transform={p.rotate ? `rotate(${p.rotate} ${p.x} ${p.y})` : undefined}>
              {p.text}
            </text>
          );
        }
        const ref = p.ref;
        return (
          <polygon key={i} points={p.points.map(([x, y]) => `${x},${y}`).join(" ")} fill={p.fill} fillOpacity={p.opacity}
            stroke={p.stroke} strokeWidth={p.width} className={ref ? "cursor-pointer" : undefined}
            onMouseMove={ref ? (e) => onHover?.(ref, e.clientX, e.clientY) : undefined}
            onClick={ref ? () => onClick?.(ref) : undefined} />
        );
      })}
    </svg>
  );
}

export type FigureFormat = "svg" | "png" | "pdf";

/** Saves exactly what is drawn: the SVG element (with the surface colour behind it, and the whole figure in view),
 * a PNG at three times the figure's size, or a vector PDF of the same primitives. Elements marked
 * data-export="skip" (hit targets, selection marks) are left out. */
export function downloadFigure(format: FigureFormat, fig: Figure, svg: SVGSVGElement, surface: string, fileStem: string) {
  if (format === "pdf") {
    const bytes = figurePdf(fig, surface, textWidth);
    save(URL.createObjectURL(new Blob([bytes], { type: "application/pdf" })), `${fileStem}.pdf`);
    return;
  }
  const clone = svg.cloneNode(true) as SVGSVGElement;
  clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
  clone.setAttribute("viewBox", `0 0 ${fig.width} ${fig.height}`);
  clone.setAttribute("width", String(fig.width));
  clone.setAttribute("height", String(fig.height));
  clone.removeAttribute("class");
  clone.removeAttribute("style");
  clone.querySelectorAll("[data-export='skip']").forEach((e) => e.remove());
  clone.insertAdjacentHTML("afterbegin", `<rect width="100%" height="100%" fill="${surface}"/>`);
  const text = new XMLSerializer().serializeToString(clone);
  if (format === "svg") {
    save(URL.createObjectURL(new Blob([text], { type: "image/svg+xml" })), `${fileStem}.svg`);
    return;
  }
  const img = new Image();
  const url = URL.createObjectURL(new Blob([text], { type: "image/svg+xml" }));
  img.onload = () => {
    const canvas = document.createElement("canvas");
    canvas.width = fig.width * 3;
    canvas.height = fig.height * 3;
    canvas.getContext("2d")!.drawImage(img, 0, 0, canvas.width, canvas.height);
    URL.revokeObjectURL(url);
    save(canvas.toDataURL("image/png"), `${fileStem}.png`);
  };
  img.src = url;
}

/** A card around a figure with SVG, PNG (3×) and vector PDF export of exactly what is drawn. */
export function FigureCard({ title, subtitle, explain, fileStem, fig, controls, footer, onClick, tooltip }: {
  title: string;
  subtitle?: ReactNode;
  explain?: GuideId;
  fileStem: string;
  fig: Figure;
  controls?: ReactNode;
  footer?: ReactNode;
  onClick?: (ref: FeatureRef) => void;
  tooltip?: (ref: FeatureRef) => ReactNode;
}) {
  const t = useT();
  const theme = useChartTheme();
  const ref = useRef<SVGSVGElement>(null);
  const [hover, setHover] = useState<{ ref: FeatureRef; x: number; y: number } | null>(null);
  const download = (format: FigureFormat) => ref.current && downloadFigure(format, fig, ref.current, theme.surface, fileStem);
  return (
    <Card className="flex flex-col">
      <div className="flex flex-wrap items-start justify-between gap-2 px-5 pt-4">
        <div className="min-w-0">
          <h3 className="text-sm font-semibold">{title}</h3>
          {subtitle && <p className="mt-0.5 text-xs text-muted-foreground">{subtitle}</p>}
        </div>
        <div className="flex items-center gap-1">
          {explain && <Explain id={explain} compact className="p-1.5" />}
          {(["SVG", "PNG (3×)", "PDF"] as const).map((k) => (
            <Button key={k} size="sm" variant="ghost" onClick={() => download(k === "SVG" ? "svg" : k === "PDF" ? "pdf" : "png")}
              aria-label={t("region.export", { format: k })}>
              <Download className="h-3.5 w-3.5" /> {k}
            </Button>
          ))}
        </div>
      </div>
      {controls && <div className="flex flex-wrap items-center gap-3 px-5 pt-3 text-xs">{controls}</div>}
      <div className="relative overflow-x-auto px-3 pb-3 pt-2">
        <FigureSvg fig={fig} svgRef={ref} label={title} onClick={onClick}
          onHover={(r, x, y) => setHover(r ? { ref: r, x, y } : null)} />
        {hover && tooltip && (
          <div className="pointer-events-none fixed z-50 max-w-xs rounded-lg border bg-card px-3 py-2 text-xs shadow-lg"
            style={{ left: hover.x + 14, top: hover.y + 14 }}>
            {tooltip(hover.ref)}
          </div>
        )}
      </div>
      {footer && <div className="space-y-1 px-5 pb-4 text-xs text-muted-foreground">{footer}</div>}
    </Card>
  );
}
