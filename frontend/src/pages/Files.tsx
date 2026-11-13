import { useState, useRef, useEffect } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError, type FileEntry, type DirectoryEntry } from "@/lib/api";
import { FileDetailDialog } from "@/components/FileDetailDialog";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { toast } from "@/components/ui/sonner";
import { errorText, saidByThePage } from "@/lib/errors";
import { useI18n } from "@/lib/i18n";
import { useUploads } from "@/lib/uploads";
import { usePageTitle } from "@/hooks/use-page-title";
import { useFocusWithin } from "@/hooks/use-focus-within";
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
  // Why the folder asked for could not be made, until the name changes.
  const [folderError, setFolderError] = useState<string | null>(null);
  // Uploads live above the pages: one goes on when another page is shown.
  const uploads = useUploads();
  const { t, lang, duration } = useI18n();
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
      // By the field it is about, where it is read and stays; and back
      // to that field, to change the name.
      setFolderError(errorText(err, t, lang));
      document.getElementById("new-folder-name")?.focus();
    },
  });

  useEffect(() => {
    if (!newFolderOpen) setNewFolderName("");
    setFolderError(null);
  }, [newFolderOpen]);

  // When what is shown changes (another folder, an error, a new try) and
  // focus was on something that went with it, put focus on the list
  // rather than let it fall to the top of the page. Not when focus was
  // not in the page: nothing was lost.
  const listRef = useRef<HTMLDivElement>(null);
  const focus = useFocusWithin();
  useEffect(() => {
    if (focus.lost()) listRef.current?.focus();
    // `focus` is new at every drawing; what it notes is not.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, error, isLoading]);

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

  const handleUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    uploads.start(file, currentPath);
    // Lets the same file be picked again after a refusal.
    e.target.value = "";
  };

  const handleCreateFolder = () => {
    const name = newFolderName.trim();
    if (!name || createFolderMutation.isPending) return;
    createFolderMutation.mutate(name);
  };

  const shownPath = currentPath === "." ? "/" : `/${currentPath}`;
  const row =
    "flex w-full items-center gap-2 px-3 py-2.5 text-left text-sm transition-colors hover:bg-muted focus-visible:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring";

  return (
    <div className="container py-6" {...focus.area}>
      <div className="mb-6 flex items-center justify-between gap-4">
        <div className="min-w-0">
          <h1 className="text-2xl font-bold">{t("files.heading")}</h1>
          <p
            className="break-all font-mono text-sm text-muted-foreground"
            aria-hidden
          >
            {shownPath}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <input
            ref={fileInputRef}
            type="file"
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
            aria-disabled={uploads.busy}
            onClick={() => {
              if (!uploads.busy) fileInputRef.current?.click();
            }}
          >
            <Upload className="h-3.5 w-3.5" aria-hidden />
            <span className="sr-only sm:not-sr-only">{t("files.upload")}</span>
          </Button>
        </div>
      </div>

      {/* Where focus goes when the list changes under it: the row that
          was pressed is gone with the folder it was in. */}
      <div
        ref={listRef}
        tabIndex={-1}
        role="region"
        aria-label={t("files.folder", { path: shownPath })}
        className="rounded-lg border bg-card focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
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
        ) : saidByThePage(error) ? null : error ? (
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
            {currentPath !== "." && (
              // The folder may be gone: a way out other than reloading.
              <Button
                variant="ghost"
                className="mt-2 h-auto min-h-10 gap-2 whitespace-normal"
                onClick={() => handleDirectoryClick("..")}
              >
                <CornerLeftUp className="h-4 w-4" aria-hidden />
                {t("files.up")}
              </Button>
            )}
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
                  <span className="min-w-0 flex-1 break-all font-mono text-sm">
                    {file.filename}
                  </span>
                  <span className="flex shrink-0 items-center gap-3 text-xs text-muted-foreground">
                    {!!file.print_time_secs && (
                      <span className="hidden items-center gap-1 sm:flex">
                        <Clock className="h-3 w-3" aria-hidden />
                        <span className="sr-only">
                          {t("files.printTime", {
                            time: duration(file.print_time_secs),
                          })}
                        </span>
                        <span aria-hidden>
                          {duration(file.print_time_secs)}
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
                aria-invalid={folderError !== null}
                aria-describedby={folderError ? "new-folder-error" : undefined}
                onChange={(e) => {
                  setNewFolderName(e.target.value);
                  setFolderError(null);
                }}
                className="flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm shadow-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              />
              {folderError && (
                <p
                  id="new-folder-error"
                  role="alert"
                  className="text-sm leading-relaxed text-danger"
                >
                  {folderError}
                </p>
              )}
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
                disabled={!newFolderName.trim()}
                // Said to be unavailable while it works rather than
                // switched off, which would drop the focus it has.
                aria-disabled={createFolderMutation.isPending}
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
