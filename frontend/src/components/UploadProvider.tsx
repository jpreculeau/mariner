import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "@/lib/api";
import { errorText, saidByThePage } from "@/lib/errors";
import { useI18n } from "@/lib/i18n";
import { isSupportedKind, isUsableName, supportedKinds } from "@/lib/kinds";
import {
  UploadsContext,
  type RefusedUpload,
  type Sending,
  type Uploads,
} from "@/lib/uploads";
import { toast } from "@/components/ui/sonner";

/**
 * Sends files, one at a time, above the pages: a file goes on being sent,
 * and shown as such, when the reader goes to look at the printer.
 */
export function UploadProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const { t, lang } = useI18n();
  const [sending, setSending] = useState<Sending | null>(null);
  const [refused, setRefused] = useState<RefusedUpload | null>(null);
  // The upload under way, to give it up. Also what says that one is.
  const underWay = useRef<AbortController | null>(null);
  // The words of the moment, for an answer that comes minutes later.
  const words = useRef({ t, lang });
  words.current = { t, lang };

  const upload = useCallback(
    async (file: File, path: string, ignoreUnreachablePrinter: boolean) => {
      // A second upload while one is under way is not taken: if both were
      // refused, the question about the second would replace the first's.
      if (underWay.current) return;
      const giveUp = new AbortController();
      underWay.current = giveUp;
      setRefused(null);
      setSending({ name: file.name, fraction: 0 });
      try {
        await api.uploadFile(
          file,
          path,
          { ignoreUnreachablePrinter },
          (fraction) => setSending({ name: file.name, fraction }),
          giveUp.signal,
        );
        queryClient.invalidateQueries({ queryKey: ["files", path] });
        toast.success(words.current.t("files.uploaded", { file: file.name }));
      } catch (err) {
        const { t, lang } = words.current;
        if (err instanceof ApiError && err.code === "cancelled") {
          // What the reader did, not something that went wrong.
          toast.success(t("files.uploadCancelled"));
        } else if (
          err instanceof ApiError &&
          err.canBeOverridden &&
          !ignoreUnreachablePrinter
        ) {
          // The printer sent nothing back: the reader decides.
          setRefused({ file, path, reason: errorText(err, t, lang) });
        } else {
          // The server says why, e.g. the file is being printed.
          if (!saidByThePage(err)) toast.error(errorText(err, t, lang));
          if (
            err instanceof ApiError &&
            (err.code === "upload_unanswered" || err.code === "folder_gone")
          ) {
            // The file may well be there; or the folder is not, and the
            // list that shows it is old.
            queryClient.invalidateQueries({ queryKey: ["files"] });
          }
        }
      } finally {
        underWay.current = null;
        setSending(null);
      }
    },
    [queryClient],
  );

  // Leaving the page drops the upload: the browser asks first.
  const busy = sending !== null;
  useEffect(() => {
    if (!busy) return;
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [busy]);

  const value = useMemo<Uploads>(
    () => ({
      sending,
      busy,
      start: (file, path) => {
        // What the server would refuse for its name alone, it would
        // refuse only once the whole file had been sent.
        const { t } = words.current;
        if (!isUsableName(file.name)) {
          toast.error(t("error.name_not_allowed"));
        } else if (!isSupportedKind(file.name)) {
          toast.error(
            t("error.type_not_supported", {
              kinds: supportedKinds().join(", "),
            }),
          );
        } else {
          upload(file, path, false);
        }
      },
      cancel: () => underWay.current?.abort(),
      refused,
      confirmRefused: () => {
        if (refused) upload(refused.file, refused.path, true);
      },
      dismissRefused: () => setRefused(null),
    }),
    [sending, busy, refused, upload],
  );

  return (
    <UploadsContext.Provider value={value}>{children}</UploadsContext.Provider>
  );
}
