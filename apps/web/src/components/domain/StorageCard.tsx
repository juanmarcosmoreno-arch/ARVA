import { useQuery } from "@tanstack/react-query";
import { HardDrive } from "lucide-react";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { ErrorNote, Skeleton } from "@/components/ui/misc";
import { useT } from "@/i18n";
import { api } from "@/lib/api";
import { fmtBytes } from "@/lib/format";
import { cn } from "@/lib/utils";

export function StorageCard() {
  const t = useT();
  const storage = useQuery({ queryKey: ["storage"], queryFn: api.storage, refetchInterval: 30_000 });
  const s = storage.data;
  const usedPct = s && s.total_bytes ? Math.min(100, Math.round(100 * (1 - s.free_bytes / s.total_bytes))) : 0;

  return (
    <Card>
      <CardHeader title={t("storage.title")} description={t("storage.subtitle")} action={<HardDrive className="h-4 w-4 text-arva-teal" aria-hidden />} />
      <CardBody className="space-y-3 text-sm">
        {storage.isLoading ? (
          <Skeleton className="h-16" />
        ) : storage.error ? (
          <ErrorNote error={storage.error} />
        ) : (
          s && (
            <>
              <div>
                <div className="font-medium tabular-nums">{t("storage.freeOfTotal", { free: fmtBytes(s.free_bytes), total: fmtBytes(s.total_bytes) })}</div>
                <div
                  role="meter"
                  aria-label={t("storage.title")}
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-valuenow={usedPct}
                  className="mt-2 h-2 overflow-hidden rounded-full bg-muted"
                >
                  <div className={cn("h-full", usedPct >= 90 ? "bg-warning" : "bg-arva-teal")} style={{ width: `${usedPct}%` }} />
                </div>
              </div>
              <div className="flex items-baseline justify-between gap-2">
                <span className="text-xs text-muted-foreground">{t("storage.usable")}</span>
                <span className={cn("font-semibold tabular-nums", s.available_for_data_bytes === 0 && "text-danger")}>{fmtBytes(s.available_for_data_bytes)}</span>
              </div>
              <p className="text-xs text-muted-foreground">{t("storage.reserve", { reserve: fmtBytes(s.min_free_bytes) })}</p>
              <code className="block break-all rounded-md bg-muted px-2 py-1 text-[11px] text-muted-foreground">{s.storage_root}</code>
            </>
          )
        )}
      </CardBody>
    </Card>
  );
}
