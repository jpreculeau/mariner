import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
  DialogDescription,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Play, Layers, Clock, Ruler, Trash2, Loader2 } from "lucide-react";
import { api, ApiError, type FileEntry } from "@/lib/api";
import { errorText } from "@/lib/errors";
import { useI18n } from "@/lib/i18n";
import { PrinterOffDialog } from "@/components/PrinterOffDialog";
import { toast } from "@/components/ui/sonner";

interface FileDetailDialogProps {
  file: FileEntry | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function FileDetailDialog({
  file,
  open,
  onOpenChange,
}: FileDetailDialogProps) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { t, lang, duration, number } = useI18n();
  // Why the server refused a deletion that the user may still confirm. It
  // is always about the file on screen: it is set only for that file, and
  // withdrawn as soon as another one is shown or the dialog is closed.
  const [printerOffReason, setPrinterOffReason] = useState<string | null>(null);
  // Whether the reader is being asked if the file is really to be deleted.
  const [askingToDelete, setAskingToDelete] = useState(false);
  // What is being done to the file: one thing at a time, each asked once
  // however often its button is pressed.
  const [busy, setBusy] = useState<"print" | "delete" | null>(null);

  // The file on screen right now. An answer can come seconds after the
  // request, when the user has closed the dialog or opened another file.
  const shownPath = open && file ? file.path : null;
  const shownPathNow = useRef(shownPath);
  shownPathNow.current = shownPath;

  useEffect(() => {
    setPrinterOffReason(null);
    setAskingToDelete(false);
  }, [shownPath]);

  const { data: details } = useQuery({
    queryKey: ["fileDetails", file?.path],
    queryFn: () => api.fileDetails(file!.path),
    enabled: !!file?.can_be_printed && open,
  });

  if (!file) return null;

  const handlePrint = async () => {
    if (busy) return;
    setBusy("print");
    try {
      await api.printerCommand("start_print", file.path);
    } catch (failure) {
      // The dialog stays open: the reader can read why and try again.
      toast.error(errorText(failure, t, lang));
      return;
    } finally {
      setBusy(null);
    }
    toast.success(t("print.started"));
    onOpenChange(false);
    navigate("/");
  };

  const deleteFile = async (
    path: string,
    name: string,
    ignoreUnreachablePrinter: boolean,
  ) => {
    if (busy) return;
    setPrinterOffReason(null);
    setBusy("delete");
    try {
      await api.deleteFile(path, { ignoreUnreachablePrinter });
    } catch (err) {
      if (
        err instanceof ApiError &&
        err.canBeOverridden &&
        !ignoreUnreachablePrinter &&
        shownPathNow.current === path
      ) {
        // The printer sent nothing back: the user decides.
        setPrinterOffReason(errorText(err, t, lang));
        return;
      }
      // The server says why, e.g. the file is being printed. The dialog
      // stays open so the user can read it and try again.
      toast.error(errorText(err, t, lang));
      return;
    } finally {
      setBusy(null);
    }
    toast.success(t("file.deleted", { file: name }));
    queryClient.invalidateQueries({ queryKey: ["files"] });
    if (shownPathNow.current === path) {
      onOpenChange(false);
    }
  };

  const spinner = <Loader2 className="h-4 w-4 animate-spin" aria-hidden />;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="sm:max-w-md"
        // On the dialog itself, not on its first button: what the file is
        // comes before what can be done with it.
        onOpenAutoFocus={(event) => {
          event.preventDefault();
          (event.currentTarget as HTMLElement).focus();
        }}
      >
        <DialogHeader>
          <DialogTitle className="break-all font-mono text-base">
            {file.filename}
          </DialogTitle>
          <DialogDescription>
            {file.can_be_printed
              ? t("file.details.printable")
              : t("file.details.other")}
          </DialogDescription>
        </DialogHeader>

        {file.can_be_printed && (
          <>
            <div className="mx-auto flex aspect-square max-h-[40vh] w-full max-w-full items-center justify-center overflow-hidden rounded-md border bg-muted">
              <img
                src={api.filePreviewUrl(file.path)}
                alt={t("file.preview")}
                className="h-full w-full object-contain"
                onError={(e) => {
                  const el = e.target as HTMLImageElement;
                  el.style.display = "none";
                }}
              />
            </div>

            {details && (
              <dl className="grid grid-cols-3 gap-3">
                <MetaItem
                  icon={Layers}
                  label={t("file.layers")}
                  value={`${details.layer_count}`}
                />
                <MetaItem
                  icon={Clock}
                  label={t("file.time")}
                  value={duration(details.print_time_secs)}
                />
                <MetaItem
                  icon={Ruler}
                  label={t("file.height")}
                  value={`${number(details.height_mm || details.layer_height_mm * details.layer_count, 1)}\u00a0mm`}
                />
              </dl>
            )}
          </>
        )}

        {/* Apart, and deleting on the quieter side: one cannot be undone. */}
        <DialogFooter className="gap-2 sm:justify-between sm:gap-0">
          <Button
            variant="ghost"
            className="gap-2 text-muted-foreground"
            aria-disabled={busy !== null}
            onClick={() => {
              if (!busy) setAskingToDelete(true);
            }}
          >
            {busy === "delete" ? (
              spinner
            ) : (
              <Trash2 className="h-4 w-4" aria-hidden />
            )}
            {busy === "delete" ? t("file.deleting") : t("file.delete")}
          </Button>
          {file.can_be_printed && (
            <Button
              className="gap-2"
              aria-disabled={busy !== null}
              onClick={handlePrint}
            >
              {busy === "print" ? (
                spinner
              ) : (
                <Play className="h-4 w-4" aria-hidden />
              )}
              {busy === "print" ? t("file.starting") : t("file.print")}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>

      <Dialog open={askingToDelete} onOpenChange={setAskingToDelete}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>{t("file.delete.title")}</DialogTitle>
            <DialogDescription className="break-all">
              {t("file.delete.text", { file: file.filename })}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter className="gap-2 sm:gap-0">
            <Button
              type="button"
              variant="ghost"
              autoFocus
              onClick={() => setAskingToDelete(false)}
            >
              {t("common.cancel")}
            </Button>
            <Button
              type="button"
              variant="destructive"
              onClick={() => {
                setAskingToDelete(false);
                deleteFile(file.path, file.filename, false);
              }}
            >
              {t("file.delete.confirm")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <PrinterOffDialog
        reason={printerOffReason}
        confirmLabel={t("printerOff.delete")}
        onConfirm={() => deleteFile(file.path, file.filename, true)}
        onCancel={() => setPrinterOffReason(null)}
      />
    </Dialog>
  );
}

function MetaItem({
  icon: Icon,
  label,
  value,
}: {
  icon: React.ElementType;
  label: string;
  value: string;
}) {
  return (
    <div className="rounded-md border bg-card p-2 text-center">
      <Icon className="mx-auto h-4 w-4 text-muted-foreground" aria-hidden />
      <dt className="mt-1 text-xs text-muted-foreground">{label}</dt>
      <dd className="font-mono text-sm font-medium">{value}</dd>
    </div>
  );
}
