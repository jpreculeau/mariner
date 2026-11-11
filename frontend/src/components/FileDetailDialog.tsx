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
import { Play, Layers, Clock, Ruler, Trash2 } from "lucide-react";
import { api, ApiError, formatTime, type FileEntry } from "@/lib/api";
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
  // Why the server refused a deletion that the user may still confirm. It
  // is always about the file on screen: it is set only for that file, and
  // withdrawn as soon as another one is shown or the dialog is closed.
  const [printerOffReason, setPrinterOffReason] = useState<string | null>(null);

  // The file on screen right now. An answer can come seconds after the
  // request, when the user has closed the dialog or opened another file.
  const shownPath = open && file ? file.path : null;
  const shownPathNow = useRef(shownPath);
  shownPathNow.current = shownPath;

  useEffect(() => {
    setPrinterOffReason(null);
  }, [shownPath]);

  const { data: details } = useQuery({
    queryKey: ["fileDetails", file?.path],
    queryFn: () => api.fileDetails(file!.path),
    enabled: !!file?.can_be_printed && open,
  });

  if (!file) return null;

  const handlePrint = async () => {
    await api.printerCommand("start_print", file.path);
    onOpenChange(false);
    navigate("/");
  };

  const deleteFile = async (
    path: string,
    ignoreUnreachablePrinter: boolean,
  ) => {
    setPrinterOffReason(null);
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
        setPrinterOffReason(err.message);
        return;
      }
      // The server says why, e.g. the file is being printed. The dialog
      // stays open so the user can read it and try again.
      toast.error(err instanceof Error ? err.message : "Could not delete file");
      return;
    }
    queryClient.invalidateQueries({ queryKey: ["files"] });
    if (shownPathNow.current === path) {
      onOpenChange(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="break-all font-mono text-base">
            {file.filename}
          </DialogTitle>
          <DialogDescription>
            {file.can_be_printed ? "Printable file details" : "File details"}
          </DialogDescription>
        </DialogHeader>

        {file.can_be_printed && (
          <>
            {/* Layer preview */}
            <div className="flex aspect-square w-full items-center justify-center overflow-hidden rounded-md border bg-muted">
              <img
                src={api.filePreviewUrl(file.path)}
                alt="Layer preview"
                className="h-full w-full object-contain"
                onError={(e) => {
                  const el = e.target as HTMLImageElement;
                  el.style.display = "none";
                }}
              />
            </div>

            {/* Metadata */}
            {details && (
              <div className="grid grid-cols-3 gap-3">
                <MetaItem
                  icon={Layers}
                  label="Layers"
                  value={`${details.layer_count}`}
                />
                <MetaItem
                  icon={Clock}
                  label="Est. Time"
                  value={formatTime(details.print_time_secs)}
                />
                <MetaItem
                  icon={Ruler}
                  label="Height"
                  value={`${details.height_mm || (details.layer_height_mm * details.layer_count).toFixed(1)}mm`}
                />
              </div>
            )}
          </>
        )}

        <DialogFooter className="gap-2 sm:gap-0">
          <Button
            variant="ghost"
            className="gap-2 text-muted-foreground"
            onClick={() => deleteFile(file.path, false)}
          >
            <Trash2 className="h-4 w-4" />
            Delete
          </Button>
          {file.can_be_printed && (
            <Button className="gap-2" onClick={handlePrint}>
              <Play className="h-4 w-4" />
              Start Print
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
      <PrinterOffDialog
        reason={printerOffReason}
        confirmLabel="Delete anyway"
        onConfirm={() => deleteFile(file.path, true)}
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
      <Icon className="mx-auto h-4 w-4 text-muted-foreground" />
      <p className="mt-1 text-[10px] text-muted-foreground">{label}</p>
      <p className="font-mono text-sm font-medium">{value}</p>
    </div>
  );
}
