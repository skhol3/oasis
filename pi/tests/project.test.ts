import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { findProjectRoot, projectContext } from "../lib/project.ts";

function scratch(): string {
  return mkdtempSync(join(tmpdir(), "oasis-pi-"));
}

test("findProjectRoot walks up to the directory holding .odoo19-agent.toml", () => {
  const root = scratch();
  try {
    writeFileSync(join(root, ".odoo19-agent.toml"), "[tooling]\n");
    const nested = join(root, "addons", "coffee", "models");
    mkdirSync(nested, { recursive: true });
    assert.equal(findProjectRoot(nested), root);
    assert.equal(findProjectRoot(root), root);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("findProjectRoot returns null outside an Odoo project", () => {
  const root = scratch();
  try {
    assert.equal(findProjectRoot(root), null);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("projectContext names the root and routes the agent to the odoo19 tools", () => {
  const text = projectContext("/work/coffee");
  assert.match(text, /Odoo 19 project root: \/work\/coffee/);
  for (const tool of [
    "odoo19_test_module",
    "odoo19_module_status",
    "odoo19_check_environment",
    "odoo19_lint_module",
    "odoo19_find_module",
  ]) {
    assert.ok(text.includes(tool), tool);
  }
  assert.ok(text.length < 1200, `context must stay compact, got ${text.length} chars`);
});
