import { vi } from "vitest";

/** What the server is made to answer to one upload. */
export interface Answer {
  status: number;
  statusText?: string;
  body?: string;
  /** Fractions of the file reported as sent before the answer. */
  progress?: number[];
  /** The connection drops instead of an answer. */
  fails?: boolean;
  /** Answer only when the test says so. */
  held?: boolean;
}

/**
 * Stands in for the browser's XMLHttpRequest, which is what tells how much
 * of a file has been sent. Each request takes the next answer in `answers`.
 */
export class FakeXhr {
  static requests: FakeXhr[] = [];
  static answers: Answer[] = [];

  method = "";
  url = "";
  headers: Record<string, string> = {};
  body: unknown = null;
  status = 0;
  statusText = "";
  responseText = "";
  upload: { onprogress: ((event: unknown) => void) | null } = {
    onprogress: null,
  };
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onabort: (() => void) | null = null;
  aborted = false;
  /** Answers held back until `release()`: an upload still under way. */
  static held: (() => void)[] = [];

  abort() {
    this.aborted = true;
    this.onabort?.();
  }

  open(method: string, url: string) {
    this.method = method;
    this.url = url;
  }

  setRequestHeader(name: string, value: string) {
    this.headers[name] = value;
  }

  send(body: unknown) {
    this.body = body;
    FakeXhr.requests.push(this);
    const answer = FakeXhr.answers.shift() ?? { status: 200, body: "{}" };
    const deliver = () => {
      if (this.aborted) return;
      for (const fraction of answer.progress ?? []) {
        this.upload.onprogress?.({
          lengthComputable: true,
          loaded: fraction * 1000,
          total: 1000,
        });
      }
      if (answer.fails) {
        this.onerror?.();
        return;
      }
      this.status = answer.status;
      this.statusText = answer.statusText ?? "";
      this.responseText = answer.body ?? "";
      this.onload?.();
    };
    if (answer.held) FakeXhr.held.push(deliver);
    else queueMicrotask(deliver);
  }
}

/** Put the stand-in in place for a test; answers and requests start empty. */
export function useFakeXhr() {
  FakeXhr.requests = [];
  FakeXhr.answers = [];
  FakeXhr.held = [];
  vi.stubGlobal("XMLHttpRequest", FakeXhr);
}
