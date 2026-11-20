import { test } from "node:test";
import assert from "node:assert/strict";
import { formatStatus, parseAssignments, type StatusInput } from "../lib/status.ts";

test("parseAssignments reads config.py shell-quoted output", () => {
  const output = [
    "DEV_PREFIX=cc_dev_",
    "TEST_DATABASE=''",
    "ODOO_SOURCE=/opt/odoo/community",
    "ADDON_ROOTS='/p/addons",
    "/p/vendor addons'",
    "NOTE='it'\"'\"'s'",
  ].join("\n");
  assert.deepEqual(parseAssignments(output), {
    DEV_PREFIX: "cc_dev_",
    TEST_DATABASE: "",
    ODOO_SOURCE: "/opt/odoo/community",
    ADDON_ROOTS: "/p/addons\n/p/vendor addons",
    NOTE: "it's",
  });
});

test("formatStatus shows profile, modules, databases and worktree compactly", () => {
  const text = formatStatus({
    root: "/work/coffee-07.1",
    config: { DEV_PREFIX: "cc_dev_", TEST_PREFIX: "cc_test_", TEST_DATABASE: "cc_test_coffee", ODOO_SOURCE: "/opt/odoo" },
    modules: [
      { root: "/work/coffee-07.1/addons", names: ["coffee", "coffee_mrp"] },
      { root: "/work/coffee-07.1/vendor", names: Array.from({ length: 14 }, (_, i) => `m${i}`) },
    ],
    git: { branch: "feat/mrp-07.1", linkedWorktree: true, changedFiles: 3 },
  });
  assert.equal(
    text,
    [
      "Odoo project: /work/coffee-07.1",
      "odoo source: /opt/odoo",
      "databases: dev cc_dev_<module>, test cc_test_coffee (prefix cc_test_)",
      "addons: /work/coffee-07.1/addons (2): coffee, coffee_mrp",
      "addons: /work/coffee-07.1/vendor (14): m0, m1, m2, m3, m4, m5, m6, m7, m8, m9, ... +4",
      "git: feat/mrp-07.1, linked worktree, 3 changed files",
    ].join("\n"),
  );
});

test("formatStatus reports config errors and non-git projects", () => {
  const text = formatStatus({ root: "/p", configError: "ERROR: Invalid tooling addon roots.", modules: [], git: null });
  assert.equal(text, "Odoo project: /p\nprofile: ERROR: Invalid tooling addon roots.\ngit: not a git checkout");
});

test("formatStatus without a configured test database names the per-module default", () => {
  const text = formatStatus({
    root: "/p",
    config: { DEV_PREFIX: "x_dev_", TEST_PREFIX: "x_test_", TEST_DATABASE: "", ODOO_SOURCE: "/o" },
    modules: [],
    git: { branch: "main", linkedWorktree: false, changedFiles: 0 },
  });
  assert.equal(
    text,
    "Odoo project: /p\nodoo source: /o\ndatabases: dev x_dev_<module>, test x_test_<module>\ngit: main, main checkout, clean",
  );
});

test("listModules returns sorted directories that hold a manifest", async () => {
  const { mkdtempSync, mkdirSync, writeFileSync, rmSync } = await import("node:fs");
  const { tmpdir } = await import("node:os");
  const { join } = await import("node:path");
  const { listModules } = await import("../lib/status.ts");
  const root = mkdtempSync(join(tmpdir(), "oasis-addons-"));
  try {
    for (const name of ["zeta", "alpha", "not_a_module"]) mkdirSync(join(root, name));
    writeFileSync(join(root, "zeta", "__manifest__.py"), "{}");
    writeFileSync(join(root, "alpha", "__manifest__.py"), "{}");
    writeFileSync(join(root, "README.md"), "");
    assert.deepEqual(listModules(root), ["alpha", "zeta"]);
    assert.deepEqual(listModules(join(root, "missing")), []);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("parseGit resolves rev-parse dirs against the root and counts changed files", async () => {
  const { parseGit } = await import("../lib/status.ts");
  assert.deepEqual(parseGit("/p", "main\n.git\n.git\n", " M a.py\n?? b.py\n"), {
    branch: "main",
    linkedWorktree: false,
    changedFiles: 2,
  });
  assert.deepEqual(parseGit("/w/07.1", "feat/x\n/p/.git/worktrees/07.1\n/p/.git\n", ""), {
    branch: "feat/x",
    linkedWorktree: true,
    changedFiles: 0,
  });
  assert.deepEqual(parseGit("/p/sub", "main\n/p/.git\n../.git\n", ""), {
    branch: "main",
    linkedWorktree: false,
    changedFiles: 0,
  });
  assert.equal(parseGit("/p", "main\n", ""), null);
});

test("formatStatus adds the checkout identity reported by the profile", () => {
  const base = { DEV_PREFIX: "x_dev_", TEST_PREFIX: "x_test_", TEST_DATABASE: "", ODOO_SOURCE: "/o" };
  const head = "Odoo project: /p\nodoo source: /o\ndatabases: dev x_dev_<module>, test x_test_<module>\n";
  const cases: [Record<string, string>, StatusInput["git"], string][] = [
    [{ CHECKOUT_KIND: "main", CHECKOUT_SLUG: "" }, { branch: "main", linkedWorktree: false, changedFiles: 0 },
      "git: main, main checkout, clean\ncheckout: main"],
    [{ CHECKOUT_KIND: "linked", CHECKOUT_SLUG: "07_1" }, { branch: "feat/x", linkedWorktree: true, changedFiles: 1 },
      "git: feat/x, linked worktree, 1 changed files\ncheckout: linked worktree, slug 07_1"],
    [{ CHECKOUT_KIND: "main", CHECKOUT_SLUG: "x" }, { branch: "main", linkedWorktree: false, changedFiles: 0 },
      "git: main, main checkout, clean\ncheckout: main, slug x (profile)"],
    [{ CHECKOUT_KIND: "none", CHECKOUT_SLUG: "" }, null, "git: not a git checkout\ncheckout: outside git"],
    [{ CHECKOUT_KIND: "none", CHECKOUT_SLUG: "solo" }, null, "git: not a git checkout\ncheckout: outside git, slug solo (profile)"],
  ];
  for (const [identity, git, tail] of cases) {
    assert.equal(formatStatus({ root: "/p", config: { ...base, ...identity }, modules: [], git }), head + tail);
  }
});

test("parseServer reads runtime_state.py show output", async () => {
  const { parseServer } = await import("../lib/status.ts");
  assert.deepEqual(parseServer("pid=4242 port=8020\n"), { pid: 4242, port: 8020 });
  assert.equal(parseServer(""), null);
  assert.equal(parseServer("pid=x port=8020\n"), null);
});

test("formatStatus adds this checkout's server line after the checkout identity", () => {
  const base = {
    root: "/p",
    config: { DEV_PREFIX: "x_dev_", TEST_PREFIX: "x_test_", TEST_DATABASE: "", ODOO_SOURCE: "/o", CHECKOUT_KIND: "linked", CHECKOUT_SLUG: "07_1" },
    modules: [],
    git: { branch: "feat/x", linkedWorktree: true, changedFiles: 0 },
  };
  const head = "Odoo project: /p\nodoo source: /o\ndatabases: dev x_dev_<module>, test x_test_<module>\n" +
    "git: feat/x, linked worktree, clean\ncheckout: linked worktree, slug 07_1\n";
  assert.equal(formatStatus({ ...base, server: { pid: 4242, port: 8020 } }), head + "server: running on port 8020 (pid 4242)");
  assert.equal(formatStatus({ ...base, server: null }), head + "server: stopped");
  assert.equal(formatStatus({ ...base, serverError: "ERROR: Runtime state directory is a symlink: /run/x" }),
    head + "server: unknown (ERROR: Runtime state directory is a symlink: /run/x)");
});

test("formatStatus names the configured Odoo series", () => {
  const text = formatStatus({ root: "/p", config: { ODOO_VERSION: "19.0", ODOO_SOURCE: "/o" }, modules: [], git: null });
  assert.equal(text.split("\n")[0], "Odoo 19.0 project: /p");
});
