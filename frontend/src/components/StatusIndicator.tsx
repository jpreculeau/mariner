import { cn } from "@/lib/utils";
import type { PrinterStatus } from "@/lib/api";
import { useI18n, type TextKey } from "@/lib/i18n";

const statusConfig: Record<
  PrinterStatus,
  { label: TextKey; dotClass: string; textClass: string }
> = {
  idle: {
    label: "status.idle",
    dotClass: "bg-success",
    textClass: "text-success",
  },
  printing: {
    label: "status.printing",
    dotClass: "bg-primary animate-pulse-glow",
    textClass: "text-primary",
  },
  paused: {
    label: "status.paused",
    dotClass: "bg-warning",
    textClass: "text-warning",
  },
  offline: {
    label: "status.offline",
    dotClass: "bg-danger",
    textClass: "text-danger",
  },
};

export function StatusIndicator({ status }: { status: PrinterStatus }) {
  const { t } = useI18n();
  const config = statusConfig[status];
  const label = t(config.label);

  return (
    // Announced when it changes: a print that pauses or a printer that
    // stops answering is not only something to see.
    <div
      role="status"
      aria-label={t("status.label", { status: label })}
      className="flex items-center gap-2"
    >
      <div
        className={cn("h-2.5 w-2.5 rounded-full", config.dotClass)}
        aria-hidden
      />
      <span className={cn("font-mono text-sm font-medium", config.textClass)}>
        {label}
      </span>
    </div>
  );
}
