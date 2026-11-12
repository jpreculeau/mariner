import { Progress } from "@/components/ui/progress";
import { useI18n } from "@/lib/i18n";

export interface PrintJob {
  fileName: string;
  currentLayer: number;
  totalLayers: number;
  progress: number;
  elapsedTime: number;
  remainingTime: number;
  status: string;
}

interface PrintProgressProps {
  job: PrintJob;
}

export function PrintProgress({ job }: PrintProgressProps) {
  const { t, duration, percent: asPercent } = useI18n();
  // Within the bar's ends, whatever the printer says.
  const progress = Math.min(100, Math.max(0, job.progress));
  const percent = asPercent(progress, 1);

  return (
    <div className="space-y-6">
      {/* Big percentage. The bar below says the same to a screen reader. */}
      <div className="text-center" aria-hidden>
        <span className="font-mono text-6xl font-bold text-primary sm:text-7xl">
          {percent}
        </span>
      </div>

      <Progress
        value={progress}
        aria-label={t("print.progress")}
        aria-valuetext={percent}
        className="h-3 bg-muted"
      />

      {/* Neither time is measured: both come from the percentage. */}
      <dl className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <StatBlock
          label={t("print.currentLayer")}
          value={`${job.currentLayer}`}
        />
        <StatBlock
          label={t("print.totalLayers")}
          value={`${job.totalLayers}`}
        />
        <StatBlock
          label={t("print.elapsed")}
          value={duration(job.elapsedTime)}
        />
        <StatBlock
          label={t("print.remaining")}
          value={duration(job.remainingTime)}
        />
      </dl>

      <div className="rounded-md bg-muted px-3 py-2 text-center">
        <span className="sr-only">{t("print.file")}</span>{" "}
        <span className="break-all font-mono text-sm text-muted-foreground">
          {job.fileName}
        </span>
      </div>
    </div>
  );
}

function StatBlock({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border bg-card p-3 text-center">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="font-mono text-lg font-semibold">{value}</dd>
    </div>
  );
}
