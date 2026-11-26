import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, readFileSync, realpathSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { tmpdir } from "node:os";
import { dirname, join, relative as relativePath } from "node:path";
import { fileURLToPath } from "node:url";
import {
  findProjectRoot, findWorkspaceFile, legacyProfile, notProject, projectContext, projectRootResolver,
  planConfirmation,
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
    // Without git, the directory holding .git, as git finds it; the profile never picks the root.
    writeFileSync(join(checkout, ".git"), "gitdir: /elsewhere\n");
    assert.equal(findProjectRoot(nested, () => null), checkout);
    assert.equal(findProjectRoot(nested), checkout);
    assert.equal(legacyProfile(checkout), profile);
    assert.equal(legacyProfile(nested), null);
  } finally {
    rmSync(project, { recursive: true, force: true });
  }
});

// Without git (or with a top level outside the workspace directory) the root is the directory
// git would report: the nearest one holding .git, from the start directory up to the workspace
// directory, else the start directory. A legacy profile on the way never becomes the root:
// tools/config.py checks only <root>/.odoo19-agent.toml and crosses every other one.
test("findProjectRoot without git crosses a legacy profile between the workspace and the checkout", () => {
  const { project, checkout, nested } = workspaceLayout();
  try {
    const codigo = join(project, "codigo");
    writeFileSync(join(codigo, ".odoo19-agent.toml"), "[tooling]\n");
    const noGit = [undefined, () => null, () => tmpdir(), () => join(project, "..")];
    // No .git: the start directory, as with no profile at all.
    for (const gitTopLevel of noGit) assert.equal(findProjectRoot(nested, gitTopLevel), nested);
    // A checkout holding .git (a directory, or a linked worktree's file): that checkout.
    mkdirSync(join(checkout, ".git"));
    for (const gitTopLevel of noGit) assert.equal(findProjectRoot(nested, gitTopLevel), checkout);
    assert.equal(legacyProfile(checkout), null);
    // Started in the directory holding the profile, that directory is the root and config.py refuses it.
    for (const gitTopLevel of noGit) assert.equal(findProjectRoot(codigo, gitTopLevel), codigo);
    // The workspace directory itself may be the checkout.
    rmSync(join(checkout, ".git"), { recursive: true });
    mkdirSync(join(project, ".git"));
    for (const gitTopLevel of noGit) assert.equal(findProjectRoot(nested, gitTopLevel), project);
  } finally {
    rmSync(project, { recursive: true, force: true });
  }
  // A repository holding the workspace directory: its .git, above the workspace, is not a root
  // (the workspace file is below it), with or without git reporting that top level.
  const outer = scratch();
  try {
    mkdirSync(join(outer, ".git"));
    const workspace = join(outer, "ws");
    const codigo = join(workspace, "codigo");
    const start = join(codigo, "acme", "addons");
    mkdirSync(start, { recursive: true });
    writeFileSync(join(workspace, "oasis-workspace.toml"), "workspace_version = 1\n");
    writeFileSync(join(codigo, ".odoo19-agent.toml"), "[tooling]\n");
    for (const gitTopLevel of [() => outer, () => null]) assert.equal(findProjectRoot(start, gitTopLevel), start);
  } finally {
    rmSync(outer, { recursive: true, force: true });
  }
});

// The extension's before_agent_start handler names the workspace file only for a root without its
// own legacy profile: projectContext then says the profile is no longer read.
test("before_agent_start passes projectContext the workspace file, or null for a root with a legacy profile", () => {
  const source = readFileSync(new URL("../extensions/oasis.ts", import.meta.url), "utf8");
  const handler = source.match(/pi\.on\("before_agent_start", async \(event, ctx\) => \{[^]*?\n {2}\}\);\n/);
  assert.ok(handler, "before_agent_start handler");
  const flat = handler[0].split(/\s+/).join(" ");
  for (const part of [
    "const root = await projectRoot(ctx.cwd); if (!root) return;",
    "const workspace = legacyProfile(root) ? null : findWorkspaceFile(root);",
    "const context = projectContext(root, workspace, pi.getActiveTools(), await projectVersion(root));",
  ]) {
    assert.ok(flat.includes(part), part);
  }
  // What each branch gives projectContext.
  const { project, checkout } = workspaceLayout();
  try {
    const workspace = join(project, "oasis-workspace.toml");
    assert.equal(legacyProfile(checkout) ? null : findWorkspaceFile(checkout), workspace);
    assert.ok(projectContext(checkout, workspace).includes(`(workspace ${workspace}).`));
    writeFileSync(join(checkout, ".odoo19-agent.toml"), "[tooling]\n");
    assert.equal(legacyProfile(checkout) ? null : findWorkspaceFile(checkout), null);
    assert.match(projectContext(checkout, null), /\(legacy \.odoo19-agent\.toml, no longer read: the user runs \/oasis migrate\)/);
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

test("projectContext tells the agent which oasis commands are Tier B, and stays compact", () => {
  const line = "Tier B commands (oasis policy --json) wait for the user's confirmation; never bypass a refusal.";
  for (const tools of [undefined, ["read", "bash"]]) {
    const text = projectContext("/work/acme/codigo/acme", "/work/acme/oasis-workspace.toml", tools, "19.0");
    assert.ok(text.split("\n").includes(line), text);
    assert.ok(text.length < 1200, `context must stay compact, got ${text.length} chars`);
  }
});

// v0.14.0 S4: a linked worktree with no workspace file at or above it reads the one its main checkout
// reads, found through git (tools/config.py asks `git rev-parse --git-common-dir`; this lib reads the
// worktree's `.git` file and its git directory's `commondir`, as git does). Real git in scratch
// directories, never the user's configuration.
const GIT_ENV = {
  ...Object.fromEntries(Object.entries(process.env).filter(([key]) => !key.startsWith("GIT_"))),
  GIT_CONFIG_GLOBAL: "/dev/null", GIT_CONFIG_NOSYSTEM: "1",
  GIT_AUTHOR_NAME: "oasis tests", GIT_AUTHOR_EMAIL: "tests@example.invalid",
  GIT_COMMITTER_NAME: "oasis tests", GIT_COMMITTER_EMAIL: "tests@example.invalid",
};

function git(cwd: string, ...args: string[]): string {
  return execFileSync("git", ["-c", "init.defaultBranch=main", "-c", "commit.gpgsign=false", "-C", cwd, ...args], {
    env: { ...GIT_ENV, GIT_CEILING_DIRECTORIES: realpathSync(tmpdir()) }, encoding: "utf8",
  }).trim();
}

function gitTop(start: string): string | null {
  try {
    return git(start, "rev-parse", "--show-toplevel");
  } catch {
    return null;
  }
}

/** <scratch>/project/oasis-workspace.toml over the main checkout <scratch>/project/acme, and two
 * linked worktrees outside the workspace directory: <scratch>/elsewhere/acme-feat, and
 * <scratch>/elsewhere/rel (gitfile with relative paths). */
function worktreeLayout(): { base: string; project: string; main: string; linked: string } {
  const base = scratch();
  const project = join(base, "project");
  const main = join(project, "acme");
  mkdirSync(main, { recursive: true });
  const fixture = readFileSync(new URL("../../tests/fixture-workspace.toml", import.meta.url), "utf8");
  writeFileSync(join(project, "oasis-workspace.toml"), fixture.replaceAll("'../../", "'"));
  writeFileSync(join(main, "README.md"), "fixture\n");
  git(main, "init", "-q");
  git(main, "add", "README.md");
  git(main, "commit", "-q", "-m", "init");
  const linked = join(base, "elsewhere", "acme-feat");
  git(main, "worktree", "add", "-q", "-b", "feat", linked);
  return { base, project, main, linked };
}

test("a linked worktree outside the workspace directory finds the main checkout's workspace file", () => {
  const { base, project, main, linked } = worktreeLayout();
  try {
    const workspace = join(project, "oasis-workspace.toml");
    const nested = join(linked, "addons", "coffee");
    mkdirSync(nested, { recursive: true });
    for (const start of [linked, nested]) {
      assert.equal(findWorkspaceFile(start), workspace, start);
      for (const top of [gitTop, () => null, undefined]) assert.equal(findProjectRoot(start, top), linked, start);
    }
    // The main checkout and its own directories are unchanged.
    assert.equal(findWorkspaceFile(main), workspace);
    assert.equal(findProjectRoot(join(main), gitTop), main);
    // The upward search comes first: a workspace file above the worktree wins.
    const nearer = join(base, "elsewhere", "oasis-workspace.toml");
    writeFileSync(nearer, "workspace_version = 1\n");
    assert.equal(findWorkspaceFile(nested), nearer);
    assert.equal(findProjectRoot(nested, gitTop), linked);
    rmSync(nearer);
    // Without a workspace file for the main checkout either, the worktree is not a project.
    rmSync(workspace);
    assert.equal(findWorkspaceFile(nested), null);
    assert.equal(findProjectRoot(nested, gitTop), null);
  } finally {
    rmSync(base, { recursive: true, force: true });
  }
});

test("project detection and tools/config.py give one root and workspace for a worktree outside it", () => {
  const { base, project, linked } = worktreeLayout();
  const config = scratch();
  try {
    // A gitfile and commondir with relative paths (git worktree add --relative-paths) read the same.
    const relative = join(base, "elsewhere", "rel");
    git(join(project, "acme"), "worktree", "add", "-q", "-b", "rel", relative);
    const gitdir = readFileSync(join(relative, ".git"), "utf8").trim().replace(/^gitdir: /, "");
    writeFileSync(join(relative, ".git"), `gitdir: ${relativePath(relative, gitdir)}\n`);
    for (const checkout of [linked, relative]) {
      const start = join(checkout, "sub");
      mkdirSync(start, { recursive: true });
      const root = findProjectRoot(start, gitTop);
      assert.equal(root, checkout);
      const output = execFileSync("python3", ["-B", fileURLToPath(new URL("../../tools/config.py", import.meta.url)), root!], {
        env: { ...GIT_ENV, GIT_CEILING_DIRECTORIES: base, XDG_CONFIG_HOME: config }, encoding: "utf8",
      });
      const values = Object.fromEntries(output.split("\n").filter((line) => /^[A-Z_]+=/.test(line))
        .map((line) => [line.slice(0, line.indexOf("=")), line.slice(line.indexOf("=") + 1)]));
      assert.equal(values.PROJECT_ROOT, root);
      assert.equal(values.WORKSPACE_ROOT, dirname(findWorkspaceFile(start)!));
      assert.equal(values.WORKSPACE_ROOT, project);
      assert.equal(values.CHECKOUT_KIND, "linked");
    }
  } finally {
    rmSync(config, { recursive: true, force: true });
    rmSync(base, { recursive: true, force: true });
  }
});

// v0.16.0 S1: /oasis worktree and /oasis migrate confirm with the exact name the dry run names.
test("planConfirmation reads the --confirm value from the plan of worktree-init and migrate", () => {
  assert.equal(planConfirmation("worktree", "worktree: /work/shop-feat\nbranch: feat (existing)\nslug: feat\n" +
    "workspace: /work\ndry run: nothing changed\n"), "/work/shop-feat");
  assert.equal(planConfirmation("migrate", "workspace: /work\ncheckout: /work/shop (main)\nwrite /work/oasis-workspace.toml\n" +
    "  [tooling]\nwrite /work/shop/oasis-checkout.toml\ndry run: nothing changed; run with --apply to migrate\n"),
  "/work/oasis-workspace.toml");
  assert.equal(planConfirmation("worktree", "dry run: nothing changed\n"), null);
  assert.equal(planConfirmation("migrate", "workspace: /work\n"), null);
});
