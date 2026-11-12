import { useState } from "react";
import { Power, PowerOff, RotateCcw } from "lucide-react";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { toast } from "@/components/ui/sonner";
import { api, ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";

export function PowerMenu() {
  const [confirming, setConfirming] = useState<"shutdown" | "reboot" | null>(
    null,
  );
  const [open, setOpen] = useState(false);

  function reset() {
    setConfirming(null);
  }

  async function handleAction(action: "shutdown" | "reboot") {
    if (confirming !== action) {
      setConfirming(action);
      return;
    }
    try {
      if (action === "shutdown") {
        await api.hostShutdown();
      } else {
        await api.hostReboot();
      }
    } catch (error) {
      // A dropped connection is the host going down. An answer is the
      // host saying no.
      if (error instanceof ApiError) {
        toast.error(error.message);
      }
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
          aria-label="Power menu"
        >
          <Power className="h-4 w-4" />
        </button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-48 p-2">
        <p className="mb-2 px-2 text-xs font-medium text-muted-foreground">
          Host Power
        </p>
        <div className="space-y-0.5">
          <button
            onClick={() => handleAction("reboot")}
            className={cn(
              "flex w-full items-center gap-3 rounded-md px-2 py-2 text-sm transition-colors",
              confirming === "reboot"
                ? "bg-destructive/10 font-medium text-destructive"
                : "text-muted-foreground hover:bg-muted/50 hover:text-foreground",
            )}
          >
            <RotateCcw className="h-4 w-4" />
            {confirming === "reboot" ? "Confirm Reboot?" : "Reboot"}
          </button>
          <button
            onClick={() => handleAction("shutdown")}
            className={cn(
              "flex w-full items-center gap-3 rounded-md px-2 py-2 text-sm transition-colors",
              confirming === "shutdown"
                ? "bg-destructive/10 font-medium text-destructive"
                : "text-muted-foreground hover:bg-muted/50 hover:text-foreground",
            )}
          >
            <PowerOff className="h-4 w-4" />
            {confirming === "shutdown" ? "Confirm Shutdown?" : "Shut Down"}
          </button>
        </div>
      </PopoverContent>
    </Popover>
  );
}
