import { test } from "node:test";
import assert from "node:assert/strict";
import { appendFileSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { readTail } from "../lib/log-tail.ts";

// The live server log view reads only the end of server.log (S6), from a scratch file.
function scratch(): { dir: string; done: () => void } {
  const dir = mkdtempSync(join(tmpdir(), "oasis-log-tail-"));
  return { dir, done: () => rmSync(dir, { recursive: true, force: true }) };
}

test("readTail returns the end of the file, from the first whole line inside the window", () => {
  const { dir, done } = scratch();
  try {
    const log = join(dir, "server.log");
    writeFileSync(log, Array.from({ length: 1000 }, (_, index) => `line ${index + 1}`).join("\n") + "\n");
    const text = readTail(log, 100);
    assert.ok(Buffer.byteLength(text) <= 100);
    assert.match(text, /^line \d+\n/);
    assert.ok(text.endsWith("line 999\nline 1000\n"), text);
    // A small file is returned whole; what is appended later is read on the next call.
    const small = join(dir, "small.log");
    writeFileSync(small, "a\nb\n");
    assert.equal(readTail(small, 100), "a\nb\n");
    appendFileSync(small, "c\n");
    assert.equal(readTail(small, 100), "a\nb\nc\n");
  } finally {
    done();
  }
});

test("readTail of a missing or unreadable path is empty", () => {
  const { dir, done } = scratch();
  try {
    assert.equal(readTail(join(dir, "absent.log"), 100), "");
    assert.equal(readTail(dir, 100), "");
  } finally {
    done();
  }
});

test("readTail shows the cut end of a line longer than the window, marked with an ellipsis", () => {
  const { dir, done } = scratch();
  try {
    const log = join(dir, "server.log");
    // No newline inside the window: the end of the line, not an empty log.
    writeFileSync(log, "start\n" + "x".repeat(200));
    assert.equal(readTail(log, 100), "…" + "x".repeat(100));
    // The only newline ends the window: still the end of that line, with its newline.
    writeFileSync(log, "start\n" + "y".repeat(200) + "\n");
    assert.equal(readTail(log, 100), "…" + "y".repeat(99) + "\n");
    // A window starting inside a multi-byte character skips its remaining bytes.
    writeFileSync(log, "é".repeat(100));
    assert.equal(readTail(log, 51), "…" + "é".repeat(25));
    // A whole line after the cut one is still where the view starts.
    writeFileSync(log, "z".repeat(200) + "\nlast\n");
    assert.equal(readTail(log, 100), "last\n");
  } finally {
    done();
  }
});
