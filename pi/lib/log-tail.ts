// The end of a log file for the panel's live server log view (S6): only the last bytes are read,
// so a large server.log costs the same at every refresh. No Pi imports.
import { closeSync, fstatSync, openSync, readSync } from "node:fs";

/** How much of the end of the file is read: far more than an overlay shows. */
export const TAIL_BYTES = 64 * 1024;

/** What starts the end of a line cut by the window. */
export const CUT_MARK = "…";

/**
 * The last `maxBytes` of the file at `path` as UTF-8, starting at the first whole line inside that
 * window (the whole file when it is smaller). When no whole line starts inside it (one line longer
 * than the window), the end of that line, marked with `CUT_MARK` and without the bytes of a
 * character cut by the window. Empty when it cannot be read (missing, a directory).
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
    const bytes = buffer.subarray(0, read);
    if (start === 0) return bytes.toString("utf8");
    const newline = bytes.indexOf(0x0a);
    if (newline >= 0 && newline + 1 < bytes.length) return bytes.subarray(newline + 1).toString("utf8");
    // Only the end of one line: skip the continuation bytes of a character the window cut.
    let first = 0;
    while (first < bytes.length && (bytes[first] & 0xc0) === 0x80) first += 1;
    return CUT_MARK + bytes.subarray(first).toString("utf8");
  } catch {
    return "";
  } finally {
    if (descriptor !== undefined) closeSync(descriptor);
  }
}
