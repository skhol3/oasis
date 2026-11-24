// The end of a log file for the panel's live server log view (S6): only the last bytes are read,
// so a large server.log costs the same at every refresh. No Pi imports.
import { closeSync, fstatSync, openSync, readSync } from "node:fs";

/** How much of the end of the file is read: far more than an overlay shows. */
export const TAIL_BYTES = 64 * 1024;

/**
 * The last `maxBytes` of the file at `path` as UTF-8, starting at the first whole line inside that
 * window (the whole file when it is smaller); empty when it cannot be read (missing, a directory).
 */
export function readTail(path: string, maxBytes: number = TAIL_BYTES): string {
  let descriptor: number | undefined;
  try {
    descriptor = openSync(path, "r");
    const size = fstatSync(descriptor).size;
    const start = Math.max(0, size - maxBytes);
    const buffer = Buffer.alloc(size - start);
    let read = 0;
    while (read < buffer.length) {
      const count = readSync(descriptor, buffer, read, buffer.length - read, start + read);
      if (count === 0) break;
      read += count;
    }
    const text = buffer.subarray(0, read).toString("utf8");
    if (start === 0) return text;
    const newline = text.indexOf("\n");
    return newline < 0 ? "" : text.slice(newline + 1);
  } catch {
    return "";
  } finally {
    if (descriptor !== undefined) closeSync(descriptor);
  }
}
