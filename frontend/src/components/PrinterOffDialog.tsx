import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { useI18n } from "@/lib/i18n";

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
  const { t } = useI18n();
  return (
    <Dialog
      open={reason !== null}
      onOpenChange={(open) => {
        if (!open) onCancel();
      }}
    >
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t("printerOff.title")}</DialogTitle>
          <DialogDescription>{reason}</DialogDescription>
        </DialogHeader>
        <p className="text-base leading-relaxed">{t("printerOff.text")}</p>
        <DialogFooter className="gap-2 sm:gap-0">
          <Button type="button" variant="ghost" onClick={onCancel}>
            {t("common.cancel")}
          </Button>
          <Button type="button" variant="destructive" onClick={onConfirm}>
            {confirmLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
