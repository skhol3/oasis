import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, realpathSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { findProjectRoot, findWorkspaceFile, projectContext } from "../lib/project.ts";

function scratch(): string {
  return realpathSync(mkdtempSync(join(tmpdir(), "oasis-pi-")));
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
    assert.equal(findProjectRoot(root, () => assert.fail("no workspace, no git lookup")), null);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

// <project>/oasis-workspace.toml with the checkout <project>/codigo/acme at depth 2.
function workspaceLayout(): { project: string; checkout: string; nested: string } {
  const project = scratch();
  writeFileSync(join(project, "oasis-workspace.toml"), "workspace_version = 1\n");
  const checkout = join(project, "codigo", "acme");
  const nested = join(checkout, "addons", "coffee", "models");
  mkdirSync(nested, { recursive: true });
  return { project, checkout, nested };
}

test("findProjectRoot under a workspace file returns the git top level of the start directory", () => {
  const { project, checkout, nested } = workspaceLayout();
  try {
    const asked: string[] = [];
    const root = findProjectRoot(nested, (start) => {
      asked.push(start);
      return checkout;
    });
    assert.equal(root, checkout);
    assert.deepEqual(asked, [nested]);
  } finally {
    rmSync(project, { recursive: true, force: true });
  }
});

test("findProjectRoot under a workspace file falls back to the start directory", () => {
  const { project, nested } = workspaceLayout();
  try {
    assert.equal(findProjectRoot(nested), nested);
    assert.equal(findProjectRoot(nested, () => null), nested);
    // A top level outside the workspace directory would not find the workspace file again.
    assert.equal(findProjectRoot(nested, () => tmpdir()), nested);
  } finally {
    rmSync(project, { recursive: true, force: true });
  }
});

test("findProjectRoot prefers a profile and never crosses one to reach a workspace file", () => {
  const { project, checkout, nested } = workspaceLayout();
  try {
    const noGit = () => assert.fail("a profile needs no git lookup");
    writeFileSync(join(checkout, ".odoo19-agent.toml"), "[tooling]\n");
    assert.equal(findProjectRoot(nested, noGit), checkout);
    rmSync(join(checkout, ".odoo19-agent.toml"));
    const codigo = join(project, "codigo");
    writeFileSync(join(codigo, ".odoo19-agent.toml"), "[tooling]\n");
    assert.equal(findProjectRoot(nested, noGit), codigo);
    assert.equal(findWorkspaceFile(nested), null);
  } finally {
    rmSync(project, { recursive: true, force: true });
  }
});

test("findWorkspaceFile returns the nearest workspace file at or above the start directory", () => {
  const { project, nested } = workspaceLayout();
  try {
    assert.equal(findWorkspaceFile(nested), join(project, "oasis-workspace.toml"));
    assert.equal(findWorkspaceFile(project), join(project, "oasis-workspace.toml"));
  } finally {
    rmSync(project, { recursive: true, force: true });
  }
});

test("projectContext names the root and routes the agent to the odoo19 tools", () => {
  const text = projectContext("/work/coffee");
  assert.match(text, /Odoo 19 project root: \/work\/coffee \(profile \.odoo19-agent\.toml\)/);
  for (const tool of [
    "odoo19_test_module",
    "odoo19_module_status",
    "odoo19_check_environment",
    "odoo19_lint_module",
    "odoo19_find_module",
    "odoo19_model_info",
  ]) {
    assert.ok(text.includes(tool), tool);
  }
  assert.ok(text.length < 1200, `context must stay compact, got ${text.length} chars`);
});

test("projectContext names the workspace file of a checkout without profile", () => {
  const text = projectContext("/work/acme/codigo/acme", "/work/acme/oasis-workspace.toml");
  assert.match(text, /Odoo 19 project root: \/work\/acme\/codigo\/acme \(workspace \/work\/acme\/oasis-workspace\.toml\)/);
  assert.ok(!text.includes("profile .odoo19-agent.toml"));
  assert.ok(text.length < 1200, `context must stay compact, got ${text.length} chars`);
});
