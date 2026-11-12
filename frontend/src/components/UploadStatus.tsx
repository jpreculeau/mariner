import { useEffect } from "react";
import { X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { PrinterOffDialog } from "@/components/PrinterOffDialog";
import { useI18n } from "@/lib/i18n";
import { useUploads } from "@/lib/uploads";
import { focusContent, useFocusWithin } from "@/hooks/use-focus-within";

/**
 * The upload under way, on whichever page is shown: how far it is, a way
 * to give it up, and the question asked when the printer does not answer.
 */
export function UploadStatus() {
  const { t, percent } = useI18n();
  const { sending, cancel, refused, confirmRefused, dismissRefused } =
    useUploads();
  const done = sending ? Math.round(sending.fraction * 100) : 0;
  // Said a quarter at a time: at every step it would never stop talking.
  const quarter = sending ? Math.floor(sending.fraction * 4) * 25 : 0;
  // All of it has gone: the server still has it to check and store.
  const finishing = sending !== null && sending.fraction >= 1;
  const said = (shown: number) =>
    finishing
      ? t("files.finishing", { file: sending.name })
      : t("files.uploading", {
          file: sending?.name ?? "",
          percent: percent(shown),
        });

  // The bar goes when the upload is over, and with it the button that
  // may have focus.
  const focus = useFocusWithin();
  const shown = sending !== null;
  useEffect(() => {
    // Also when the button to give up goes, the bar staying.
    if (focus.lost()) focusContent();
    if (!shown) focus.forget();
    // `focus` is new at every drawing; what it notes is not.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [shown, finishing]);

  return (
    <>
      {sending && (
        <div className="container pt-4" {...focus.area}>
          <div className="rounded-lg border bg-card p-4">
            {/* On a narrow screen the button goes under the name rather
                than leave it a column one letter wide. */}
            <div className="mb-2 flex flex-wrap items-start justify-between gap-x-3 gap-y-2">
              <p
                className="min-w-[min(100%,12rem)] flex-1 break-all text-sm leading-relaxed"
                aria-hidden
              >
                {said(done)}
              </p>
              {/* Nothing is left to give up once all of it has gone: the
                  server has the file, and stores it. */}
              {!finishing && (
                <Button
                  variant="outline"
                  size="sm"
                  className="shrink-0 gap-1.5"
                  onClick={cancel}
                >
                  <X className="h-3.5 w-3.5" aria-hidden />
                  {t("files.uploadCancel")}
                </Button>
              )}
            </div>
            <Progress
              value={done}
              aria-label={t("files.uploadProgress")}
              aria-valuetext={finishing ? said(done) : percent(done)}
              className="h-2 bg-muted"
            />
            <p role="status" className="sr-only">
              {said(quarter)}
            </p>
          </div>
        </div>
      )}

      <PrinterOffDialog
        reason={refused?.reason ?? null}
        confirmLabel={t("printerOff.replace")}
        onConfirm={confirmRefused}
        onCancel={dismissRefused}
      />
    </>
  );
}
