import { test } from "node:test";
import assert from "node:assert/strict";
import { parseCommand, SUBCOMMAND_SUMMARY, SUBCOMMANDS, subcommandCompletions, USAGE } from "../lib/commands.ts";

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

test("parseCommand dispatches from the same table as completion and usage", () => {
  assert.deepEqual(parseCommand(""), { kind: "status" });
  assert.deepEqual(parseCommand("   "), { kind: "status" });
  for (const name of ["setup", "doctor", "migrate"] as const) {
    assert.deepEqual(parseCommand(` ${name} `), { kind: "run", name, args: [] });
    assert.deepEqual(parseCommand(`${name} extra`), { kind: "usage" });
  }
  assert.deepEqual(parseCommand("worktree shop feature/shop"), {
    kind: "run", name: "worktree", args: ["shop", "feature/shop"],
  });
  assert.deepEqual(parseCommand("worktree shop"), { kind: "usage" });
  assert.deepEqual(parseCommand("worktree shop --force"), { kind: "usage" });
  assert.deepEqual(parseCommand("worktree a b c"), { kind: "usage" });
  assert.deepEqual(parseCommand("status"), { kind: "usage" });
  assert.equal(USAGE, "Usage: /oasis [setup | doctor | migrate | worktree <feature> <branch>]");
  for (const item of SUBCOMMANDS) assert.ok(SUBCOMMAND_SUMMARY.includes(`\`${item.name}`), item.name);
});
