import { test } from "node:test";
import assert from "node:assert/strict";
import { SUBCOMMANDS, subcommandCompletions } from "../lib/commands.ts";

test("subcommandCompletions offers every /oasis subcommand for an empty prefix", () => {
  const items = subcommandCompletions("");
  assert.deepEqual(items?.map((item) => item.value), ["setup", "doctor", "migrate", "worktree "]);
  assert.ok(items?.every((item) => item.label && item.description));
  assert.deepEqual(SUBCOMMANDS.map((item) => item.name), ["setup", "doctor", "migrate", "worktree"]);
});

test("subcommandCompletions filters by prefix and stops after the first word", () => {
  assert.deepEqual(subcommandCompletions("m")?.map((item) => item.value), ["migrate"]);
  assert.deepEqual(subcommandCompletions("  do")?.map((item) => item.value), ["doctor"]);
  assert.equal(subcommandCompletions("x"), null);
  assert.equal(subcommandCompletions("worktree shop"), null);
  assert.equal(subcommandCompletions("setup "), null);
});
