import { Download } from "lucide-react";
import { useRef, type ReactNode } from "react";
import { useChartTheme } from "@/components/charts/theme";
import { Explain } from "@/components/guide/Explain";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import type { GuideId } from "@/guide/metrics";
import { useT } from "@/i18n";

function save(url: string, name: string) {
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
}

/** A card around a hand-drawn SVG figure, with SVG and PNG (3×) export of exactly what is drawn. */
export function SvgFigure({ title, subtitle, explain, fileStem, controls, footer, children }: {
  title: string;
  subtitle?: ReactNode;
  explain?: GuideId;
  fileStem: string;
  controls?: ReactNode;
  footer?: ReactNode;
  children: (ref: React.RefObject<SVGSVGElement>) => ReactNode;
}) {
  const t = useT();
  const theme = useChartTheme();
  const ref = useRef<SVGSVGElement>(null);
  const text = () => {
    if (!ref.current) return null;
    const clone = ref.current.cloneNode(true) as SVGSVGElement;
    clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
    return new XMLSerializer().serializeToString(clone);
  };
  const saveSvg = () => {
    const s = text();
    if (s) save(URL.createObjectURL(new Blob([s], { type: "image/svg+xml" })), `${fileStem}.svg`);
  };
  const savePng = () => {
    const s = text();
    const box = ref.current?.viewBox.baseVal;
    if (!s || !box) return;
    const img = new Image();
    const url = URL.createObjectURL(new Blob([s], { type: "image/svg+xml" }));
    img.onload = () => {
      const canvas = document.createElement("canvas");
      canvas.width = box.width * 3;
      canvas.height = box.height * 3;
      const ctx = canvas.getContext("2d")!;
      ctx.fillStyle = theme.surface;
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
      URL.revokeObjectURL(url);
      save(canvas.toDataURL("image/png"), `${fileStem}.png`);
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
          <Button size="sm" variant="ghost" onClick={saveSvg} aria-label={t("chart.svg")}>
            <Download className="h-3.5 w-3.5" /> SVG
          </Button>
          <Button size="sm" variant="ghost" onClick={savePng}>
            <Download className="h-3.5 w-3.5" /> PNG (3×)
          </Button>
        </div>
      </div>
      {controls && <div className="flex flex-wrap items-center gap-2 px-5 pt-3 text-xs">{controls}</div>}
      <div className="overflow-x-auto px-3 pb-3 pt-2">{children(ref)}</div>
      {footer && <div className="space-y-1 px-5 pb-4 text-xs text-muted-foreground">{footer}</div>}
    </Card>
  );
}
