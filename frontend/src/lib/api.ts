export type PrinterStatus = "idle" | "printing" | "paused" | "offline";

export interface PrintStatusResponse {
  state: string;
  selected_file: string;
  progress: number;
  current_layer?: number;
  layer_count?: number;
  print_time_secs?: number;
  time_left_secs?: number;
}

export interface FileEntry {
  filename: string;
  path: string;
  can_be_printed: boolean;
  print_time_secs?: number;
}

export interface DirectoryEntry {
  dirname: string;
}

export interface FileListResponse {
  files: FileEntry[];
  directories: DirectoryEntry[];
}

export interface FileDetailsResponse {
  filename: string;
  path: string;
  bed_size_mm: number[];
  height_mm: number;
  layer_count: number;
  layer_height_mm: number;
  resolution: number[];
  print_time_secs: number;
}

/** Whether a password is set, and whether this page is signed in. */
export interface AuthState {
  password_set: boolean;
  signed_in: boolean;
}

/** The settings that can be changed from the page. */
export interface Settings {
  printer_display_name: string | null;
  uvtools_enabled: boolean;
  sdcp_enabled: boolean;
  assume_printer_off: boolean;
}

export interface SettingsResponse {
  settings: Settings;
  /** A change waits for Mariner to be started again. */
  restart_needed: boolean;
  /** Whether Mariner can be restarted from the page. */
  can_restart: boolean;
}

// The token asked for again since the page was loaded, if any.
let renewedCsrfToken: string | null = null;

function getCsrfToken(): string | null {
  if (renewedCsrfToken) return renewedCsrfToken;
  const meta = document.querySelector('meta[name="csrf-token"]');
  return meta?.getAttribute("content") ?? null;
}

/**
 * Ask for a new token. The one the page was loaded with stops being taken
 * when Mariner restarts or the browser ends its session, which a page left
 * open on a long print can live through.
 */
async function renewCsrfToken(): Promise<boolean> {
  try {
    const res = await fetch("/api/csrf_token");
    if (!res.ok) return false;
    const body = await res.json();
    if (body && typeof body.csrf_token === "string") {
      renewedCsrfToken = body.csrf_token;
      return true;
    }
  } catch {
    // Mariner cannot be reached: the first answer is the one to show.
  }
  return false;
}

async function tokenWasRefused(res: Response): Promise<boolean> {
  if (res.status !== 400) return false;
  try {
    // A copy is read: the answer itself is still to be shown.
    const body = await res.clone().json();
    return body?.code === "token_refused";
  } catch {
    return false;
  }
}

/**
 * Send a request with the page's token. If the token is refused as out of
 * date, get a new one and send the request again, once.
 */
async function fetchWithToken(
  url: string,
  options: RequestInit = {},
): Promise<Response> {
  const send = () => {
    const headers: Record<string, string> = {
      ...(options.headers as Record<string, string>),
    };
    const csrf = getCsrfToken();
    if (csrf) headers["X-CSRFToken"] = csrf;
    return fetch(url, { ...options, headers });
  };
  const res = await send();
  if ((await tokenWasRefused(res)) && (await renewCsrfToken())) {
    return send();
  }
  return res;
}

/**
 * A request the server answered with an error.
 *
 * `message` is the explanation the server gave when it gave one, written to
 * be shown to the user as is. `code` tells apart the cases a screen may want
 * to handle differently, such as `file_in_use` and `printer_not_answering`.
 * `canBeOverridden` is true when repeating the request with
 * `ignoreUnreachablePrinter` can go through: the printer sent nothing back,
 * and the user may know that it is simply switched off.
 */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
    readonly code?: string,
    readonly title?: string,
    readonly canBeOverridden: boolean = false,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/**
 * Build the error for a failed response. The server describes some failures
 * in a JSON body; when it does not, `fallback` is used.
 */
async function errorFrom(res: Response, fallback: string): Promise<ApiError> {
  try {
    const body = await res.json();
    if (body && typeof body.description === "string") {
      return new ApiError(
        res.status,
        body.description,
        body.code,
        body.title,
        body.can_be_overridden === true,
      );
    }
  } catch {
    // No JSON body: an error page, or nothing at all.
  }
  if (res.status === 413) {
    // Past the limit the web server answers before Mariner does, in plain
    // text.
    return new ApiError(
      413,
      "This file is larger than Mariner accepts.",
      "file_too_large",
    );
  }
  return new ApiError(res.status, fallback);
}

/**
 * Send a form with a file in it, telling how much has gone as it goes.
 *
 * Not with `fetch`, which cannot tell: files are hundreds of megabytes,
 * and minutes long over a slow link.
 */
/**
 * How long the answer is waited for once the whole file has gone: the
 * server then copies it into place and writes it out, which takes the
 * longer the larger it is. Five minutes, and a second for every two
 * megabytes.
 */
function answerWait(size: number): number {
  return 5 * 60_000 + (size / (2 * 1024 * 1024)) * 1000;
}

function sendFile(
  url: string,
  body: FormData,
  size: number,
  onProgress?: (fraction: number) => void,
  signal?: AbortSignal,
): Promise<Response> {
  return new Promise((resolve, reject) => {
    // Given up by the reader: not something that went wrong.
    const givenUp = () => new ApiError(0, "Upload cancelled.", "cancelled");
    if (signal?.aborted) {
      reject(givenUp());
      return;
    }
    const request = new XMLHttpRequest();
    // Once the whole file has gone the server stores it whatever the
    // browser does: giving up then would only drop the answer, and leave
    // the page saying that a file which is there was not sent.
    let allSent = false;
    signal?.addEventListener(
      "abort",
      () => {
        if (!allSent) request.abort();
      },
      { once: true },
    );
    // Given up by the reader, unless it is the wait for the answer that
    // ran out.
    let unanswered = false;
    request.onabort = () =>
      reject(
        unanswered
          ? new ApiError(
              0,
              "Mariner did not answer after the file was sent. Look at the list: the file may be there.",
              "upload_unanswered",
            )
          : givenUp(),
      );
    request.open("POST", url);
    const csrf = getCsrfToken();
    if (csrf) request.setRequestHeader("X-CSRFToken", csrf);
    request.upload.onprogress = (event) => {
      if (onProgress && event.lengthComputable && event.total > 0) {
        // Short of all of it, which only `onload` below can tell.
        onProgress(Math.min(event.loaded / event.total, 0.999));
      }
    };
    request.upload.onload = () => {
      allSent = true;
      onProgress?.(1);
      // The server has it to check, copy and write out, which takes a
      // while on a small computer; but not for ever. Without an end the
      // page would show the upload, and take no other, until reloaded.
      const wait = setTimeout(() => {
        unanswered = true;
        request.abort();
      }, answerWait(size));
      request.onloadend = () => clearTimeout(wait);
    };
    request.onload = () => {
      // An answer without content cannot carry any: 204, 304.
      const empty = request.status === 204 || request.status === 304;
      try {
        resolve(
          new Response(empty ? null : request.responseText, {
            status: request.status,
            statusText: request.statusText,
          }),
        );
      } catch {
        // An answer no page can be made of: said, rather than left to
        // show the upload as under way for ever.
        reject(
          new ApiError(request.status, `Upload failed: ${request.status}`),
        );
      }
    };
    request.onerror = () => reject(unreachable());
    request.send(body);
  });
}

/**
 * For changing an existing file. Set once the user, told that the printer
 * does not answer, has confirmed that it is switched off.
 */
export interface FileChangeOptions {
  ignoreUnreachablePrinter?: boolean;
}

/** No answer at all: Mariner is off, or the network between is down. */
function unreachable(): ApiError {
  // What a browser throws then is in its own words, and its own language.
  return new ApiError(0, "Mariner cannot be reached.", "network");
}

// Who is told when the server says that this page is not signed in.
const signedOutListeners = new Set<() => void>();

/**
 * Be told when the server answers that this page is not signed in: its
 * session ended, or the password was changed or cleared from elsewhere.
 * Returns what stops the telling.
 */
export function onSignedOut(listener: () => void): () => void {
  signedOutListeners.add(listener);
  return () => {
    signedOutListeners.delete(listener);
  };
}

/** The same error, after telling whoever listens if it is being signed out. */
function noted(error: ApiError): ApiError {
  if (
    error.status === 401 &&
    (error.code === "login_required" || error.code === "password_not_set")
  ) {
    signedOutListeners.forEach((listener) => listener());
  }
  return error;
}

async function apiFetch<T>(url: string, options: RequestInit = {}): Promise<T> {
  let res: Response;
  try {
    res = await fetchWithToken(url, options);
  } catch {
    throw unreachable();
  }
  if (!res.ok) {
    throw noted(
      await errorFrom(res, `API error: ${res.status} ${res.statusText}`),
    );
  }
  return res.json();
}

/** Send an object as JSON. */
function post<T>(url: string, body?: unknown): Promise<T> {
  return apiFetch<T>(url, {
    method: "POST",
    ...(body === undefined
      ? {}
      : {
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        }),
  });
}

/**
 * Send what signs in. The answer carries the token of the new session:
 * the one the page held went with the session it had.
 */
async function signedInBy(url: string, body?: unknown): Promise<void> {
  const answer = await post<{ csrf_token?: string }>(url, body);
  if (typeof answer?.csrf_token === "string") {
    renewedCsrfToken = answer.csrf_token;
  }
}

export const api = {
  async authState(): Promise<AuthState> {
    return apiFetch<AuthState>("/api/auth/state");
  },

  /** Choose the password, when there is none yet. Signs in. */
  async choosePassword(password: string): Promise<void> {
    await signedInBy("/api/auth/setup", { password });
  },

  async signIn(password: string): Promise<void> {
    await signedInBy("/api/auth/login", { password });
  },

  async signOut(): Promise<void> {
    // The answer carries a token for what comes next: signing in again.
    await signedInBy("/api/auth/logout", undefined);
  },

  /** Replace the password. Every other page is signed out. */
  async changePassword(current: string, next: string): Promise<void> {
    await signedInBy("/api/auth/password", { current, new: next });
  },

  async settings(): Promise<SettingsResponse> {
    return apiFetch<SettingsResponse>("/api/settings");
  },

  async saveSettings(changes: Partial<Settings>): Promise<SettingsResponse> {
    return post<SettingsResponse>("/api/settings", changes);
  },

  async restart(): Promise<void> {
    await post("/api/restart");
  },

  async printStatus(): Promise<PrintStatusResponse> {
    return apiFetch<PrintStatusResponse>("/api/print_status");
  },

  async listFiles(path: string = "."): Promise<FileListResponse> {
    return apiFetch<FileListResponse>(
      `/api/list_files?path=${encodeURIComponent(path)}`,
    );
  },

  async fileDetails(filename: string): Promise<FileDetailsResponse> {
    return apiFetch<FileDetailsResponse>(
      `/api/file_details?filename=${encodeURIComponent(filename)}`,
    );
  },

  filePreviewUrl(filename: string): string {
    return `/api/file_preview?filename=${encodeURIComponent(filename)}`;
  },

  async uploadFile(
    file: File,
    path: string = ".",
    options: FileChangeOptions = {},
    onProgress?: (fraction: number) => void,
    signal?: AbortSignal,
  ): Promise<void> {
    const formData = new FormData();
    formData.append("file", file);
    const q = new URLSearchParams({ path });
    if (options.ignoreUnreachablePrinter) {
      q.set("ignore_unreachable_printer", "1");
    }
    const url = `/api/upload_file?${q.toString()}`;
    // A file refused for its token has been sent whole by then, and would
    // be sent whole again: make sure of the token first.
    await renewCsrfToken();
    let res = await sendFile(url, formData, file.size, onProgress, signal);
    if ((await tokenWasRefused(res)) && (await renewCsrfToken())) {
      res = await sendFile(url, formData, file.size, onProgress, signal);
    }
    if (!res.ok) {
      throw noted(await errorFrom(res, `Upload failed: ${res.status}`));
    }
  },

  async deleteFile(
    filename: string,
    options: FileChangeOptions = {},
  ): Promise<void> {
    const q = new URLSearchParams({ filename });
    if (options.ignoreUnreachablePrinter) {
      q.set("ignore_unreachable_printer", "1");
    }
    await apiFetch(`/api/delete_file?${q.toString()}`, { method: "POST" });
  },

  async createDirectory(parentPath: string, name: string): Promise<void> {
    const params = new URLSearchParams({
      path: parentPath,
      name,
    });
    await apiFetch(`/api/create_directory?${params.toString()}`, {
      method: "POST",
    });
  },

  async hostShutdown(): Promise<void> {
    await apiFetch("/api/host/shutdown", { method: "POST" });
  },

  async hostReboot(): Promise<void> {
    await apiFetch("/api/host/reboot", { method: "POST" });
  },

  async printerCommand(
    command: "start_print" | "pause_print" | "resume_print" | "cancel_print",
    filename?: string,
  ): Promise<void> {
    const params = filename ? `?filename=${encodeURIComponent(filename)}` : "";
    await apiFetch(`/api/printer/command/${command}${params}`, {
      method: "POST",
    });
  },
};

/**
 * Whether to ask again after a failure. Not when the server said no: it
 * would say so again, and the reader would wait for it three times over.
 */
export function shouldRetry(failures: number, error: unknown): boolean {
  if (error instanceof ApiError && error.status >= 400 && error.status < 500) {
    return false;
  }
  return failures < 3;
}

export function mapPrinterState(state: string): PrinterStatus {
  switch (state) {
    case "PRINTING":
    case "STARTING_PRINT":
      return "printing";
    case "PAUSED":
      return "paused";
    case "CLOSED":
      return "offline";
    default:
      return "idle";
  }
}

export function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
