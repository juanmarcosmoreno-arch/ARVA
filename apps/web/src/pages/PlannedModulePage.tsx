import { Construction } from "lucide-react";
import { Link, useParams } from "react-router-dom";
import { ALL_NAV_ITEMS } from "@/components/layout/nav";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { PageHeader } from "@/components/ui/misc";
import { useT } from "@/i18n";

/** Honest placeholder: planned modules are never shown with fake data. */
export function PlannedModulePage() {
  const { key } = useParams();
  const t = useT();
  const item = ALL_NAV_ITEMS.find((i) => i.key === key);
  if (!item) return <NotFoundPage />;
  return (
    <div className="animate-fade-in">
      <PageHeader title={t(item.label)} />
      <Card className="flex flex-col items-center px-6 py-16 text-center">
        <div className="mb-4 rounded-full bg-muted p-4">
          <item.icon className="h-8 w-8 text-arva-royal dark:text-arva-cyan" />
        </div>
        <Badge>
          <Construction className="h-3 w-3" /> {t("common.planned")} · Phase {item.plannedPhase}
        </Badge>
        <p className="mt-4 max-w-lg text-sm text-muted-foreground">{item.description}</p>
        <p className="mt-2 max-w-lg text-xs text-muted-foreground">
          This module is not implemented yet. ARVA does not display simulated results for unavailable analyses.
        </p>
        <Link to="/samples" className="mt-6 text-sm text-arva-royal underline dark:text-arva-cyan">
          Work with available read-level analyses
        </Link>
      </Card>
    </div>
  );
}

export function NotFoundPage() {
  return (
    <div className="py-24 text-center">
      <p className="text-5xl font-semibold text-muted-foreground">404</p>
      <p className="mt-2 text-sm">Page not found.</p>
      <Link to="/" className="mt-4 inline-block text-sm text-arva-royal underline dark:text-arva-cyan">
        Back to dashboard
      </Link>
    </div>
  );
}
