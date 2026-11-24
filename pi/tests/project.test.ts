import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, realpathSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import {
  findProjectRoot, findWorkspaceFile, legacyProfile, notProject, projectContext, projectRootResolver,
} from "../lib/project.ts";

function scratch(): string {
  return realpathSync(mkdtempSync(join(tmpdir(), "oasis-pi-")));
}

// tools/config.py no longer reads a legacy profile but refuses a checkout that has one: outside a
// workspace the directory holding it stays the root, so every command shows that refusal.
test("findProjectRoot without a workspace file walks up to a legacy profile, so its refusal shows", () => {
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

test("findWorkspaceFile and findProjectRoot cross a legacy profile above the checkout, as config.py does", () => {
  const { project, checkout, nested } = workspaceLayout();
  try {
    const codigo = join(project, "codigo");
    writeFileSync(join(codigo, ".odoo19-agent.toml"), "[tooling]\n");
    assert.equal(findWorkspaceFile(nested), join(project, "oasis-workspace.toml"));
    assert.equal(findWorkspaceFile(codigo), join(project, "oasis-workspace.toml"));
    assert.equal(findProjectRoot(nested, () => checkout), checkout);
    assert.equal(legacyProfile(checkout), null);
  } finally {
    rmSync(project, { recursive: true, force: true });
  }
});

test("findProjectRoot keeps a checkout that has its own legacy profile below a workspace file", () => {
  const { project, checkout, nested } = workspaceLayout();
  try {
    const profile = join(checkout, ".odoo19-agent.toml");
    writeFileSync(profile, "[tooling]\n");
    // With git, the checkout is its top level; config.py refuses it there.
    assert.equal(findProjectRoot(nested, () => checkout), checkout);
    // Without git, the directory holding the profile, not the start directory.
    assert.equal(findProjectRoot(nested, () => null), checkout);
    assert.equal(findProjectRoot(nested), checkout);
    assert.equal(legacyProfile(checkout), profile);
    assert.equal(legacyProfile(nested), null);
  } finally {
    rmSync(project, { recursive: true, force: true });
  }
});

test("notProject names the workspace file only", () => {
  assert.equal(notProject("/elsewhere"), "no oasis-workspace.toml at or above /elsewhere");
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

test("projectContext names the root and routes the agent to the oasis tools", () => {
  const text = projectContext("/work/coffee");
  // Without a workspace file the root holds a legacy profile, which no command reads any more.
  assert.match(text, /Odoo project root: \/work\/coffee \(legacy \.odoo19-agent\.toml, no longer read: the user /);
  assert.ok(text.includes("runs /oasis migrate"), text);
  for (const tool of [
    "oasis_test_module",
    "oasis_test_summary",
    "oasis_update_module",
    "oasis_module_status",
    "oasis_check_environment",
    "oasis_lint_module",
    "oasis_find_module",
    "oasis_model_info",
    "oasis_view_info",
    "oasis_xmlid_info",
    "oasis_module_info",
  ]) {
    assert.ok(text.includes(tool), tool);
  }
  // The inactive odoo19_* aliases are not advertised.
  assert.ok(!text.includes("odoo19_"), text);
  assert.ok(text.length < 1200, `context must stay compact, got ${text.length} chars`);
});

test("projectContext keeps the guidance of the test tools: what to pass, and where the logs are", () => {
  const text = projectContext("/work/acme/codigo/acme", "/work/acme/oasis-workspace.toml", undefined, "19.0");
  const lines = text.split("\n");
  const summary = lines.find((line) => line.startsWith("- oasis_test_summary: ")) ?? "";
  assert.ok(summary.includes("pass what test-module --compact printed"), summary);
  const tests = lines.find((line) => line.startsWith("- oasis_test_module: ")) ?? "";
  assert.ok(tests.includes("full logs stay on disk"), tests);
  assert.ok(text.length < 1200, `context must stay compact, got ${text.length} chars`);
});

test("projectContext names the workspace file of the checkout", () => {
  const text = projectContext("/work/acme/codigo/acme", "/work/acme/oasis-workspace.toml");
  assert.match(text, /Odoo project root: \/work\/acme\/codigo\/acme \(workspace \/work\/acme\/oasis-workspace\.toml\)/);
  assert.ok(!text.includes(".odoo19-agent.toml"), text);
  assert.ok(text.length < 1200, `context must stay compact, got ${text.length} chars`);
});

test("projectContext names only the oasis tools the session has", () => {
  const some = projectContext("/work/coffee", null, ["read", "bash", "oasis_model_info", "oasis_lint_module"]);
  assert.ok(some.includes("- oasis_model_info:") && some.includes("- oasis_lint_module:"), some);
  for (const absent of ["oasis_test_module", "oasis_test_summary", "oasis_module_status", "oasis_find_module"]) {
    assert.ok(!some.includes(absent), absent);
  }
  assert.ok(!some.includes("oasis --project"), some);
});

test("projectContext points a session without oasis tools to the guarded CLI", () => {
  const none = projectContext("/work/coffee", null, ["read", "grep"]);
  assert.match(none, /Odoo project root: \/work\/coffee/);
  assert.ok(!none.includes("oasis_"), none);
  assert.ok(none.includes("`oasis --project /work/coffee <command>`"), none);
  assert.ok(none.includes("load the matching Odoo skill first"), none);
});

test("projectContext names the configured Odoo series and its skills", () => {
  const text = projectContext("/work/coffee", null, undefined, "19.0");
  assert.match(text, /^Odoo 19\.0 project root: \/work\/coffee /);
  assert.ok(text.includes("load the matching odoo19-* skill first"), text);
  const other = projectContext("/work/coffee", null, undefined, "15.0");
  assert.match(other, /^Odoo 15\.0 project root: /);
  assert.ok(other.includes("load the matching odoo15-* skill first"), other);
  // Unknown series (the configuration could not be read): no number is made up.
  const unknown = projectContext("/work/coffee");
  assert.match(unknown, /^Odoo project root: /);
  assert.ok(!/odoo\d+-\*/.test(unknown), unknown);
});

test("projectContext tells the agent which oasis commands ask the user, and stays compact", () => {
  const line = "drop-database, stop --database, gc --apply --trash ask the user; never bypass a refusal.";
  for (const tools of [undefined, ["read", "bash"]]) {
    const text = projectContext("/work/acme/codigo/acme", "/work/acme/oasis-workspace.toml", tools, "19.0");
    assert.ok(text.split("\n").includes(line), text);
    assert.ok(text.length < 1200, `context must stay compact, got ${text.length} chars`);
  }
});
