import { useEffect, useRef } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { PrintProgress } from "@/components/PrintProgress";
import { PrintControls } from "@/components/PrintControls";
import { StatusIndicator } from "@/components/StatusIndicator";
import { api, mapPrinterState, type PrinterStatus } from "@/lib/api";
import { errorText } from "@/lib/errors";
import { useI18n, type TextKey } from "@/lib/i18n";
import { usePageTitle } from "@/hooks/use-page-title";
import { focusContent, useFocusWithin } from "@/hooks/use-focus-within";
import { toast } from "@/components/ui/sonner";
import { WifiOff, CheckCircle2, Loader2, Unplug } from "lucide-react";
import { Link } from "react-router-dom";
import { Button } from "@/components/ui/button";

type PrintCommand = "pause_print" | "resume_print" | "cancel_print";

export default function Index() {
  const queryClient = useQueryClient();
  const { t, lang } = useI18n();
  usePageTitle(t("title.dashboard"));
  // The words of the moment, for an answer that comes seconds later.
  const words = useRef({ t, lang });
  words.current = { t, lang };

  const { data, isLoading, error } = useQuery({
    queryKey: ["printStatus"],
    queryFn: () => api.printStatus(),
    refetchInterval: 5000,
  });

  const status: PrinterStatus = data ? mapPrinterState(data.state) : "offline";

  // The buttons of a print go when it is over, and with them the one
  // that may have focus.
  const focus = useFocusWithin();
  useEffect(() => {
    if (focus.lost()) focusContent();
    // `focus` is new at every drawing; what it notes is not.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status]);

  // Send a command to the printer and say how it went: a command the
  // printer did not take must not look like one that it did.
  const send = async (command: PrintCommand, done: TextKey) => {
    try {
      await api.printerCommand(command);
      toast.success(words.current.t(done));
    } catch (failure) {
      toast.error(errorText(failure, words.current.t, words.current.lang));
      throw failure;
    } finally {
      queryClient.invalidateQueries({ queryKey: ["printStatus"] });
    }
  };

  const printerName =
    document
      .querySelector('meta[name="printer-display-name"]')
      ?.getAttribute("content") || undefined;

  const header = (
    <div className="mb-6 flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
      <div>
        <h1 className="text-2xl font-bold">{t("dashboard.heading")}</h1>
        {printerName && (
          <p className="text-sm text-muted-foreground">{printerName}</p>
        )}
      </div>
      {/* Not what Mariner last said once it has stopped answering. */}
      {data && !error && <StatusIndicator status={status} />}
    </div>
  );

  if (isLoading) {
    return (
      <div className="container py-6">
        {header}
        <div
          role="status"
          className="flex flex-col items-center justify-center rounded-lg border bg-card px-6 py-16"
        >
          <Loader2 className="h-8 w-8 animate-spin text-primary" aria-hidden />
          <p className="mt-4 text-sm text-muted-foreground">
            {t("dashboard.connecting")}
          </p>
        </div>
      </div>
    );
  }

  if (error || !data) {
    // Mariner itself did not answer: not the same as a printer that does
    // not, and not the same thing to check.
    return (
      <div className="container py-6">
        {header}
        <div
          role="alert"
          className="flex flex-col items-center justify-center rounded-lg border border-danger/30 bg-destructive/5 px-6 py-16"
        >
          <WifiOff className="h-8 w-8 text-danger" aria-hidden />
          <h2 className="mt-4 text-lg font-semibold">
            {t("dashboard.unreachable.title")}
          </h2>
          <p className="mt-1 max-w-prose text-center text-base leading-relaxed text-muted-foreground">
            {t("dashboard.unreachable.text")}
          </p>
        </div>
      </div>
    );
  }

  const job = {
    fileName: data.selected_file || "",
    currentLayer: data.current_layer ?? 0,
    totalLayers: data.layer_count ?? 0,
    progress: data.progress,
    elapsedTime: data.print_time_secs
      ? data.print_time_secs - (data.time_left_secs ?? 0)
      : 0,
    remainingTime: data.time_left_secs ?? 0,
    status,
  };

  return (
    <div className="container py-6">
      {header}

      {(status === "printing" || status === "paused") && (
        <div className="space-y-6" {...focus.area}>
          <div className="rounded-lg border bg-card p-6">
            <PrintProgress job={job} />
          </div>
          <PrintControls
            status={status}
            fileName={job.fileName}
            progress={job.progress}
            onPause={() => send("pause_print", "print.paused")}
            onResume={() => send("resume_print", "print.resumed")}
            onCancel={() => send("cancel_print", "print.cancelled")}
          />
        </div>
      )}

      {status === "idle" && (
        <div className="flex flex-col items-center justify-center rounded-lg border bg-card px-6 py-16">
          <div className="flex h-16 w-16 items-center justify-center rounded-full bg-success/10">
            <CheckCircle2 className="h-8 w-8 text-success" aria-hidden />
          </div>
          <h2 className="mt-4 text-lg font-semibold">
            {t("dashboard.idle.title")}
          </h2>
          <p className="mt-1 text-center text-base leading-relaxed text-muted-foreground">
            {t("dashboard.idle.text")}
          </p>
          <Button asChild className="mt-4">
            <Link to="/files">{t("dashboard.idle.open")}</Link>
          </Button>
        </div>
      )}

      {status === "offline" && (
        <div className="flex flex-col items-center justify-center rounded-lg border border-danger/30 bg-destructive/5 px-6 py-16">
          <div className="flex h-16 w-16 items-center justify-center rounded-full bg-destructive/10">
            <Unplug className="h-8 w-8 text-danger" aria-hidden />
          </div>
          <h2 className="mt-4 text-lg font-semibold">
            {t("dashboard.offline.title")}
          </h2>
          <p className="mt-1 max-w-prose text-center text-base leading-relaxed text-muted-foreground">
            {t("dashboard.offline.text")}
          </p>
        </div>
      )}
    </div>
  );
}
