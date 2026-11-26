import { test } from "node:test";
import assert from "node:assert/strict";
import { classifyBash } from "../lib/bash-guard.ts";
import { POLICY } from "../lib/policy.generated.ts";
import { HARNESS, tierOf } from "../lib/policy.ts";

// v0.16.0 S1: the guard takes its tiers from the core policy table (tools/policy.py, generated into
// lib/policy.generated.ts; tests/test_policy.py fails when that module drifts from the table).

test("every example of the table gets its tier's decision: A runs, B asks, C is denied", () => {
  const examples = POLICY.filter((entry) => entry.example !== null);
  assert.ok(examples.length > 20);
  for (const entry of examples) {
    const { programs, asks } = classifyBash(entry.example as string);
    const decision = programs.length > 0 ? "deny" : asks.length > 0 ? "ask" : "allow";
    assert.equal(decision, HARNESS[entry.tier], `${entry.operation} (${entry.tier}): ${entry.example}`);
  }
});

test("tierOf reads the table and refuses an operation it does not list", () => {
  assert.equal(tierOf("setup --apply"), "A");
  assert.equal(tierOf("worktree-init"), "B");
  assert.equal(tierOf("menu"), "C");
  assert.throws(() => tierOf("no such operation"), /not in the oasis policy table/);
});

test("Tier A operations an agent was denied before now run", () => {
  for (const command of [
    "oasis setup --apply",
    "oasis --project /p setup --community $SRC --apply",
    "~/.agents/skills/odoo19/tools/setup --apply",
    "oasis --project /p worktree-init feat feature/x --dry-run",
    "oasis --project /p migrate",
    "oasis --project /p migrate --plan",
  ]) {
    assert.deepEqual(classifyBash(command), { program: null, programs: [], asks: [] }, command);
  }
});

test("Tier B worktree-init and migrate --apply ask instead of being denied", () => {
  const cases: [string, object[]][] = [
    ["oasis --project /p worktree-init feat feature/x", [{ command: "worktree-init", project: "/p" }]],
    ["tools/worktree-init feat x", [{ command: "worktree-init" }]],
    ["python3 -I -B tools/worktree_init.py feat x --dry-run $MORE", [{ command: "worktree-init" }]],
    ["oasis --project /p migrate --apply", [{ command: "migrate --apply", project: "/p" }]],
    ["oasis --project /p migrate $ARGS", [{ command: "migrate --apply", project: "/p" }]],
    ["python3 -I -B ~/.agents/skills/odoo19/tools/migrate.py --apply", [{ command: "migrate --apply" }]],
  ];
  for (const [command, asks] of cases) {
    assert.deepEqual(classifyBash(command), { program: null, programs: [], asks }, command);
  }
});
