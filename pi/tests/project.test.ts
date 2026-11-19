import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, realpathSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { findProjectRoot, findWorkspaceFile, projectContext, projectRootResolver } from "../lib/project.ts";

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

test("findProjectRoot resolves a symlinked session directory to the real checkout root", () => {
  const { project, checkout, nested } = workspaceLayout();
  const links = scratch();
  try {
    // The session directory is reached through a link (not resolved here); git reports real paths.
    const link = join(links, "acme-link");
    symlinkSync(project, link);
    const linked = join(link, "codigo", "acme", "addons", "coffee", "models");
    const asked: string[] = [];
    const root = findProjectRoot(linked, (start) => {
      asked.push(start);
      return checkout;
    });
    assert.equal(root, checkout);
    assert.deepEqual(asked, [nested]);
    assert.equal(findProjectRoot(linked, () => null), nested);
    // A link to the checkout itself resolves the same way.
    const checkoutLink = join(links, "checkout-link");
    symlinkSync(checkout, checkoutLink);
    assert.equal(findProjectRoot(join(checkoutLink, "addons"), () => checkout), checkout);
  } finally {
    rmSync(links, { recursive: true, force: true });
    rmSync(project, { recursive: true, force: true });
  }
});

test("findProjectRoot treats only .. segments as outside the workspace directory", () => {
  const { project, nested } = workspaceLayout();
  try {
    // A checkout directory whose name starts with two dots is still inside the workspace.
    const dotted = join(project, "..acme");
    mkdirSync(join(dotted, "addons"), { recursive: true });
    assert.equal(findProjectRoot(join(dotted, "addons"), () => dotted), dotted);
    // The workspace's parent is outside.
    assert.equal(findProjectRoot(nested, () => join(project, "..")), nested);
  } finally {
    rmSync(project, { recursive: true, force: true });
  }
});

test("projectRootResolver retries a failed git lookup and caches a found top level", async () => {
  const { project, checkout, nested } = workspaceLayout();
  try {
    const answers: (string | null)[] = [null, checkout];
    const asked: string[] = [];
    const resolve = projectRootResolver(async (start) => {
      asked.push(start);
      assert.ok(answers.length > 0, "a found top level is cached");
      return answers.shift() ?? null;
    });
    assert.equal(await resolve(nested), nested);
    assert.equal(await resolve(nested), checkout);
    assert.equal(await resolve(nested), checkout);
    assert.deepEqual(asked, [nested, nested]);
    // A profile needs no git lookup.
    const plain = scratch();
    const outside = scratch();
    try {
      writeFileSync(join(plain, ".odoo19-agent.toml"), "[tooling]\n");
      assert.equal(await resolve(plain), plain);
      assert.equal(await resolve(outside), null);
    } finally {
      rmSync(plain, { recursive: true, force: true });
      rmSync(outside, { recursive: true, force: true });
    }
    assert.deepEqual(asked, [nested, nested]);
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
