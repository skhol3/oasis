import { test } from "node:test";
import assert from "node:assert/strict";
import {
  mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, statSync, symlinkSync, utimesSync, writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import {
  configHome, formatSetupReport, gentleShellHost, installOverlay, NOT_GENTLE_SHELL, overlayReminder, overlayState,
  overlayTarget, runSetup, setupCommand,
} from "../lib/setup.ts";

const TEMPLATE_BODY = '{\n  "gentle-ai-worker": { "add": ["odoo19_test_module"] }\n}\n';

function scratch(): string {
  return mkdtempSync(join(tmpdir(), "oasis-setup-"));
}

function withScratch(body: (dir: string, template: string) => void): void {
  const dir = scratch();
  try {
    const template = join(dir, "template.json");
    writeFileSync(template, TEMPLATE_BODY);
    body(dir, template);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
}

test("configHome uses an absolute GENTLE_PI_CONFIG_HOME", () => {
  assert.equal(configHome({ GENTLE_PI_CONFIG_HOME: "/x/cfg" }, "/home/u"), "/x/cfg");
});

test("configHome defaults to ~/.gentle-shell/gentle-ai", () => {
  assert.equal(configHome({}, "/home/u"), "/home/u/.gentle-shell/gentle-ai");
  assert.equal(configHome({ GENTLE_PI_CONFIG_HOME: "" }, "/home/u"), "/home/u/.gentle-shell/gentle-ai");
});

test("configHome ignores a relative GENTLE_PI_CONFIG_HOME", () => {
  assert.equal(configHome({ GENTLE_PI_CONFIG_HOME: "rel/cfg" }, "/home/u"), "/home/u/.gentle-shell/gentle-ai");
});

test("overlayTarget is agent-overlays.d/oasis.json under the config home", () => {
  assert.equal(overlayTarget("/x/cfg"), "/x/cfg/agent-overlays.d/oasis.json");
});

test("overlayState: missing, outdated, current, formatting-only difference and invalid JSON", () => {
  withScratch((dir, template) => {
    const target = join(dir, "cfg", "agent-overlays.d", "oasis.json");
    assert.equal(overlayState(template, target), "missing");
    mkdirSync(join(dir, "cfg", "agent-overlays.d"), { recursive: true });
    writeFileSync(target, '{"gentle-ai-worker": {"add": ["other"]}}');
    assert.equal(overlayState(template, target), "outdated");
    writeFileSync(target, TEMPLATE_BODY);
    assert.equal(overlayState(template, target), "current");
    writeFileSync(target, '{"gentle-ai-worker":{"add":["odoo19_test_module"]}}');
    assert.equal(overlayState(template, target), "current");
    writeFileSync(target, "{not json");
    assert.equal(overlayState(template, target), "outdated");
  });
});

test("installOverlay creates the directory with mode 0700 and the template bytes", () => {
  withScratch((dir, template) => {
    const overlays = join(dir, "cfg", "agent-overlays.d");
    const target = join(overlays, "oasis.json");
    assert.deepEqual(installOverlay(template, target), { state: "created" });
    assert.equal(readFileSync(target, "utf8"), TEMPLATE_BODY);
    assert.equal(statSync(overlays).mode & 0o777, 0o700);
    assert.deepEqual(readdirSync(overlays), ["oasis.json"]);
    assert.equal(overlayState(template, target), "current");
  });
});

test("installOverlay updates an outdated target and leaves siblings untouched", () => {
  withScratch((dir, template) => {
    const overlays = join(dir, "cfg", "agent-overlays.d");
    mkdirSync(overlays, { recursive: true });
    const target = join(overlays, "oasis.json");
    const sibling = join(overlays, "other.json");
    writeFileSync(target, "{}");
    writeFileSync(sibling, '{"a": {"add": ["b"]}}');
    assert.deepEqual(installOverlay(template, target), { state: "updated" });
    assert.equal(readFileSync(target, "utf8"), TEMPLATE_BODY);
    assert.equal(readFileSync(sibling, "utf8"), '{"a": {"add": ["b"]}}');
    assert.deepEqual(readdirSync(overlays).sort(), ["oasis.json", "other.json"]);
  });
});

test("installOverlay leaves a current target's bytes and mtime unchanged", () => {
  withScratch((dir, template) => {
    const overlays = join(dir, "cfg", "agent-overlays.d");
    mkdirSync(overlays, { recursive: true });
    const target = join(overlays, "oasis.json");
    const formatted = '{"gentle-ai-worker":{"add":["odoo19_test_module"]}}';
    writeFileSync(target, formatted);
    const past = new Date("2020-01-01T00:00:00Z");
    utimesSync(target, past, past);
    assert.deepEqual(installOverlay(template, target), { state: "unchanged" });
    assert.equal(readFileSync(target, "utf8"), formatted);
    assert.equal(statSync(target).mtimeMs, past.getTime());
    assert.deepEqual(readdirSync(overlays), ["oasis.json"]);
  });
});

test("installOverlay refuses a symlink target and leaves the file it points to unchanged", () => {
  withScratch((dir, template) => {
    const overlays = join(dir, "cfg", "agent-overlays.d");
    mkdirSync(overlays, { recursive: true });
    const pointed = join(dir, "elsewhere.json");
    writeFileSync(pointed, "{}");
    const target = join(overlays, "oasis.json");
    symlinkSync(pointed, target);
    assert.throws(() => installOverlay(template, target), /symlink/);
    assert.equal(readFileSync(pointed, "utf8"), "{}");
    assert.deepEqual(readdirSync(overlays), ["oasis.json"]);
  });
});

test("installOverlay refuses a directory target", () => {
  withScratch((dir, template) => {
    const target = join(dir, "cfg", "agent-overlays.d", "oasis.json");
    mkdirSync(target, { recursive: true });
    assert.throws(() => installOverlay(template, target), /directory/);
    assert.deepEqual(readdirSync(target), []);
  });
});

// S7: the overlay is read only by Gentle Shell's subagents. Its launcher sets
// PI_PROGRAM_STATUS_APP=gentle-shell; an absolute GENTLE_PI_CONFIG_HOME names its config home.
const GENTLE_SHELL = { PI_PROGRAM_STATUS_APP: "gentle-shell" };

type Call = string[];
type Result = { code: number; stdout: string; stderr: string };

// The CLI double: `status --json` and `setup --plan --json` answer with these results; any other command fails
// the test (/oasis setup never applies setup).
function fakeRun(status: Result, plan: Result) {
  const calls: Call[] = [];
  return {
    calls,
    run: async (args: string[]) => {
      calls.push(args);
      if (args.join(" ") === "status --json") return status;
      if (args.join(" ") === "setup --plan --json") return plan;
      throw new Error(`unexpected command: ${args.join(" ")}`);
    },
  };
}

function fakeUi() {
  const notices: { message: string; level: string | undefined }[] = [];
  const shown: string[] = [];
  return { notices, shown, ui: { notify: (message: string, level?: "info" | "warning" | "error") => notices.push({ message, level }) } };
}

function tree(dir: string): string[] {
  return readdirSync(dir, { recursive: true }).map(String).sort();
}

test("gentleShellHost: the launcher marker or an absolute GENTLE_PI_CONFIG_HOME", () => {
  assert.equal(gentleShellHost(GENTLE_SHELL), true);
  assert.equal(gentleShellHost({ GENTLE_PI_CONFIG_HOME: "/x/cfg" }), true);
  assert.equal(gentleShellHost({}), false);
  assert.equal(gentleShellHost({ PI_PROGRAM_STATUS_APP: "" }), false);
  assert.equal(gentleShellHost({ PI_PROGRAM_STATUS_APP: "pi" }), false);
  assert.equal(gentleShellHost({ GENTLE_PI_CONFIG_HOME: "rel/cfg" }), false);
  assert.equal(gentleShellHost({ GENTLE_SHELL_CONFIG_HOME: "/x/cfg" }), false);
});

const CHECKOUT = "/work/shop/code/shop";
const STATUS = {
  project: CHECKOUT, ready: ["workspace", "environment"], missing: ["locks", "database_service", "databases", "server"],
  checks: {
    workspace: { ready: true, detail: "/work/shop/oasis-workspace.toml" },
    environment: { ready: true, detail: "/work/shop/.oasis/venv" },
    locks: { ready: false, detail: "stale" },
    database_service: { ready: false, detail: "stopped" },
    databases: { ready: false, detail: "unknown while the database service is stopped" },
    server: { ready: false, detail: "stopped" },
  },
  next: `oasis --project ${CHECKOUT} bootstrap --apply`,
};
const PLAN = {
  format: "oasis-setup-plan", version: 1, checkout: CHECKOUT, complete: true, ready_to_apply: false,
  inferred: {}, lines: [],
  changes: [
    { kind: "create", path: "/work/shop/config/odoo.conf", summary: "create /work/shop/config/odoo.conf (mode 0600)" },
    { kind: "compile", path: "/work/shop/config/requirements", summary: "compile the locks (uv pip compile)" },
  ],
  questions: [
    { id: "workspace", text: "Workspace directory", flag: "--workspace <dir>", recommended: "/work/shop", answer: null },
    { id: "requirement:cv2", text: "Add cv2 to runtime.in?", flag: "--answer requirement:cv2=<add|skip>",
      recommended: null, answer: null },
  ],
  open: ["workspace", "requirement:cv2"],
};

function json(value: unknown, code = 0): Result {
  return { code, stdout: `${JSON.stringify(value)}\n`, stderr: "" };
}

test("formatSetupReport: the status checks, the plan's changes and open questions, nothing applied", () => {
  assert.equal(formatSetupReport({ status: json(STATUS), plan: json(PLAN), overlay: "subagent overlay: x" }), [
    `oasis setup: ${CHECKOUT}`,
    "status (oasis status --json):",
    "  ready: workspace, environment",
    "  missing: locks (stale), database_service (stopped), databases (unknown while the database service is stopped), " +
      "server (stopped)",
    `  next: oasis --project ${CHECKOUT} bootstrap --apply`,
    "setup plan (oasis setup --plan --json): 2 changes, 2 open questions",
    "  - create /work/shop/config/odoo.conf (mode 0600)",
    "  - compile the locks (uv pip compile)",
    "  open question workspace: Workspace directory (--workspace <dir>; recommended: /work/shop)",
    "  open question requirement:cv2: Add cv2 to runtime.in? (--answer requirement:cv2=<add|skip>; no recommended answer)",
    "  nothing applied: answer the open questions, then run oasis --project /work/shop/code/shop setup --apply",
    "subagent overlay: x",
  ].join("\n"));
});

test("formatSetupReport: a plan ready to apply, nothing to set up, a refusal and unreadable output", () => {
  const ready = { ...PLAN, ready_to_apply: true, questions: [], open: [] };
  const done = { ...STATUS, ready: [...STATUS.ready, "locks"], missing: [], next: null,
    checks: { ...STATUS.checks, databases: { ready: true, detail: ["shop_dev_manual"] } } };
  const report = (status: Result, plan: Result) => formatSetupReport({ status, plan, overlay: "subagent overlay: x" });
  assert.equal(report(json(done), json(ready)).split("\n").slice(1).join("\n"), [
    "status (oasis status --json):",
    "  ready: workspace, environment, locks",
    "  missing: none",
    "  next: none",
    "setup plan (oasis setup --plan --json): 2 changes",
    "  - create /work/shop/config/odoo.conf (mode 0600)",
    "  - compile the locks (uv pip compile)",
    `  nothing applied: oasis --project ${CHECKOUT} setup --apply applies it`,
    "subagent overlay: x",
  ].join("\n"));
  const nothing = { ...ready, changes: [] };
  assert.match(report(json(done), json(nothing)), /\nsetup plan \(oasis setup --plan --json\): nothing to set up\n/);
  const refused = { code: 2, stdout: "", stderr: "ERROR: Refusing --workspace /x: it is not at or above the checkout.\n" };
  const broken = { code: 0, stdout: "not json", stderr: "" };
  assert.equal(report(broken, refused), [
    "oasis setup: the current checkout",
    "status (oasis status --json): unavailable (no JSON output)",
    "setup plan (oasis setup --plan --json): ERROR: Refusing --workspace /x: it is not at or above the checkout.",
    "subagent overlay: x",
  ].join("\n"));
  assert.match(report({ code: 2, stdout: "", stderr: "" }, json(ready)), /^status \(oasis status --json\): unavailable \(exit 2\)$/m);
  assert.match(report(json(STATUS), json(ready)), new RegExp(`^oasis setup: ${CHECKOUT}$`, "m"));
});

test("formatSetupReport: the apply hint shell-quotes the checkout and is left out when none is known", () => {
  const spaced = "/work/my shop/code/it's";
  const quoted = "'/work/my shop/code/it'\"'\"'s'";
  const report = (plan: unknown, status: Result) =>
    formatSetupReport({ status, plan: json(plan), overlay: "subagent overlay: x" }).split("\n");
  const ready = { ...PLAN, checkout: spaced, questions: [], open: [] };
  assert.ok(report(ready, json(STATUS)).includes(`  nothing applied: oasis --project ${quoted} setup --apply applies it`));
  assert.ok(report({ ...PLAN, checkout: spaced }, json(STATUS)).includes(
    `  nothing applied: answer the open questions, then run oasis --project ${quoted} setup --apply`));
  // No checkout in the plan or the status: no command to copy, only what was (not) done.
  const unknown = { code: 2, stdout: "", stderr: "" };
  const anonymous = report({ ...ready, checkout: "" }, unknown);
  assert.equal(anonymous[0], "oasis setup: the current checkout");
  assert.ok(anonymous.includes("  nothing applied"), anonymous.join("\n"));
  assert.ok(!anonymous.some((line) => line.includes("--project")), anonymous.join("\n"));
  const open = report({ ...PLAN, checkout: "" }, unknown);
  assert.ok(open.includes("  nothing applied: answer the open questions"), open.join("\n"));
  assert.ok(!open.some((line) => line.includes("--project")), open.join("\n"));
});

test("setupCommand: --project <root> in the root when the session knows it, else the working directory", () => {
  const oasis = "/bundle/oasis";
  assert.deepEqual(setupCommand(oasis, "/work/shop/code/shop", "/work/shop/code/shop/addons", ["status", "--json"]), {
    command: "python3", args: ["-B", oasis, "--project", "/work/shop/code/shop", "status", "--json"],
    cwd: "/work/shop/code/shop",
  });
  // A clone setup has not configured yet: no root, so the CLI finds the checkout of the working directory.
  assert.deepEqual(setupCommand(oasis, null, "/work/new/code/new", ["setup", "--plan", "--json"]), {
    command: "python3", args: ["-B", oasis, "setup", "--plan", "--json"], cwd: "/work/new/code/new",
  });
});

test("runSetup shows the status and the plan, never applies setup, and installs the overlay in Gentle Shell", async () => {
  const dir = scratch();
  try {
    const template = join(dir, "template.json");
    writeFileSync(template, TEMPLATE_BODY);
    const home = join(dir, "home");
    const target = join(home, ".gentle-shell", "gentle-ai", "agent-overlays.d", "oasis.json");
    const cli = fakeRun(json(STATUS), json(PLAN));
    const session = fakeUi();
    await runSetup({ env: GENTLE_SHELL, homedir: home, template, run: cli.run, show: (text) => session.shown.push(text),
      ui: session.ui });
    assert.deepEqual(cli.calls, [["status", "--json"], ["setup", "--plan", "--json"]]);
    assert.equal(readFileSync(target, "utf8"), TEMPLATE_BODY);
    const installed = `subagent overlay: installed at ${target}; start a new session or /reload for subagents to use it.`;
    assert.deepEqual(session.shown, [formatSetupReport({ status: json(STATUS), plan: json(PLAN), overlay: installed })]);
    assert.deepEqual(session.notices, []);
    // Again: already installed, nothing to do (the file is kept as it is).
    const again = fakeUi();
    await runSetup({ env: GENTLE_SHELL, homedir: home, template, run: fakeRun(json(STATUS), json(PLAN)).run,
      show: (text) => again.shown.push(text), ui: again.ui });
    assert.ok(again.shown[0].endsWith(`\nsubagent overlay: already installed, nothing to do (${target}).`), again.shown[0]);
    // An outdated overlay is updated.
    writeFileSync(target, "{}");
    const outdated = fakeUi();
    await runSetup({ env: GENTLE_SHELL, homedir: home, template, run: fakeRun(json(STATUS), json(PLAN)).run,
      show: (text) => outdated.shown.push(text), ui: outdated.ui });
    assert.ok(outdated.shown[0].endsWith(
      `\nsubagent overlay: updated at ${target}; start a new session or /reload for subagents to use it.`));
    assert.equal(readFileSync(target, "utf8"), TEMPLATE_BODY);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("runSetup outside Gentle Shell shows the status and the plan and writes no overlay", async () => {
  const dir = scratch();
  try {
    const template = join(dir, "template.json");
    writeFileSync(template, TEMPLATE_BODY);
    const home = join(dir, "home");
    // Even a leftover ~/.gentle-shell/gentle-ai does not make a vanilla Pi session Gentle Shell.
    mkdirSync(join(home, ".gentle-shell", "gentle-ai"), { recursive: true });
    const before = tree(dir);
    const cli = fakeRun(json(STATUS), json(PLAN));
    const session = fakeUi();
    await runSetup({ env: {}, homedir: home, template, run: cli.run, show: (text) => session.shown.push(text),
      ui: session.ui });
    assert.deepEqual(cli.calls, [["status", "--json"], ["setup", "--plan", "--json"]]);
    assert.equal(NOT_GENTLE_SHELL,
      "subagent overlay: it applies only to Gentle Shell, and this session is not running in it; nothing written.");
    assert.deepEqual(session.shown, [formatSetupReport({ status: json(STATUS), plan: json(PLAN), overlay: NOT_GENTLE_SHELL })]);
    assert.deepEqual(tree(dir), before);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("runSetup reports an overlay it cannot write and a CLI that cannot run", async () => {
  const dir = scratch();
  try {
    const template = join(dir, "template.json");
    writeFileSync(template, TEMPLATE_BODY);
    const target = join(dir, "cfg", "agent-overlays.d", "oasis.json");
    mkdirSync(target, { recursive: true });
    const session = fakeUi();
    const failing = async () => { throw new Error("spawn python3 ENOENT"); };
    await runSetup({ env: { GENTLE_PI_CONFIG_HOME: join(dir, "cfg") }, homedir: join(dir, "home"), template,
      run: failing, show: (text) => session.shown.push(text), ui: session.ui });
    assert.deepEqual(session.shown, [[
      "oasis setup: the current checkout",
      "status (oasis status --json): unavailable (spawn python3 ENOENT)",
      "setup plan (oasis setup --plan --json): unavailable (spawn python3 ENOENT)",
      `subagent overlay: not installed (Refusing to write ${target}: it is a directory.)`,
    ].join("\n")]);
    assert.deepEqual(session.notices, []);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("overlayReminder: none outside Gentle Shell; missing, outdated or none in it", () => {
  withScratch((dir, template) => {
    const home = join(dir, "home");
    const target = join(home, ".gentle-shell", "gentle-ai", "agent-overlays.d", "oasis.json");
    assert.equal(overlayReminder({ env: {}, homedir: home, template }), null);
    assert.equal(overlayReminder({ env: GENTLE_SHELL, homedir: home, template }),
      "oasis: subagents do not have the oasis tools yet; run /oasis setup");
    mkdirSync(dirname(target), { recursive: true });
    writeFileSync(target, "{}");
    assert.equal(overlayReminder({ env: {}, homedir: home, template }), null);
    assert.equal(overlayReminder({ env: GENTLE_SHELL, homedir: home, template }),
      "oasis: overlay is outdated; run /oasis setup");
    writeFileSync(target, TEMPLATE_BODY);
    assert.equal(overlayReminder({ env: GENTLE_SHELL, homedir: home, template }), null);
  });
});
