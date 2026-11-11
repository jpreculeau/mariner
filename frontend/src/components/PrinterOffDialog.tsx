import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";

interface PrinterOffDialogProps {
  /** Why the server refused; shown as is. Null keeps the dialog closed. */
  reason: string | null;
  /** What confirming does, e.g. "Delete anyway". */
  confirmLabel: string;
  onConfirm: () => void;
  onCancel: () => void;
}

/**
 * Asks the user to confirm changing a file although the printer does not
 * answer.
 *
 * The server refuses such a change by default: it cannot tell a printer that
 * is switched off from one that is printing with its cable unplugged. Only
 * the user can, so the decision is theirs, and it is asked every time.
 */
export function PrinterOffDialog({
  reason,
  confirmLabel,
  onConfirm,
  onCancel,
}: PrinterOffDialogProps) {
  return (
    <Dialog
      open={reason !== null}
      onOpenChange={(open) => {
        if (!open) onCancel();
      }}
    >
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Printer not answering</DialogTitle>
          <DialogDescription>{reason}</DialogDescription>
        </DialogHeader>
        <p className="text-sm">
          Go ahead only if the printer is switched off. If it is printing this
          file, the print will be ruined.
        </p>
        <DialogFooter className="gap-2 sm:gap-0">
          <Button type="button" variant="ghost" onClick={onCancel}>
            Cancel
          </Button>
          <Button type="button" variant="destructive" onClick={onConfirm}>
            {confirmLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
