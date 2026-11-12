import { useState, useRef, useEffect } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  api,
  ApiError,
  formatTime,
  type FileEntry,
  type DirectoryEntry,
} from "@/lib/api";
import { FileDetailDialog } from "@/components/FileDetailDialog";
import { PrinterOffDialog } from "@/components/PrinterOffDialog";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Progress } from "@/components/ui/progress";
import { toast } from "@/components/ui/sonner";
import { errorText } from "@/lib/errors";
import { useI18n } from "@/lib/i18n";
import { usePageTitle } from "@/hooks/use-page-title";
import {
  Folder,
  FileText,
  Layers,
  Clock,
  Upload,
  Loader2,
  CornerLeftUp,
  FolderPlus,
  TriangleAlert,
} from "lucide-react";

/**
 * The kinds of file the printer takes, for the file picker: ".ctb,.fdg".
 * Empty when the page was not told, so that every file is offered.
 */
function acceptedFiles(): string {
  const listed =
    document
      .querySelector('meta[name="supported-extensions"]')
      ?.getAttribute("content") || "";
  return listed
    .split(",")
    .map((extension) => extension.trim().replace(/^\./, ""))
    .filter((extension) => /^[a-z0-9]+$/i.test(extension))
    .map((extension) => `.${extension}`)
    .join(",");
}

function FileIcon({ canBePrinted }: { canBePrinted: boolean }) {
  if (canBePrinted)
    return <Layers className="h-4 w-4 shrink-0 text-primary" aria-hidden />;
  return (
    <FileText className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
  );
}

export default function Files() {
  const [currentPath, setCurrentPath] = useState(".");
  const [selectedFile, setSelectedFile] = useState<FileEntry | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [newFolderOpen, setNewFolderOpen] = useState(false);
  const [newFolderName, setNewFolderName] = useState("");
  // An upload the server refused but that the user may still confirm.
  const [refusedUpload, setRefusedUpload] = useState<{
    file: File;
    path: string;
    reason: string;
  } | null>(null);
  // One upload at a time: see upload.
  const [uploading, setUploading] = useState(false);
  // The file being sent and how much of it has gone, from 0 to 1.
  const [sending, setSending] = useState<{
    name: string;
    fraction: number;
  } | null>(null);
  const { t, lang } = useI18n();
  usePageTitle(t("title.files"));
  const fileInputRef = useRef<HTMLInputElement>(null);
  const queryClient = useQueryClient();

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["files", currentPath],
    queryFn: () => api.listFiles(currentPath),
  });

  const createFolderMutation = useMutation({
    mutationFn: (name: string) => api.createDirectory(currentPath, name),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["files", currentPath] });
      toast.success(t("files.newFolder.created"));
      setNewFolderOpen(false);
      setNewFolderName("");
    },
    onError: (err: Error) => {
      toast.error(errorText(err, t, lang));
    },
  });

  useEffect(() => {
    if (!newFolderOpen) setNewFolderName("");
  }, [newFolderOpen]);

  const handleDirectoryClick = (dirname: string) => {
    if (dirname === "..") {
      setCurrentPath((prev) => {
        const parts = prev.split("/").filter(Boolean);
        parts.pop();
        return parts.length === 0 ? "." : parts.join("/");
      });
    } else {
      setCurrentPath((prev) => (prev === "." ? dirname : `${prev}/${dirname}`));
    }
  };

  const handleFileClick = (file: FileEntry) => {
    setSelectedFile(file);
    setDialogOpen(true);
  };

  const upload = async (
    file: File,
    path: string,
    ignoreUnreachablePrinter: boolean,
  ) => {
    // A second upload while one is under way is not taken: if both were
    // refused, the question about the second would replace the first's.
    if (uploading) return;
    setUploading(true);
    setRefusedUpload(null);
    setSending({ name: file.name, fraction: 0 });
    try {
      await api.uploadFile(
        file,
        path,
        { ignoreUnreachablePrinter },
        (fraction) => setSending({ name: file.name, fraction }),
      );
      queryClient.invalidateQueries({ queryKey: ["files", path] });
      toast.success(t("files.uploaded", { file: file.name }));
    } catch (err) {
      if (
        err instanceof ApiError &&
        err.canBeOverridden &&
        !ignoreUnreachablePrinter
      ) {
        // The printer sent nothing back: the user decides.
        setRefusedUpload({ file, path, reason: errorText(err, t, lang) });
        return;
      }
      // The server says why, e.g. the file is being printed.
      toast.error(errorText(err, t, lang));
    } finally {
      setUploading(false);
      setSending(null);
    }
  };

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      await upload(file, currentPath, false);
    } finally {
      // Lets the same file be picked again after a refusal.
      e.target.value = "";
    }
  };

  const handleCreateFolder = () => {
    const name = newFolderName.trim();
    if (!name) return;
    createFolderMutation.mutate(name);
  };

  const shownPath = currentPath === "." ? "/" : `/${currentPath}`;
  const percent = sending ? `${Math.round(sending.fraction * 100)}%` : "";
  const row =
    "flex w-full items-center gap-2 px-3 py-2.5 text-left text-sm transition-colors hover:bg-muted focus-visible:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring";

  return (
    <div className="container py-6">
      <div className="mb-6 flex items-center justify-between gap-4">
        <div className="min-w-0">
          <h1 className="text-2xl font-bold tracking-tight">
            {t("files.heading")}
          </h1>
          <p className="break-all font-mono text-sm text-muted-foreground">
            <span className="sr-only">
              {t("files.folder", { path: shownPath })}
            </span>
            <span aria-hidden>{shownPath}</span>
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <input
            ref={fileInputRef}
            type="file"
            accept={acceptedFiles()}
            className="hidden"
            tabIndex={-1}
            aria-hidden
            onChange={handleUpload}
          />
          {/* On a phone only the icons show: the words stay for those who
              cannot see them. */}
          <Button
            variant="outline"
            size="sm"
            className="gap-1.5"
            onClick={() => setNewFolderOpen(true)}
          >
            <FolderPlus className="h-3.5 w-3.5" aria-hidden />
            <span className="sr-only sm:not-sr-only">
              {t("files.newFolder")}
            </span>
          </Button>
          <Button
            variant="outline"
            size="sm"
            className="gap-1.5"
            disabled={uploading}
            onClick={() => fileInputRef.current?.click()}
          >
            <Upload className="h-3.5 w-3.5" aria-hidden />
            <span className="sr-only sm:not-sr-only">{t("files.upload")}</span>
          </Button>
        </div>
      </div>

      {sending && (
        <div className="mb-4 rounded-lg border bg-card p-4">
          <p className="mb-2 break-all text-sm">
            {t("files.uploading", { file: sending.name, percent })}
          </p>
          <Progress
            value={Math.round(sending.fraction * 100)}
            aria-label={t("files.uploadProgress")}
            aria-valuetext={percent}
            className="h-2 bg-muted"
          />
        </div>
      )}

      <div className="rounded-lg border bg-card">
        {isLoading ? (
          <div role="status" className="flex items-center justify-center py-16">
            <Loader2
              className="h-6 w-6 animate-spin text-primary"
              aria-hidden
            />
            <span className="ml-2 text-sm text-muted-foreground">
              {t("files.loading")}
            </span>
          </div>
        ) : error ? (
          <div
            role="alert"
            className="flex flex-col items-center px-6 py-12 text-center"
          >
            <TriangleAlert className="h-8 w-8 text-danger" aria-hidden />
            <h2 className="mt-3 text-lg font-semibold">
              {t("files.error.title")}
            </h2>
            <p className="mt-1 max-w-prose text-sm text-muted-foreground">
              {errorText(error, t, lang)}
            </p>
            <Button
              variant="outline"
              className="mt-4"
              onClick={() => refetch()}
            >
              {t("files.error.retry")}
            </Button>
          </div>
        ) : (
          <ul className="divide-y">
            {currentPath !== "." && (
              <li>
                <button
                  onClick={() => handleDirectoryClick("..")}
                  aria-label={t("files.up")}
                  className={row}
                >
                  <CornerLeftUp
                    className="h-4 w-4 shrink-0 text-primary"
                    aria-hidden
                  />
                  <span className="font-medium" aria-hidden>
                    ..
                  </span>
                </button>
              </li>
            )}

            {data?.directories.map((dir: DirectoryEntry) => (
              <li key={dir.dirname}>
                <button
                  onClick={() => handleDirectoryClick(dir.dirname)}
                  aria-label={t("files.openFolder", { name: dir.dirname })}
                  className={row}
                >
                  <Folder
                    className="h-4 w-4 shrink-0 text-primary"
                    aria-hidden
                  />
                  <span className="min-w-0 break-all font-medium">
                    {dir.dirname}
                  </span>
                </button>
              </li>
            ))}

            {data?.files.map((file: FileEntry) => (
              <li key={file.filename}>
                <button onClick={() => handleFileClick(file)} className={row}>
                  <FileIcon canBePrinted={file.can_be_printed} />
                  <span className="min-w-0 flex-1 truncate font-mono text-sm">
                    {file.filename}
                  </span>
                  <span className="flex shrink-0 items-center gap-3 text-xs text-muted-foreground">
                    {!!file.print_time_secs && (
                      <span className="hidden items-center gap-1 sm:flex">
                        <Clock className="h-3 w-3" aria-hidden />
                        <span className="sr-only">
                          {t("files.printTime", {
                            time: formatTime(file.print_time_secs),
                          })}
                        </span>
                        <span aria-hidden>
                          {formatTime(file.print_time_secs)}
                        </span>
                      </span>
                    )}
                    {/* Says what the file is; not something to press. */}
                    {file.can_be_printed && (
                      <span className="text-xs font-medium text-primary">
                        {t("files.printable")}
                      </span>
                    )}
                  </span>
                </button>
              </li>
            ))}

            {data &&
              data.directories.length === 0 &&
              data.files.length === 0 && (
                <li className="py-12 text-center text-sm text-muted-foreground">
                  {t("files.empty")}
                </li>
              )}
          </ul>
        )}
      </div>

      <FileDetailDialog
        file={selectedFile}
        open={dialogOpen}
        onOpenChange={setDialogOpen}
      />

      <PrinterOffDialog
        reason={refusedUpload?.reason ?? null}
        confirmLabel={t("printerOff.replace")}
        onConfirm={() => {
          if (refusedUpload) {
            upload(refusedUpload.file, refusedUpload.path, true);
          }
        }}
        onCancel={() => setRefusedUpload(null)}
      />

      <Dialog open={newFolderOpen} onOpenChange={setNewFolderOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>{t("files.newFolder")}</DialogTitle>
            <DialogDescription className="break-all">
              {t("files.newFolder.in", { path: shownPath })}
            </DialogDescription>
          </DialogHeader>
          <form
            className="grid gap-4"
            onSubmit={(event) => {
              event.preventDefault();
              handleCreateFolder();
            }}
          >
            <div className="grid gap-1.5">
              <label htmlFor="new-folder-name" className="text-sm font-medium">
                {t("files.newFolder.name")}
              </label>
              <input
                id="new-folder-name"
                autoFocus
                autoComplete="off"
                value={newFolderName}
                onChange={(e) => setNewFolderName(e.target.value)}
                className="flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm shadow-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              />
            </div>
            <DialogFooter className="gap-2 sm:gap-0">
              <Button
                type="button"
                variant="ghost"
                onClick={() => setNewFolderOpen(false)}
              >
                {t("common.cancel")}
              </Button>
              <Button
                type="submit"
                disabled={
                  !newFolderName.trim() || createFolderMutation.isPending
                }
              >
                {createFolderMutation.isPending ? (
                  <>
                    <Loader2
                      className="mr-1.5 h-3.5 w-3.5 animate-spin"
                      aria-hidden
                    />
                    {t("files.newFolder.creating")}
                  </>
                ) : (
                  t("files.newFolder.create")
                )}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}
