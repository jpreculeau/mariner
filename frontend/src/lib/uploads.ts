import { createContext, useContext } from "react";

/** A file being sent, and how much of it has gone: from 0 to 1. */
export interface Sending {
  name: string;
  fraction: number;
}

/** An upload the server refused but that the reader may still confirm. */
export interface RefusedUpload {
  file: File;
  path: string;
  reason: string;
}

export interface Uploads {
  /** The upload under way, if any. One at a time. */
  sending: Sending | null;
  /** Whether another file can be taken now. */
  busy: boolean;
  /** Send a file to a folder. Not taken while another is under way. */
  start: (file: File, path: string) => void;
  /** Give up on the upload under way. */
  cancel: () => void;
  refused: RefusedUpload | null;
  /** Send the refused file all the same: the reader says the printer is off. */
  confirmRefused: () => void;
  dismissRefused: () => void;
}

export const UploadsContext = createContext<Uploads | null>(null);

export function useUploads(): Uploads {
  const uploads = useContext(UploadsContext);
  if (!uploads) throw new Error("useUploads needs an UploadProvider above it");
  return uploads;
}
