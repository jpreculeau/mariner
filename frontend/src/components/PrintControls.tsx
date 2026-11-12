import { useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Loader2, Pause, Play, X } from "lucide-react";
import type { PrinterStatus } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

interface PrintControlsProps {
  status: PrinterStatus;
  /** The file being printed and how far it is, for the question asked
   * before cancelling. */
  fileName: string;
  progress: number;
  onPause: () => Promise<void>;
  onResume: () => Promise<void>;
  onCancel: () => Promise<void>;
}

type Command = "pause" | "resume" | "cancel";

export function PrintControls({
  status,
  fileName,
  progress,
  onPause,
  onResume,
  onCancel,
}: PrintControlsProps) {
  const { t, percent } = useI18n();
  // The command under way: one at a time, and each sent once however
  // often its button is pressed. A button is then said to be unavailable
  // rather than switched off, which would drop the focus it has.
  const [busy, setBusy] = useState<Command | null>(null);
  const [asking, setAsking] = useState(false);
  // Known at once, where `busy` is only once the page is drawn again: two
  // presses can come before that.
  const underWay = useRef(false);

  const run = async (command: Command, send: () => Promise<void>) => {
    if (underWay.current) return;
    underWay.current = true;
    setBusy(command);
    try {
      await send();
    } catch {
      // Whoever sends the command says what went wrong.
    } finally {
      underWay.current = false;
      setBusy(null);
    }
  };

  if (status !== "printing" && status !== "paused") return null;

  const spinner = <Loader2 className="h-4 w-4 animate-spin" aria-hidden />;

  return (
    // Cancelling is set apart from pausing: one cannot be undone.
    <div className="flex flex-wrap items-center justify-between gap-3">
      {status === "printing" ? (
        <Button
          onClick={() => run("pause", onPause)}
          aria-disabled={busy !== null}
          variant="secondary"
          size="lg"
          className="gap-2"
        >
          {busy === "pause" ? (
            spinner
          ) : (
            <Pause className="h-4 w-4" aria-hidden />
          )}
          {busy === "pause" ? t("print.pausing") : t("print.pause")}
        </Button>
      ) : (
        <Button
          onClick={() => run("resume", onResume)}
          aria-disabled={busy !== null}
          size="lg"
          className="gap-2"
        >
          {busy === "resume" ? (
            spinner
          ) : (
            <Play className="h-4 w-4" aria-hidden />
          )}
          {busy === "resume" ? t("print.resuming") : t("print.resume")}
        </Button>
      )}

      <Button
        onClick={() => {
          if (!busy) setAsking(true);
        }}
        aria-disabled={busy !== null}
        variant="destructive"
        size="lg"
        className="gap-2"
      >
        {busy === "cancel" ? spinner : <X className="h-4 w-4" aria-hidden />}
        {busy === "cancel" ? t("print.cancelling") : t("print.cancel")}
      </Button>

      <Dialog open={asking} onOpenChange={setAsking}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>{t("print.cancel.title")}</DialogTitle>
            <DialogDescription>
              {fileName
                ? t("print.cancel.text", {
                    file: fileName,
                    progress: percent(progress, 1),
                  })
                : t("print.cancel.textNoFile", {
                    progress: percent(progress, 1),
                  })}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter className="gap-2 sm:gap-0">
            {/* First, and so the one a hasty Enter lands on. */}
            <Button
              type="button"
              variant="ghost"
              autoFocus
              onClick={() => setAsking(false)}
            >
              {t("print.cancel.keep")}
            </Button>
            <Button
              type="button"
              variant="destructive"
              onClick={() => {
                setAsking(false);
                run("cancel", onCancel);
              }}
            >
              {t("print.cancel.confirm")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
