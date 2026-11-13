import { useContext, useRef, useState } from "react";
import { Power, PowerOff, RotateCcw } from "lucide-react";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { toast } from "@/components/ui/sonner";
import { AccessContext } from "@/lib/access";
import { api, ApiError } from "@/lib/api";
import { errorText, saidByThePage } from "@/lib/errors";
import { useI18n } from "@/lib/i18n";
import { cn } from "@/lib/utils";

export function PowerMenu() {
  const [confirming, setConfirming] = useState<"shutdown" | "reboot" | null>(
    null,
  );
  const [open, setOpen] = useState(false);
  // What the computer is being asked: once, however often it is pressed.
  const [asking, setAsking] = useState<"shutdown" | "reboot" | null>(null);
  const underWay = useRef(false);
  const { t, lang } = useI18n();
  // Seen from the Internet, the computer refuses both unless its owner
  // allowed them: what would be refused is not offered.
  const allowed = useContext(AccessContext)?.hostCommands ?? true;

  function reset() {
    setConfirming(null);
  }

  async function handleAction(action: "shutdown" | "reboot") {
    // One thing at a time: the other choice is not armed meanwhile for a
    // press that would do nothing.
    if (underWay.current) return;
    if (confirming !== action) {
      setConfirming(action);
      return;
    }
    underWay.current = true;
    setAsking(action);
    try {
      if (action === "shutdown") {
        await api.hostShutdown();
      } else {
        await api.hostReboot();
      }
      toast.success(
        t(action === "shutdown" ? "power.shuttingDown" : "power.rebooting"),
      );
    } catch (error) {
      // The computer answers before it goes down. No answer may be it
      // going down all the same, or it never having been asked: said as
      // such, so that it is not unplugged while running.
      const unanswered = error instanceof ApiError && error.code === "network";
      if (!saidByThePage(error)) {
        toast.error(
          unanswered ? t("power.noAnswer") : errorText(error, t, lang),
        );
      }
    } finally {
      underWay.current = false;
      setAsking(null);
    }
    setOpen(false);
    reset();
  }

  return (
    <Popover
      open={open}
      onOpenChange={(v) => {
        setOpen(v);
        if (!v) reset();
      }}
    >
      <PopoverTrigger asChild>
        <button
          className="flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          aria-label={t("power.open")}
        >
          <Power className="h-4 w-4" aria-hidden />
        </button>
      </PopoverTrigger>
      <PopoverContent
        align="end"
        aria-label={t("power.open")}
        className="w-64 p-2"
      >
        {/* Said aloud: the name of a button that has focus is not read
            again when it changes, and the second press switches the
            computer off. */}
        <p role="status" className="sr-only">
          {asking === "shutdown"
            ? t("power.shutdownAsking")
            : asking === "reboot"
              ? t("power.rebootAsking")
              : confirming === "shutdown"
                ? t("power.shutdownAgain")
                : confirming === "reboot"
                  ? t("power.rebootAgain")
                  : ""}
        </p>
        <p className="mb-2 px-2 text-xs font-medium text-muted-foreground">
          {t("power.heading")}
        </p>
        {!allowed && (
          <p className="px-2 pb-1 text-sm leading-relaxed">
            {t("power.localOnly")}
          </p>
        )}
        {allowed && (
          <div className="space-y-0.5">
            <button
              onClick={() => handleAction("reboot")}
              aria-disabled={asking !== null}
              className={cn(
                "flex w-full items-center gap-3 rounded-md px-2 py-2 text-sm transition-colors",
                confirming === "reboot"
                  ? "bg-destructive/10 font-medium text-danger"
                  : "text-muted-foreground hover:bg-muted/50 hover:text-foreground",
              )}
            >
              <RotateCcw className="h-4 w-4" aria-hidden />
              {asking === "reboot"
                ? t("power.rebootAsking")
                : confirming === "reboot"
                  ? t("power.rebootConfirm")
                  : t("power.reboot")}
            </button>
            <button
              onClick={() => handleAction("shutdown")}
              aria-disabled={asking !== null}
              className={cn(
                "flex w-full items-center gap-3 rounded-md px-2 py-2 text-sm transition-colors",
                confirming === "shutdown"
                  ? "bg-destructive/10 font-medium text-danger"
                  : "text-muted-foreground hover:bg-muted/50 hover:text-foreground",
              )}
            >
              <PowerOff className="h-4 w-4" aria-hidden />
              {asking === "shutdown"
                ? t("power.shutdownAsking")
                : confirming === "shutdown"
                  ? t("power.shutdownConfirm")
                  : t("power.shutdown")}
            </button>
          </div>
        )}
      </PopoverContent>
    </Popover>
  );
}
