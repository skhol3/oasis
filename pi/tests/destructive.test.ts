import { test } from "node:test";
import assert from "node:assert/strict";
import { blockReason } from "../lib/bash-guard.ts";
import type { MenuEntry } from "../lib/menu.ts";
import {
  agentFileGate, agentGate, ASK_TIMEOUT_MS, type GateContext, type GateEffects, settingReader, toolCallRouter,
} from "../lib/destructive.ts";

// The bash gate (S3, S4) with every Pi effect faked: what it blocks, asks and records.
const ROOT = "/work/shop";
const DROP = "oasis --project /work/shop drop-database shop_dev_old";
const STOP = "oasis --project /work/shop stop --database";
const PURGE = "oasis --project /work/shop gc --apply --trash --older-than 0";
const SECONDS = ASK_TIMEOUT_MS / 1000;
// v0.16.0 S1: Tier B in the policy table, so they ask like drop-database (before: denied).
const WORKTREE = "oasis --project /work/shop worktree-init feat feature/x";

interface Setup {
  root?: string | null;
  /** AGENT_DESTRUCTIVE as config.py printed it; undefined when the profile could not be read. */
  setting?: string | undefined;
  hasUI?: boolean;
  answers?: (string | undefined)[];
  /** realpath of the file system: identity unless given. */
  realpath?: (path: string) => string;
  cwd?: string;
  /** projectRoot of a directory (the session's and every target's); default: `root` for any. */
  roots?: (dir: string) => string | null;
  /** AGENT_DESTRUCTIVE per project root; a root not listed gets `setting`. */
  settings?: Record<string, string | undefined>;
  /** The environment the machine file is found from (XDG_CONFIG_HOME); default: none set. */
  environment?: Record<string, string | undefined>;
}

function harness(options: Setup = {}) {
  const entries: MenuEntry[] = [];
  const prompts: { title: string; placeholder: string | undefined; options: { timeout?: number; signal?: AbortSignal } }[] = [];
  const settingsRead: string[] = [];
  const answers = [...(options.answers ?? [])];
  const effects: GateEffects = {
    projectRoot: async (dir) => (options.roots ? options.roots(dir) : options.root === undefined ? ROOT : options.root),
    home: "/home/u",
    exists: () => false,
    agentDestructive: async (root) => {
      settingsRead.push(root);
      if (options.settings && root in options.settings) return options.settings[root];
      return "setting" in options ? options.setting : "ask";
    },
    appendEntry: (entry) => entries.push(entry),
    realpath: options.realpath ?? ((path) => path),
    environment: options.environment ?? {},
  };
  const signal = new AbortController().signal;
  const ctx: GateContext = {
    cwd: options.cwd ?? `${ROOT}/addons`,
    hasUI: options.hasUI ?? true,
    signal,
    ui: {
      input: async (title, placeholder, dialog) => {
        prompts.push({ title, placeholder, options: dialog });
        assert.ok(answers.length > 0, `unexpected dialog: ${title}`);
        return answers.shift();
      },
    },
  };
  const gate = agentGate(effects);
  const fileGate = agentFileGate(effects);
  return {
    gate: (command: string) => gate(command, ctx),
    file: (tool: string, path: string) => fileGate(tool, path, ctx),
    entries, prompts, settingsRead, signal,
  };
}

test("the deny tier blocks exactly as before, without a dialog or an entry", async () => {
  const inProject = harness();
  assert.deepEqual(await inProject.gate("psql -l"), { block: true, reason: blockReason("psql", ROOT) });
  assert.deepEqual(await inProject.gate("oasis --project /p menu"), { block: true, reason: blockReason("menu", "") });
  assert.deepEqual(await inProject.gate(`${DROP}; dropdb x`), { block: true, reason: blockReason("dropdb", ROOT) });
  const outside = harness({ root: null });
  assert.equal(await outside.gate("psql -l"), undefined);
  assert.deepEqual(await outside.gate("oasis --project /p menu"), { block: true, reason: blockReason("menu", "") });
  for (const run of [inProject, outside]) {
    assert.deepEqual(run.prompts, []);
    assert.deepEqual(run.entries, []);
  }
});

test("allowed commands run without a dialog, an entry or reading the setting", async () => {
  const run = harness();
  for (const command of [
    "oasis --project /work/shop test-module coffee", "oasis --project /work/shop gc --apply",
    "oasis --project /work/shop stop", "oasis --project /work/shop trash restore shop_dev_old_trash_20261124_101500",
    // S6: restart, stop --force and status act on the checkout's own server.
    "oasis --project /work/shop restart", "oasis --project /work/shop restart -d shop_dev_x --workers=0",
    "oasis --project /work/shop restart --database shop_dev_x", "oasis --project /work/shop stop --force",
    "oasis --project /work/shop status", "~/.agents/skills/oasis/tools/stop --force",
    "~/.agents/skills/oasis/tools/restart",
    "oasis --project /work/shop drop-database --help", "git status",
    // v0.12.1 S5: the native odoo-bin line only prints.
    "oasis --project /work/shop start --print-command -d shop_dev_x", "oasis --project /work/shop restart --print-command",
    "~/.agents/skills/oasis/tools/restart --print-command --http-port 8070",
  ]) {
    assert.equal(await run.gate(command), undefined, command);
  }
  assert.deepEqual([run.prompts, run.entries, run.settingsRead], [[], [], []]);
});

test("drop-database asks to type the database name and runs when it matches", async () => {
  const run = harness({ answers: ["shop_dev_old"] });
  assert.equal(await run.gate(DROP), undefined);
  assert.equal(run.prompts.length, 1);
  const [prompt] = run.prompts;
  assert.equal(prompt.title,
    `oasis: the agent wants to run\n\n${DROP}\n\n` +
      `Type shop_dev_old to allow drop-database shop_dev_old. Esc, another answer or no answer within ${SECONDS} s refuses.`);
  assert.equal(prompt.placeholder, undefined);
  assert.deepEqual(prompt.options, { timeout: ASK_TIMEOUT_MS, signal: run.signal });
  assert.deepEqual(run.entries, [{ label: "Agent command approved", command: DROP, note: "typed shop_dev_old", output: "" }]);
  assert.deepEqual(run.settingsRead, [ROOT]);
});

test("the dialog is bounded in time: about two minutes", () => {
  assert.equal(ASK_TIMEOUT_MS, 2 * 60 * 1000);
});

test("a wrong answer, `yes` for drop-database, cancel or no answer blocks and records the refusal", async () => {
  for (const [answer, note, reason] of [
    ["shop_dev_other", "wrong answer",
      "The user's answer did not confirm drop-database shop_dev_old; nothing ran. Do not retry it: ask the user " +
        "whether to run it."],
    ["yes", "wrong answer",
      "The user's answer did not confirm drop-database shop_dev_old; nothing ran. Do not retry it: ask the user " +
        "whether to run it."],
    [undefined, "no answer",
      `The user did not confirm drop-database shop_dev_old (cancelled, or no answer within ${SECONDS} s); nothing ran. ` +
        "Do not retry it: ask the user whether to run it."],
  ] as const) {
    const run = harness({ answers: [answer] });
    assert.deepEqual(await run.gate(DROP), { block: true, reason }, String(answer));
    assert.deepEqual(run.entries, [{ label: "Agent command refused", command: DROP, note, output: "" }]);
  }
});

test("stop --database, gc --apply --trash and worktree-init ask to type yes", async () => {
  for (const [command, label] of [[STOP, "stop --database"], [PURGE, "gc --apply --trash"],
    [WORKTREE, "worktree-init"]]) {
    const approved = harness({ answers: [" yes "] });
    assert.equal(await approved.gate(command), undefined, command);
    assert.equal(approved.prompts[0].title,
      `oasis: the agent wants to run\n\n${command}\n\n` +
        `Type yes to allow ${label}. Esc, another answer or no answer within ${SECONDS} s refuses.`);
    assert.deepEqual(approved.entries, [{ label: "Agent command approved", command, note: "typed yes", output: "" }]);
    const refused = harness({ answers: ["YES"] });
    assert.deepEqual(await refused.gate(command), {
      block: true,
      reason: `The user's answer did not confirm ${label}; nothing ran. Do not retry it: ask the user whether to run it.`,
    });
    assert.deepEqual(refused.entries, [{ label: "Agent command refused", command, note: "wrong answer", output: "" }]);
  }
});

test("every ask command of one bash call is confirmed, in order; the first refusal stops", async () => {
  const command = `${DROP} && ${STOP}`;
  const both = harness({ answers: ["shop_dev_old", "yes"] });
  assert.equal(await both.gate(command), undefined);
  assert.equal(both.prompts.length, 2);
  assert.match(both.prompts[1].title, /Type yes to allow stop --database\./);
  assert.deepEqual(both.entries, [{ label: "Agent command approved", command, note: "typed shop_dev_old, yes", output: "" }]);
  const first = harness({ answers: [undefined] });
  assert.equal((await first.gate(command))?.block, true);
  assert.equal(first.prompts.length, 1);
  assert.deepEqual(first.entries, [{ label: "Agent command refused", command, note: "no answer", output: "" }]);
});

test("without a UI (subagent, headless) an ask command is blocked without a dialog", async () => {
  const run = harness({ hasUI: false });
  assert.deepEqual(await run.gate(STOP), {
    block: true,
    reason: "stop --database needs the user's confirmation in a dialog, and this session has none (a subagent or a " +
      "headless run); nothing ran. Ask the user to run it or to confirm it from an interactive session.",
  });
  assert.deepEqual(run.prompts, []);
  assert.deepEqual(run.entries, [{ label: "Agent command refused", command: STOP, note: "no dialog", output: "" }]);
});

test("a database name that is not literal is refused before any dialog", async () => {
  const command = "oasis --project /work/shop drop-database $NAME";
  const run = harness();
  assert.deepEqual(await run.gate(command), {
    block: true,
    reason: "drop-database needs the database name written literally as its first argument, so the user can confirm " +
      "it; nothing ran. Rewrite the command with the name, or ask the user to run it.",
  });
  assert.deepEqual(run.prompts, []);
  assert.deepEqual(run.entries, [{ label: "Agent command refused", command, note: "database name not literal", output: "" }]);
});

test("agent_destructive = deny turns ask into deny; allow runs without a dialog; both are recorded", async () => {
  const denied = harness({ setting: "deny" });
  assert.deepEqual(await denied.gate(DROP), {
    block: true,
    reason: "drop-database shop_dev_old is denied to agents by [tooling].agent_destructive = \"deny\" in this " +
      "project's configuration; nothing ran. Ask the user to run it.",
  });
  assert.deepEqual(denied.entries, [{ label: "Agent command refused", command: DROP, note: "agent_destructive = deny", output: "" }]);
  const allowed = harness({ setting: "allow", hasUI: false });
  assert.equal(await allowed.gate(PURGE), undefined);
  assert.deepEqual(allowed.prompts, []);
  assert.deepEqual(allowed.entries, [{ label: "Agent command approved", command: PURGE, note: "agent_destructive = allow", output: "" }]);
  // allow never lifts the deny tier.
  assert.deepEqual(await allowed.gate(`${PURGE}; psql`), { block: true, reason: blockReason("psql", ROOT) });
});

test("worktree-init honors agent_destructive like drop-database (v0.16.0 S1)", async () => {
  for (const [command, label] of [[WORKTREE, "worktree-init"]]) {
    const denied = harness({ setting: "deny" });
    assert.deepEqual(await denied.gate(command), {
      block: true,
      reason: `${label} is denied to agents by [tooling].agent_destructive = "deny" in this project's configuration; ` +
        "nothing ran. Ask the user to run it.",
    }, command);
    const allowed = harness({ setting: "allow", hasUI: false });
    assert.equal(await allowed.gate(command), undefined, command);
    assert.deepEqual([allowed.prompts, allowed.entries],
      [[], [{ label: "Agent command approved", command, note: "agent_destructive = allow", output: "" }]], command);
    // Its dry run is Tier A: no dialog, no entry, no setting read.
    const plan = harness({ setting: "deny" });
    assert.equal(await plan.gate(command.replace("feature/x", "feature/x --dry-run")), undefined, command);
    assert.deepEqual([plan.prompts, plan.entries, plan.settingsRead], [[], [], []], command);
  }
});

test("an unreadable or unknown setting, and a session outside a project, keep ask", async () => {
  for (const setting of [undefined, "", "yes", "ALLOW"]) {
    const run = harness({ setting, hasUI: false });
    assert.equal((await run.gate(STOP))?.block, true, String(setting));
    assert.equal(run.entries[0].note, "no dialog");
  }
  const outside = harness({ root: null, answers: ["yes"] });
  assert.equal(await outside.gate(STOP), undefined);
  assert.deepEqual(outside.settingsRead, []);
  assert.equal(outside.prompts.length, 1);
});

test("the dialog and the entry show the command without terminal control sequences", async () => {
  const command = "oasis --project /work/shop stop --database # \x1b[2K\x1b[1Ahidden\x07";
  const run = harness({ answers: ["yes"] });
  assert.equal(await run.gate(command), undefined);
  assert.ok(run.prompts[0].title.includes("oasis --project /work/shop stop --database # hidden\n"), run.prompts[0].title);
  assert.ok(!/[\x00-\x09\x0b-\x1f\x7f]/.test(run.prompts[0].title));
  assert.equal(run.entries[0].command, "oasis --project /work/shop stop --database # hidden");
});

// L7: the project an ask command targets (`--project`, or a tool script's OASIS_PROJECT_ROOT) has a say too:
// the stricter of its setting and the session's decides.
const OTHER = "/work/other";
const OTHER_DROP = "oasis --project /work/other drop-database other_dev_old";
const roots = (dir: string) => (dir === OTHER || dir.startsWith(`${OTHER}/`) ? OTHER : dir.startsWith(ROOT) ? ROOT : null);

test("the stricter of the session's and the target project's agent_destructive decides: deny > ask > allow", async () => {
  // allow here, ask there: the dialog runs, and without a UI the command is refused.
  const ask = harness({ roots, settings: { [ROOT]: "allow", [OTHER]: "ask" }, hasUI: false });
  assert.deepEqual(await ask.gate(OTHER_DROP), {
    block: true,
    reason: "drop-database other_dev_old needs the user's confirmation in a dialog, and this session has none (a " +
      "subagent or a headless run); nothing ran. Ask the user to run it or to confirm it from an interactive session.",
  });
  assert.deepEqual(ask.settingsRead, [ROOT, OTHER]);
  const asked = harness({ roots, settings: { [ROOT]: "allow", [OTHER]: "ask" }, answers: ["other_dev_old"] });
  assert.equal(await asked.gate(OTHER_DROP), undefined);
  assert.equal(asked.prompts.length, 1);
  assert.deepEqual(asked.entries, [{ label: "Agent command approved", command: OTHER_DROP, note: "typed other_dev_old", output: "" }]);
  // deny there blocks, naming that project.
  const denied = harness({ roots, settings: { [ROOT]: "allow", [OTHER]: "deny" } });
  assert.deepEqual(await denied.gate(OTHER_DROP), {
    block: true,
    reason: "drop-database other_dev_old is denied to agents by [tooling].agent_destructive = \"deny\" in the " +
      "configuration of /work/other; nothing ran. Ask the user to run it.",
  });
  assert.deepEqual(denied.entries, [{ label: "Agent command refused", command: OTHER_DROP, note: "agent_destructive = deny", output: "" }]);
  // deny here wins over allow there, with the reason of this project.
  const here = harness({ roots, settings: { [ROOT]: "deny", [OTHER]: "allow" } });
  assert.match((await here.gate(OTHER_DROP) as { reason: string }).reason, /in this project's configuration; nothing ran/);
  // ask here stays ask with allow there; allow in both runs without a dialog.
  const stays = harness({ roots, settings: { [ROOT]: "ask", [OTHER]: "allow" }, hasUI: false });
  assert.equal(stays.entries.length, 0);
  assert.equal((await stays.gate(OTHER_DROP))?.block, true);
  assert.equal(stays.entries[0].note, "no dialog");
  const both = harness({ roots, settings: { [ROOT]: "allow", [OTHER]: "allow" }, hasUI: false });
  assert.equal(await both.gate(OTHER_DROP), undefined);
  assert.deepEqual(both.entries, [{ label: "Agent command approved", command: OTHER_DROP, note: "agent_destructive = allow", output: "" }]);
  // The session's own project as the target is read once.
  const own = harness({ roots, settings: { [ROOT]: "allow" }, hasUI: false });
  assert.equal(await own.gate(DROP), undefined);
  assert.deepEqual(own.settingsRead, [ROOT]);
});

test("a target whose setting cannot be read, outside a project or not literal counts as ask", async () => {
  for (const [command, setup] of [
    [OTHER_DROP, { settings: { [ROOT]: "allow", [OTHER]: undefined } }],
    ["oasis --project /tmp/elsewhere stop --database", { settings: { [ROOT]: "allow" } }],
    ["oasis --project $TARGET stop --database", { settings: { [ROOT]: "allow" } }],
    ["oasis --proj /work/other gc --apply --trash", { settings: { [ROOT]: "allow", [OTHER]: "ask" } }],
    ["OASIS_PROJECT_ROOT=/work/other ~/.agents/skills/oasis/tools/stop --database", { settings: { [ROOT]: "allow" } }],
    ["OASIS_PROJECT_ROOT=$P ~/.agents/skills/oasis/tools/stop --database", { settings: { [ROOT]: "allow" } }],
    // Set elsewhere on the line: the tool reads a root the text does not tell.
    ["export OASIS_PROJECT_ROOT=/work/other; ~/.agents/skills/oasis/tools/stop --database", { settings: { [ROOT]: "allow" } }],
  ] as const) {
    const run = harness({ roots, hasUI: false, ...setup });
    assert.deepEqual(await run.gate(command), {
      block: true,
      reason: `${command.includes(" gc ") ? "gc --apply --trash" : command.includes("drop-database") ? "drop-database other_dev_old"
        : "stop --database"} needs the user's confirmation in a ` +
        "dialog, and this session has none (a subagent or a headless run); nothing ran. Ask the user to run it or to " +
        "confirm it from an interactive session.",
    }, command);
    assert.deepEqual(run.entries.map((entry) => entry.note), ["no dialog"], command);
  }
  // A literal tool-script root that is allowed there, as here, runs.
  const allowed = harness({ roots, settings: { [ROOT]: "allow", [OTHER]: "allow" }, hasUI: false });
  assert.equal(await allowed.gate("env OASIS_PROJECT_ROOT=/work/other ~/.agents/skills/oasis/tools/stop --database"), undefined);
  // deny there blocks a tool script too.
  const denied = harness({ roots, settings: { [ROOT]: "ask", [OTHER]: "deny" } });
  assert.match((await denied.gate("OASIS_PROJECT_ROOT=/work/other ~/.agents/skills/oasis/tools/stop --database") as
    { reason: string }).reason, /in the configuration of \/work\/other;/);
});

// v0.14.0 S8: without --project the entry point runs in the git top level of its directory. The
// gate judges it against the session's project, and after a literal cd (or env -C) against the
// stricter of the session's and that directory's project; nothing is loosened.
test("an entry point without --project still asks, judged against the session's project", async () => {
  const command = "oasis drop-database shop_dev_old";
  const asked = harness({ answers: ["shop_dev_old"] });
  assert.equal(await asked.gate(command), undefined);
  assert.match(asked.prompts[0].title, /Type shop_dev_old to allow drop-database shop_dev_old\./);
  assert.deepEqual(asked.entries, [{ label: "Agent command approved", command, note: "typed shop_dev_old", output: "" }]);
  assert.deepEqual(asked.settingsRead, [ROOT]);
  const headless = harness({ hasUI: false });
  assert.equal((await headless.gate(command))?.block, true);
  assert.deepEqual(headless.entries.map((entry) => entry.note), ["no dialog"]);
  const denied = harness({ setting: "deny" });
  assert.match((await denied.gate("oasis stop --database") as { reason: string }).reason,
    /^stop --database is denied to agents by \[tooling\]\.agent_destructive = "deny" in this project's configuration;/);
  // A literal cd inside the session's own project reads the session's setting once.
  const inside = harness({ roots, settings: { [ROOT]: "ask" }, hasUI: false });
  assert.equal((await inside.gate("cd /work/shop && oasis gc --apply --trash"))?.block, true);
  assert.deepEqual(inside.settingsRead, [ROOT]);
});

test("without --project the stricter of the session's and the directory's project decides", async () => {
  const drop = "cd /work/other && oasis drop-database other_dev_old";
  // allow here, deny there: denied, naming that project.
  const there = harness({ roots, settings: { [ROOT]: "allow", [OTHER]: "deny" } });
  assert.deepEqual(await there.gate(drop), {
    block: true,
    reason: "drop-database other_dev_old is denied to agents by [tooling].agent_destructive = \"deny\" in the " +
      "configuration of /work/other; nothing ran. Ask the user to run it.",
  });
  assert.deepEqual(there.settingsRead, [ROOT, OTHER]);
  // deny here wins over allow there.
  const here = harness({ roots, settings: { [ROOT]: "deny", [OTHER]: "allow" } });
  assert.match((await here.gate(drop) as { reason: string }).reason, /in this project's configuration; nothing ran/);
  // allow here, ask there: the dialog, so refused without a UI.
  const ask = harness({ roots, settings: { [ROOT]: "allow", [OTHER]: "ask" }, hasUI: false });
  assert.equal((await ask.gate(drop))?.block, true);
  assert.deepEqual(ask.entries.map((entry) => entry.note), ["no dialog"]);
  // A directory the text does not tell, or one outside any project, counts as ask.
  for (const command of ["cd $DIR && oasis stop --database", "pushd /work/other; popd; oasis stop --database",
    "cd /tmp/elsewhere && oasis stop --database", "cd /work/other && echo $(oasis stop --database)"]) {
    const unknown = harness({ roots, settings: { [ROOT]: "allow", [OTHER]: "allow" }, hasUI: false });
    assert.equal((await unknown.gate(command))?.block, true, command);
    assert.deepEqual(unknown.entries.map((entry) => entry.note), ["no dialog"], command);
  }
  // env -C and sudo -D change the directory too.
  for (const command of ["env -C /work/other oasis stop --database", "sudo -D /work/other oasis stop --database"]) {
    const wrapped = harness({ roots, settings: { [ROOT]: "allow", [OTHER]: "deny" } });
    assert.match((await wrapped.gate(command) as { reason: string }).reason, /in the configuration of \/work\/other;/, command);
  }
  // allow in both runs without a dialog, as with --project.
  const both = harness({ roots, settings: { [ROOT]: "allow", [OTHER]: "allow" }, hasUI: false });
  assert.equal(await both.gate(drop), undefined);
  assert.deepEqual(both.entries, [{ label: "Agent command approved", command: drop, note: "agent_destructive = allow", output: "" }]);
});

// The extension's tool_call handler is toolCallRouter: Pi's event and context in, the gates' result out.
function piContext(options: { hasUI?: boolean; answers?: (string | undefined)[] } = {}) {
  const prompts: { title: string; options: unknown }[] = [];
  const answers = [...(options.answers ?? [])];
  // Pi's ui is an object whose methods may use `this`.
  const ui = {
    answers,
    async input(this: { answers: (string | undefined)[] }, title: string, _placeholder?: string, dialog?: unknown) {
      prompts.push({ title, options: dialog });
      return this.answers.shift();
    },
    notify() {},
  };
  const signal = new AbortController().signal;
  return { ctx: { cwd: `${ROOT}/addons`, hasUI: options.hasUI ?? true, signal, mode: "tui", ui }, prompts, signal };
}

function router(setting = "ask") {
  const entries: MenuEntry[] = [];
  const route = toolCallRouter({
    projectRoot: async () => ROOT, home: "/home/u", exists: () => false,
    agentDestructive: async () => setting, appendEntry: (entry) => entries.push(entry), realpath: (path) => path,
  });
  return { route, entries };
}

test("toolCallRouter sends bash to the bash gate and edit or write to the file gate, with Pi's context", async () => {
  const { route, entries } = router();
  const headless = piContext({ hasUI: false });
  assert.equal((await route({ toolName: "bash", input: { command: STOP } }, headless.ctx))?.block, true);
  assert.equal(entries.at(-1)?.note, "no dialog");
  const pi = piContext({ answers: ["yes", "no"] });
  assert.equal(await route({ toolName: "write", input: { path: WORKSPACE, content: "x" } }, pi.ctx), undefined);
  assert.deepEqual(pi.prompts[0].options, { timeout: ASK_TIMEOUT_MS, signal: pi.signal });
  assert.ok(pi.prompts[0].title.includes(`\n\nwrite ${WORKSPACE}\n\n`), pi.prompts[0].title);
  assert.deepEqual(await route({ toolName: "edit", input: { path: "../oasis-workspace.toml" } }, pi.ctx), {
    block: true,
    reason: `The user's answer did not confirm editing ${WORKSPACE}; nothing changed. Do not retry it: ask the user ` +
      "whether to make the change.",
  });
  assert.deepEqual(entries.map((entry) => [entry.label, entry.command]), [
    ["Agent command refused", STOP], ["Agent command approved", `write ${WORKSPACE}`],
    ["Agent command refused", "edit ../oasis-workspace.toml"],
  ]);
});

test("toolCallRouter leaves other tools and malformed inputs alone, and reads nothing for them", async () => {
  const { route, entries } = router();
  const pi = piContext();
  for (const event of [
    { toolName: "read", input: { path: WORKSPACE } }, { toolName: "grep", input: { pattern: "psql" } },
    { toolName: "bash", input: { command: 42 } }, { toolName: "bash", input: {} },
    { toolName: "edit", input: { path: ["x"] } }, { toolName: "write", input: {} },
    { toolName: "bash", input: { command: "git status" } }, { toolName: "edit", input: { path: "models/sale.py" } },
  ]) {
    assert.equal(await route(event, pi.ctx), undefined, JSON.stringify(event));
  }
  assert.deepEqual([pi.prompts, entries], [[], []]);
  // The deny tier still answers through the router.
  assert.deepEqual(await route({ toolName: "bash", input: { command: "psql -l" } }, pi.ctx),
    { block: true, reason: blockReason("psql", ROOT) });
});

// S1 (v0.15.1): every tool that runs shell text gets the decision of bash for the same command text.
const SHELL = ["bash", "bash_background", "monitor"];

/** The tool's input around a command, as Gentle Shell's bash_background and monitor take it. */
function shellInput(tool: string, command: unknown): Record<string, unknown> {
  return tool === "monitor" ? { command, timeout_seconds: 60 } : { command };
}

test("SHELL_TOOLS lists every tool that runs shell text, in one place", async () => {
  const destructive = await import("../lib/destructive.ts") as Record<string, unknown>;
  assert.deepEqual(destructive.SHELL_TOOLS, SHELL);
});

test("toolCallRouter denies the same command text in bash, bash_background and monitor", async () => {
  for (const tool of SHELL) {
    const { route, entries } = router();
    const pi = piContext();
    for (const [command, reason] of [
      ["psql -l", blockReason("psql", ROOT)],
      ["oasis --project /p menu", blockReason("menu", "")],
    ]) {
      assert.deepEqual(await route({ toolName: tool, input: shellInput(tool, command) }, pi.ctx),
        { block: true, reason }, `${tool}: ${command}`);
    }
    assert.deepEqual([pi.prompts, entries], [[], []], tool);
  }
});

test("toolCallRouter asks for the same command text in bash, bash_background and monitor, honoring agent_destructive", async () => {
  for (const tool of SHELL) {
    const asked = router();
    const pi = piContext({ answers: ["yes", "no"] });
    assert.equal(await asked.route({ toolName: tool, input: shellInput(tool, STOP) }, pi.ctx), undefined, tool);
    assert.deepEqual(pi.prompts[0].options, { timeout: ASK_TIMEOUT_MS, signal: pi.signal });
    assert.ok(pi.prompts[0].title.includes(`the agent wants to run\n\n${STOP}\n\n`), pi.prompts[0].title);
    const refused = await asked.route({ toolName: tool, input: shellInput(tool, STOP) }, pi.ctx);
    assert.equal(refused?.block, true, tool);
    assert.deepEqual(asked.entries.map((entry) => [entry.label, entry.command, entry.note]), [
      ["Agent command approved", STOP, "typed yes"], ["Agent command refused", STOP, "wrong answer"],
    ], tool);

    const headless = router();
    const none = piContext({ hasUI: false });
    assert.equal((await headless.route({ toolName: tool, input: shellInput(tool, STOP) }, none.ctx))?.block, true, tool);
    assert.deepEqual(headless.entries.map((entry) => [entry.label, entry.note]), [["Agent command refused", "no dialog"]]);

    const allowed = router("allow");
    const quiet = piContext();
    assert.equal(await allowed.route({ toolName: tool, input: shellInput(tool, DROP) }, quiet.ctx), undefined, tool);
    assert.deepEqual(quiet.prompts, []);
    assert.deepEqual(allowed.entries, [{ label: "Agent command approved", command: DROP, note: "agent_destructive = allow", output: "" }]);

    // The same decision as bash, reason included, for the deny setting.
    const denied = router("deny");
    const bash = router("deny");
    assert.deepEqual(await denied.route({ toolName: tool, input: shellInput(tool, STOP) }, piContext().ctx),
      await bash.route({ toolName: "bash", input: { command: STOP } }, piContext().ctx), tool);
    assert.equal(denied.entries.at(-1)?.note, "agent_destructive = deny");
  }
});

test("toolCallRouter allows other command text in every shell tool, and leaves inputs without one and other tools alone", async () => {
  const { route, entries } = router();
  const pi = piContext();
  for (const tool of SHELL) {
    for (const input of [shellInput(tool, "git status"), shellInput(tool, 42), shellInput(tool, undefined), {}]) {
      assert.equal(await route({ toolName: tool, input }, pi.ctx), undefined, `${tool} ${JSON.stringify(input)}`);
    }
    assert.equal(await route({ toolName: tool, input: undefined }, pi.ctx), undefined, tool);
  }
  for (const event of [
    { toolName: "job_stop", input: { id: "1" } }, { toolName: "job_list", input: {} },
    { toolName: "codemode", input: { command: "psql -l" } }, { toolName: "shell", input: { command: STOP } },
  ]) {
    assert.equal(await route(event, pi.ctx), undefined, JSON.stringify(event));
  }
  assert.deepEqual([pi.prompts, entries], [[], []]);
});

test("settingReader returns AGENT_DESTRUCTIVE of config.py, and undefined (ask) when it cannot be read", async () => {
  const read = settingReader(async (root) => {
    if (root === "/fails") throw new Error("spawn failed");
    if (root === "/broken") return { error: "Invalid tooling configuration." };
    return { config: root === "/old" ? { ODOO_VERSION: "19.0" } : { AGENT_DESTRUCTIVE: "allow" } };
  });
  assert.equal(await read("/work/shop"), "allow");
  for (const root of ["/fails", "/broken", "/old"]) assert.equal(await read(root), undefined, root);
});

test("the extension's tool_call handler is toolCallRouter over the Pi effects", async () => {
  const { readFileSync } = await import("node:fs");
  const flat = readFileSync(new URL("../extensions/oasis.ts", import.meta.url), "utf8").split(/\s+/).join(" ");
  for (const part of [
    "const routeToolCall = toolCallRouter(gateEffects);",
    "pi.on(\"tool_call\", (event, ctx) => routeToolCall(event, ctx));",
    "agentDestructive: settingReader(projectConfig),",
    "appendEntry: (entry) => pi.appendEntry(DECISION_ENTRY, entry),",
    "pi.registerEntryRenderer(DECISION_ENTRY, renderMenuEntry);",
  ]) {
    assert.ok(flat.includes(part), part);
  }
  const lib = readFileSync(new URL("../lib/destructive.ts", import.meta.url), "utf8");
  assert.deepEqual([...lib.matchAll(/ from "([^"]+)";/g)].map((match) => match[1]),
    ["node:path", "./bash-guard.ts", "./menu.ts", "./project.ts"]);
});

test("a line is judged on every denied program: user-run tools anywhere on it block in every session", async () => {
  const outside = harness({ root: null });
  assert.deepEqual(await outside.gate("psql -l; oasis --project /p menu"), { block: true, reason: blockReason("menu", "") });
  assert.deepEqual(await outside.gate("dropdb x && oasis --project /p menu"), { block: true, reason: blockReason("menu", "") });
  // Single commands keep their tier: odoo-bin, dropdb and psql run outside Odoo projects.
  for (const command of ["psql -l", "dropdb x", "odoo-bin --version", "psql -l; dropdb x"]) {
    assert.equal(await outside.gate(command), undefined, command);
  }
  // In an Odoo project the first denied program still gives the reason, as before.
  const inProject = harness();
  assert.deepEqual(await inProject.gate("psql -l; oasis --project /p menu"),
    { block: true, reason: blockReason("psql", ROOT) });
  assert.deepEqual(await inProject.gate("psql -l"), { block: true, reason: blockReason("psql", ROOT) });
  assert.deepEqual(await inProject.gate("oasis --project /p menu; psql -l"),
    { block: true, reason: blockReason("menu", "") });
  for (const run of [inProject, outside]) assert.deepEqual([run.prompts, run.entries], [[], []]);
});

const WORKSPACE = `${ROOT}/oasis-workspace.toml`;
const NOTE = "(it holds [tooling].agent_destructive)";

test("the agent's edit and write of a setting file ask to type yes, naming the file, and are recorded", async () => {
  for (const [tool, path, file] of [
    ["edit", "../oasis-workspace.toml", WORKSPACE],
    ["edit", "@../oasis-workspace.toml", WORKSPACE],
    ["write", "/work/oasis-workspace.toml", "/work/oasis-workspace.toml"],
  ] as const) {
    const run = harness({ answers: ["yes"] });
    assert.equal(await run.file(tool, path), undefined, path);
    assert.equal(run.prompts.length, 1, path);
    assert.equal(run.prompts[0].title,
      `oasis: the agent wants to call\n\n${tool} ${path}\n\n` +
        `Type yes to allow editing ${file} ${NOTE}. Esc, another answer or no answer within ${SECONDS} s refuses.`);
    assert.deepEqual(run.prompts[0].options, { timeout: ASK_TIMEOUT_MS, signal: run.signal });
    assert.deepEqual(run.entries, [{ label: "Agent command approved", command: `${tool} ${path}`, note: "typed yes", output: "" }]);
  }
});

test("a refused, unanswered or dialog-less edit of a setting file is blocked and recorded", async () => {
  const path = "../oasis-workspace.toml";
  const wrong = harness({ answers: ["allow"] });
  assert.deepEqual(await wrong.file("edit", path), {
    block: true,
    reason: `The user's answer did not confirm editing ${WORKSPACE}; nothing changed. Do not retry it: ask the user ` +
      "whether to make the change.",
  });
  assert.deepEqual(wrong.entries, [{ label: "Agent command refused", command: `edit ${path}`, note: "wrong answer", output: "" }]);
  const none = harness({ answers: [undefined] });
  assert.equal((await none.file("write", path))?.block, true);
  assert.equal(none.entries[0].note, "no answer");
  const headless = harness({ hasUI: false });
  assert.deepEqual(await headless.file("edit", path), {
    block: true,
    reason: `editing ${WORKSPACE} needs the user's confirmation in a dialog, and this session has none (a subagent or a ` +
      "headless run); nothing changed. Ask the user to make the change or to confirm it from an interactive session.",
  });
  assert.deepEqual(headless.prompts, []);
  assert.deepEqual(headless.entries, [{ label: "Agent command refused", command: `edit ${path}`, note: "no dialog", output: "" }]);
  const denied = harness({ setting: "deny" });
  assert.deepEqual(await denied.file("edit", path), {
    block: true,
    reason: `editing ${WORKSPACE} is denied to agents by [tooling].agent_destructive = "deny" in this project's ` +
      "configuration; nothing changed. Ask the user to make the change.",
  });
  // allow never lets the agent change its own permission: the dialog still runs, and without a
  // UI the edit is refused.
  const allowedHeadless = harness({ setting: "allow", hasUI: false });
  assert.equal((await allowedHeadless.file("edit", path) as { block: boolean }).block, true);
  assert.deepEqual(allowedHeadless.entries, [{ label: "Agent command refused", command: `edit ${path}`, note: "no dialog", output: "" }]);
  const allowedDialog = harness({ setting: "allow", answers: ["yes"] });
  assert.equal(await allowedDialog.file("edit", path), undefined);
  assert.equal(allowedDialog.prompts.length, 1);
  assert.deepEqual(allowedDialog.entries.map((entry) => entry.label), ["Agent command approved"]);
});

test("other files, setting names below the session directory and symlinks are judged by the file they reach", async () => {
  const run = harness();
  for (const path of [
    `${ROOT}/addons/coffee/models/sale.py`, `${ROOT}/dev/odoo.conf`, `${ROOT}/oasis-checkout.toml.bak`,
    `${ROOT}/addons/coffee/oasis-workspace.toml`, "/tmp/oasis-workspace.toml", `${ROOT}/oasis-workspace.toml.bak`,
    // An oasis-checkout.toml below the checkout root: tools/config.py never reads it.
    `${ROOT}/addons/coffee/oasis-checkout.toml`,
    // The profile format before v0.12.0: nothing reads it since v0.21.0 (S6).
    `${ROOT}/.odoo19-agent.toml`, `${ROOT}/addons/.odoo19-agent.toml`,
  ]) {
    assert.equal(await run.file("write", path), undefined, path);
  }
  assert.deepEqual([run.prompts, run.entries, run.settingsRead], [[], [], []]);
  // A link (or a linked directory) that reaches a setting file is that file.
  const linked = harness({
    hasUI: false,
    realpath: (path) => (path === "/tmp/link.toml" ? WORKSPACE : path.replace(/^\/tmp\/dir\//, `${ROOT}/`)),
  });
  for (const path of ["/tmp/link.toml", "/tmp/dir/oasis-workspace.toml"]) {
    assert.equal((await linked.file("edit", path))?.block, true, path);
  }
  assert.match(linked.entries[0].command, /^edit \/tmp\/link\.toml$/);
  // A session directory reached through a link: the files above its real path count too.
  const real = harness({ cwd: "/home/u/shop/addons", hasUI: false, realpath: (path) => path.replace("/home/u/shop", ROOT) });
  assert.equal((await real.file("write", `${ROOT}/oasis-workspace.toml`))?.block, true);
});

test("bash writes to a setting file go through the same dialog, in the order bash reaches them", async () => {
  const command = `oasis --project /work/shop stop --database && echo "agent_destructive = 'allow'" >> ${WORKSPACE}`;
  const run = harness({ answers: ["yes", "yes"] });
  assert.equal(await run.gate(command), undefined);
  assert.equal(run.prompts.length, 2);
  assert.equal(run.prompts[1].title,
    `oasis: the agent wants to run\n\n${command}\n\n` +
      `Type yes to allow editing ${WORKSPACE} ${NOTE}. Esc, another answer or no answer within ${SECONDS} s refuses.`);
  assert.deepEqual(run.entries, [{ label: "Agent command approved", command, note: "typed yes, yes", output: "" }]);
  const refused = harness({ answers: ["no"] });
  assert.deepEqual(await refused.gate(`sed -i s/ask/allow/ ${WORKSPACE}`), {
    block: true,
    reason: `The user's answer did not confirm editing ${WORKSPACE}; nothing changed. Do not retry it: ask the user ` +
      "whether to make the change.",
  });
  // Reading a setting file is not an edit.
  const read = harness();
  assert.equal(await read.gate(`cat ${WORKSPACE}; grep agent_destructive ../oasis-workspace.toml`), undefined);
  assert.deepEqual(read.prompts, []);
});

// v0.14.0 S4: a linked worktree outside the workspace directory is governed by the workspace file
// its main checkout reads, found through git. That file is a setting file of the worktree's
// sessions like one above them, and the stricter-of-two rule reads it through tools/config.py.
// Real git and the real config.py in scratch directories; never the user's configuration.
const GIT_ENV = {
  ...Object.fromEntries(Object.entries(process.env).filter(([key]) => !key.startsWith("GIT_"))),
  GIT_CONFIG_GLOBAL: "/dev/null", GIT_CONFIG_NOSYSTEM: "1",
  GIT_AUTHOR_NAME: "oasis tests", GIT_AUTHOR_EMAIL: "tests@example.invalid",
  GIT_COMMITTER_NAME: "oasis tests", GIT_COMMITTER_EMAIL: "tests@example.invalid",
};

async function worktreeOutside(agentDestructive: string) {
  const { execFileSync } = await import("node:child_process");
  const { mkdtempSync, mkdirSync, readFileSync: read, realpathSync, symlinkSync, writeFileSync } = await import("node:fs");
  const { tmpdir } = await import("node:os");
  const { join } = await import("node:path");
  const { fileURLToPath } = await import("node:url");
  const { projectRootResolver } = await import("../lib/project.ts");
  const base = realpathSync(mkdtempSync(join(tmpdir(), "oasis-gate-")));
  const env = { ...GIT_ENV, GIT_CEILING_DIRECTORIES: realpathSync(tmpdir()), XDG_CONFIG_HOME: join(base, "xdg") };
  const git = (cwd: string, ...args: string[]) => execFileSync("git",
    ["-c", "init.defaultBranch=main", "-c", "commit.gpgsign=false", "-C", cwd, ...args], { env, encoding: "utf8" }).trim();
  const project = join(base, "project");
  const main = join(project, "acme");
  mkdirSync(main, { recursive: true });
  const fixture = read(new URL("../../tests/fixture-workspace.toml", import.meta.url), "utf8").replaceAll("'../../", "'");
  const workspace = join(project, "oasis-workspace.toml");
  writeFileSync(workspace, `${fixture}agent_destructive = '${agentDestructive}'\n`);
  writeFileSync(join(main, "README.md"), "fixture\n");
  git(main, "init", "-q");
  git(main, "add", "README.md");
  git(main, "commit", "-q", "-m", "init");
  const linked = join(base, "elsewhere", "acme-feat");
  git(main, "worktree", "add", "-q", "-b", "feat", linked);
  const cwd = join(linked, "addons");
  mkdirSync(cwd);
  symlinkSync(workspace, join(base, "link.toml"));
  const reader = fileURLToPath(new URL("../../tools/config.py", import.meta.url));
  const configOf = async (root: string) => {
    try {
      const output = execFileSync("python3", ["-B", reader, root], { env, encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] });
      return { config: Object.fromEntries(output.split("\n").filter((line) => /^[A-Z_]+=/.test(line))
        .map((line) => [line.slice(0, line.indexOf("=")), line.slice(line.indexOf("=") + 1)])) };
    } catch (error) {
      return { error: String(error) };
    }
  };
  const gitTop = async (start: string) => {
    try {
      return git(start, "rev-parse", "--show-toplevel");
    } catch {
      return null;
    }
  };
  const entries: MenuEntry[] = [];
  const prompts: string[] = [];
  const answers: (string | undefined)[] = [];
  const effects: GateEffects = {
    projectRoot: projectRootResolver(gitTop),
    home: "/home/u",
    exists: () => false,
    agentDestructive: settingReader(configOf),
    appendEntry: (entry) => entries.push(entry),
    realpath: realpathSync,
    environment: {},
  };
  const context = (hasUI: boolean, at = cwd): GateContext => ({
    cwd: at, hasUI, ui: { input: async (title) => {
      prompts.push(title);
      return answers.shift();
    } },
  });
  return {
    base, project, main, linked, cwd, workspace, entries, prompts, answers,
    gate: (command: string, hasUI = true, at?: string) => agentGate(effects)(command, context(hasUI, at)),
    file: (tool: string, path: string, hasUI = true) => agentFileGate(effects)(tool, path, context(hasUI)),
    cleanup: async () => (await import("node:fs")).rmSync(base, { recursive: true, force: true }),
  };
}

test("in a worktree outside the workspace, the main checkout's workspace file found through git always asks", async () => {
  // allow never covers it, as for a workspace file above the session.
  const run = await worktreeOutside("allow");
  try {
    const writes: [string, string][] = [
      ["write", run.workspace],
      ["edit", "../../../project/oasis-workspace.toml"],
      ["edit", `${run.base}/link.toml`],
    ];
    for (const [tool, path] of writes) {
      run.answers.push("yes");
      assert.equal(await run.file(tool, path), undefined, path);
      assert.equal(run.prompts.at(-1),
        `oasis: the agent wants to call\n\n${tool} ${path}\n\n` +
          `Type yes to allow editing ${run.workspace} ${NOTE}. ` +
          `Esc, another answer or no answer within ${SECONDS} s refuses.`, path);
    }
    for (const command of [`echo "agent_destructive = 'allow'" >> ${run.workspace}`,
      `sed -i s/allow/deny/ ../../../project/oasis-workspace.toml`, `cp new.toml ${run.workspace}`]) {
      run.answers.push("yes");
      assert.equal(await run.gate(command), undefined, command);
      assert.match(run.prompts.at(-1)!, new RegExp(`Type yes to allow editing ${run.workspace} \\(it holds`), command);
    }
    assert.equal(run.prompts.length, writes.length + 3);
    assert.deepEqual(run.entries.map((entry) => entry.note), Array(writes.length + 3).fill("typed yes"));
    // Refused without a dialog, and other files of the main checkout stay allowed.
    assert.equal((await run.file("edit", run.workspace, false))?.block, true);
    assert.equal(run.entries.at(-1)?.note, "no dialog");
    const before = run.prompts.length;
    assert.equal(await run.file("write", `${run.main}/README.md`), undefined);
    assert.equal(await run.gate(`echo x >> ${run.project}/notes.toml`), undefined);
    assert.equal(run.prompts.length, before);
  } finally {
    await run.cleanup();
  }
});

test("the stricter-of-two rule reads the main checkout's workspace file for a worktree outside it", async () => {
  const run = await worktreeOutside("deny");
  try {
    // The session's own project: the worktree, whose setting is the main checkout's file.
    assert.deepEqual(await run.gate("oasis stop --database"), {
      block: true,
      reason: "stop --database is denied to agents by [tooling].agent_destructive = \"deny\" in this project's " +
        "configuration; nothing ran. Ask the user to run it.",
    });
    // A target in that worktree from a session elsewhere (not an Odoo project: ask) is denied by it.
    const outside = `${run.base}/plain`;
    (await import("node:fs")).mkdirSync(outside);
    for (const command of [`cd ${run.linked} && oasis gc --apply --trash`,
      `oasis --project ${run.linked} drop-database cc_dev_feat_x`]) {
      const result = await run.gate(command, true, outside) as { reason: string };
      assert.match(result.reason, new RegExp(`= "deny" in the configuration of ${run.linked}; nothing ran`), command);
    }
    assert.deepEqual(run.prompts, []);
  } finally {
    await run.cleanup();
  }
});

// v0.15.0 S6: a checkout's oasis-checkout.toml sets checkout_slug (the database namespace) and the
// environment, so the agent's changes to it always ask, like the workspace file's.
const CHECKOUT_NOTE = "(it sets checkout_slug, the database namespace, and the environment)";
const CHECKOUT = `${ROOT}/oasis-checkout.toml`;

test("the agent's edit and write of a checkout's oasis-checkout.toml always ask, saying why", async () => {
  const cases: [string, string, string][] = [
    ["write", CHECKOUT, CHECKOUT],
    ["edit", "../oasis-checkout.toml", CHECKOUT],
    ["edit", "@../oasis-checkout.toml", CHECKOUT],
    // The checkout a --project or cd target names.
    ["write", `${OTHER}/oasis-checkout.toml`, `${OTHER}/oasis-checkout.toml`],
    // A link that reaches it.
    ["edit", "/tmp/checkout-link", CHECKOUT],
  ];
  for (const [tool, path, file] of cases) {
    const run = harness({
      roots, setting: "allow", answers: ["yes"],
      realpath: (target) => (target === "/tmp/checkout-link" ? CHECKOUT : target),
    });
    assert.equal(await run.file(tool, path), undefined, path);
    assert.deepEqual(run.prompts.map((prompt) => prompt.title), [
      `oasis: the agent wants to call\n\n${tool} ${path}\n\n` +
        `Type yes to allow editing ${file} ${CHECKOUT_NOTE}. Esc, another answer or no answer within ${SECONDS} s refuses.`,
    ], path);
    assert.deepEqual(run.entries, [{ label: "Agent command approved", command: `${tool} ${path}`, note: "typed yes", output: "" }]);
  }
  // allow never covers it: without a UI it is refused; deny blocks it; a wrong answer refuses.
  const headless = harness({ roots, setting: "allow", hasUI: false });
  assert.deepEqual(await headless.file("write", CHECKOUT), {
    block: true,
    reason: `editing ${CHECKOUT} needs the user's confirmation in a dialog, and this session has none (a subagent or a ` +
      "headless run); nothing changed. Ask the user to make the change or to confirm it from an interactive session.",
  });
  assert.deepEqual(headless.entries.map((entry) => entry.note), ["no dialog"]);
  const denied = harness({ roots, setting: "deny" });
  assert.deepEqual(await denied.file("edit", "../oasis-checkout.toml"), {
    block: true,
    reason: `editing ${CHECKOUT} is denied to agents by [tooling].agent_destructive = "deny" in this project's ` +
      "configuration; nothing changed. Ask the user to make the change.",
  });
  const wrong = harness({ roots, answers: ["no"] });
  assert.deepEqual(await wrong.file("edit", CHECKOUT), {
    block: true,
    reason: `The user's answer did not confirm editing ${CHECKOUT}; nothing changed. Do not retry it: ask the user ` +
      "whether to make the change.",
  });
});

test("bash writes to a checkout's oasis-checkout.toml ask, in the session's checkout or after a literal cd", async () => {
  const command = `echo "checkout_slug = 'x'" >> ../oasis-checkout.toml`;
  const asked = harness({ roots, setting: "allow", answers: ["yes"] });
  assert.equal(await asked.gate(command), undefined);
  assert.deepEqual(asked.prompts.map((prompt) => prompt.title), [
    `oasis: the agent wants to run\n\n${command}\n\n` +
      `Type yes to allow editing ${CHECKOUT} ${CHECKOUT_NOTE}. Esc, another answer or no answer within ${SECONDS} s refuses.`,
  ]);
  assert.deepEqual(asked.entries, [{ label: "Agent command approved", command, note: "typed yes", output: "" }]);
  for (const write of [
    `echo x > ${CHECKOUT}`, `cd ${ROOT} && tee oasis-checkout.toml < x`, "cd /work/other && sed -i s/a/b/ oasis-checkout.toml",
    "cp new/oasis-checkout.toml /work/other/", "mv new.toml /work/other/oasis-checkout.toml",
    // A target the text does not tell counts by its name.
    'echo x > "$ROOT"/oasis-checkout.toml',
  ]) {
    const run = harness({ roots, setting: "allow", hasUI: false });
    assert.equal((await run.gate(write))?.block, true, write);
    assert.deepEqual(run.entries.map((entry) => entry.note), ["no dialog"], write);
  }
  // Reads, another name, and an oasis-checkout.toml that is not at a checkout root do not ask.
  const run = harness({ roots, setting: "allow" });
  for (const command of [
    `cat ../oasis-checkout.toml; grep checkout_slug ${CHECKOUT}`, `cp ${CHECKOUT} /tmp/copy.toml`,
    `cp ${CHECKOUT} /tmp/`, "echo x > /tmp/oasis-checkout.toml", `echo x > ${ROOT}/addons/coffee/oasis-checkout.toml`,
    `echo x > ${ROOT}/checkout.toml`,
  ]) {
    assert.equal(await run.gate(command), undefined, command);
  }
  for (const path of ["/tmp/oasis-checkout.toml", `${ROOT}/addons/oasis-checkout.toml`, `${OTHER}/oasis-checkout.toml.orig`]) {
    assert.equal(await run.file("write", path), undefined, path);
  }
  assert.deepEqual([run.prompts, run.entries], [[], []]);
});

test("an oasis-checkout.toml reached through a linked directory asks only at a checkout root", async () => {
  // /links/shop is a link to the checkout root, /links/below to a directory below it, /links/out to a
  // directory outside any project; /links/held is a link to the root whose oasis-checkout.toml is itself
  // a link to a file outside it (tools/config.py reads that file through the root).
  const links: Record<string, string> = {
    "/links/shop": ROOT, "/links/below": `${ROOT}/addons`, "/links/out": "/tmp/out", "/links/held": ROOT,
    "/links/held/oasis-checkout.toml": "/tmp/held/oasis-checkout.toml",
  };
  const realpath = (path: string) => {
    if (path in links) return links[path];
    const dir = Object.keys(links).find((link) => path.startsWith(`${link}/`));
    return dir ? links[dir] + path.slice(dir.length) : path;
  };
  // The root of a written path, as the resolver finds it: by its real path (projectRootResolver), or
  // by the written path only (a resolver that does not follow links).
  const resolving = (dir: string) => roots(realpath(dir));
  const cases: [string, (dir: string) => string | null, string][] = [
    // The real path's directory is the root (the written one has none).
    ["/links/shop/oasis-checkout.toml", roots, "/links/shop/oasis-checkout.toml"],
    // The written directory's root is its real path (the real file lies outside every project).
    ["/links/held/oasis-checkout.toml", resolving, "/links/held/oasis-checkout.toml"],
  ];
  for (const [path, resolver, file] of cases) {
    for (const tool of ["write", "edit"]) {
      const run = harness({ roots: resolver, realpath, setting: "allow", answers: ["yes"] });
      assert.equal(await run.file(tool, path), undefined, path);
      assert.deepEqual(run.prompts.map((prompt) => prompt.title), [
        `oasis: the agent wants to call\n\n${tool} ${path}\n\n` +
          `Type yes to allow editing ${file} ${CHECKOUT_NOTE}. Esc, another answer or no answer within ${SECONDS} s refuses.`,
      ], path);
      assert.deepEqual(run.entries.map((entry) => entry.note), ["typed yes"], path);
    }
    const headless = harness({ roots: resolver, realpath, setting: "allow", hasUI: false });
    assert.equal((await headless.gate(`echo "checkout_slug = 'x'" > ${path}`))?.block, true, path);
    assert.deepEqual(headless.entries.map((entry) => entry.note), ["no dialog"], path);
  }
  // Below a checkout root or outside every project, through a link: never read, no dialog.
  for (const resolver of [roots, resolving]) {
    const run = harness({ roots: resolver, realpath, setting: "allow" });
    for (const path of ["/links/below/oasis-checkout.toml", "/links/out/oasis-checkout.toml"]) {
      assert.equal(await run.file("write", path), undefined, path);
      assert.equal(await run.gate(`echo x > ${path}`), undefined, path);
    }
    assert.deepEqual([run.prompts, run.entries], [[], []]);
  }
});

test("on disk, a linked directory reaches a checkout's oasis-checkout.toml only at its root", async () => {
  const run = await worktreeOutside("allow");
  try {
    const { symlinkSync } = await import("node:fs");
    for (const [link, target] of [["root-link", run.linked], ["below-link", run.cwd],
      ["outside-link", `${run.base}/elsewhere`], ["main-link", run.main]]) {
      symlinkSync(target, `${run.base}/${link}`);
    }
    for (const link of ["root-link", "main-link"]) {
      const path = `${run.base}/${link}/oasis-checkout.toml`;
      run.answers.push("yes");
      assert.equal(await run.file("write", path), undefined, path);
      assert.equal(run.prompts.at(-1),
        `oasis: the agent wants to call\n\nwrite ${path}\n\n` +
          `Type yes to allow editing ${path} ${CHECKOUT_NOTE}. Esc, another answer or no answer within ${SECONDS} s refuses.`,
        path);
      assert.equal((await run.gate(`echo x > ${path}`, false))?.block, true, path);
      assert.equal(run.entries.at(-1)?.note, "no dialog");
    }
    const before = [run.prompts.length, run.entries.length];
    for (const link of ["below-link", "outside-link"]) {
      const path = `${run.base}/${link}/oasis-checkout.toml`;
      assert.equal(await run.file("write", path), undefined, path);
      assert.equal(await run.gate(`echo x > ${path}`, false), undefined, path);
    }
    assert.deepEqual([run.prompts.length, run.entries.length], before);
  } finally {
    await run.cleanup();
  }
});

test("a linked worktree's oasis-checkout.toml, found through git, and the main checkout's always ask", async () => {
  const run = await worktreeOutside("allow");
  try {
    const files: [string, string, string][] = [
      ["write", `${run.linked}/oasis-checkout.toml`, `${run.linked}/oasis-checkout.toml`],
      ["edit", "../oasis-checkout.toml", `${run.linked}/oasis-checkout.toml`],
      ["write", `${run.main}/oasis-checkout.toml`, `${run.main}/oasis-checkout.toml`],
    ];
    for (const [tool, path, file] of files) {
      run.answers.push("yes");
      assert.equal(await run.file(tool, path), undefined, path);
      assert.equal(run.prompts.at(-1),
        `oasis: the agent wants to call\n\n${tool} ${path}\n\n` +
          `Type yes to allow editing ${file} ${CHECKOUT_NOTE}. Esc, another answer or no answer within ${SECONDS} s refuses.`,
        path);
    }
    run.answers.push("yes");
    assert.equal(await run.gate("echo \"checkout_slug = 'feat'\" > ../oasis-checkout.toml"), undefined);
    assert.match(run.prompts.at(-1)!, new RegExp(`Type yes to allow editing ${run.linked}/oasis-checkout\\.toml \\(it sets`));
    assert.equal((await run.file("write", `${run.linked}/oasis-checkout.toml`, false))?.block, true);
    assert.equal(run.entries.at(-1)?.note, "no dialog");
    // Below the worktree's root, or outside any checkout: not read by tools/config.py, no dialog.
    const before = run.prompts.length;
    for (const path of [`${run.cwd}/oasis-checkout.toml`, `${run.base}/elsewhere/oasis-checkout.toml`]) {
      assert.equal(await run.file("write", path), undefined, path);
    }
    assert.equal(run.prompts.length, before);
  } finally {
    await run.cleanup();
  }
});

// The machine file holds the Odoo source of each series (v0.14.0 S2, S10): the agent's changes to it
// ask too, wherever the session runs, whatever agent_destructive says.
const MACHINE_NOTE = "(the machine file: it holds the Odoo source paths)";

test("the agent's edits of the machine file always ask, at $XDG_CONFIG_HOME or ~/.config", async () => {
  const cases: [Record<string, string | undefined>, string, string][] = [
    [{}, "write", "/home/u/.config/oasis/config.toml"],
    [{}, "edit", "~/.config/oasis/config.toml"],
    [{ XDG_CONFIG_HOME: "/xdg" }, "write", "/xdg/oasis/config.toml"],
    // ~/.config stays covered when XDG_CONFIG_HOME names another directory, and a relative one is ignored.
    [{ XDG_CONFIG_HOME: "/xdg" }, "edit", "/home/u/.config/oasis/config.toml"],
    [{ XDG_CONFIG_HOME: "rel" }, "edit", "/home/u/.config/oasis/config.toml"],
  ];
  for (const [environment, tool, path] of cases) {
    const run = harness({ environment, setting: "allow", answers: ["yes"] });
    assert.equal(await run.file(tool, path), undefined, path);
    const file = path.replace(/^~/, "/home/u");
    assert.deepEqual(run.prompts.map((prompt) => prompt.title), [
      `oasis: the agent wants to call\n\n${tool} ${path}\n\n` +
        `Type yes to allow editing ${file} ${MACHINE_NOTE}. Esc, another answer or no answer within ${SECONDS} s refuses.`,
    ], path);
    assert.deepEqual(run.entries.map((entry) => entry.note), ["typed yes"], path);
  }
  // Bash writes, a target the text does not tell (by its oasis/config.toml tail), a link, no dialog, deny.
  for (const command of ["echo x > ~/.config/oasis/config.toml", "tee -a /xdg/oasis/config.toml < x",
    "cp other.toml \"$XDG_CONFIG_HOME\"/oasis/config.toml", "sed -i s/a/b/ /tmp/machine-link"]) {
    const run = harness({
      environment: { XDG_CONFIG_HOME: "/xdg" }, hasUI: false,
      realpath: (path) => (path === "/tmp/machine-link" ? "/xdg/oasis/config.toml" : path),
    });
    assert.equal((await run.gate(command))?.block, true, command);
    assert.deepEqual(run.entries.map((entry) => entry.note), ["no dialog"], command);
  }
  const denied = harness({ setting: "deny" });
  assert.match((await denied.file("edit", "/home/u/.config/oasis/config.toml") as { reason: string }).reason,
    /^editing \/home\/u\/\.config\/oasis\/config\.toml is denied to agents/);
  // Other config.toml files are not the machine file; reading it is not a change.
  const run = harness({ environment: { XDG_CONFIG_HOME: "/xdg" } });
  for (const path of ["/home/u/.config/other/config.toml", "/xdg/config.toml", "/work/shop/config.toml",
    "/home/u/.config/oasis/config.toml.bak"]) {
    assert.equal(await run.file("write", path), undefined, path);
  }
  assert.equal(await run.gate("cat ~/.config/oasis/config.toml; cp /xdg/oasis/config.toml /tmp/copy.toml"), undefined);
  assert.deepEqual([run.prompts, run.entries], [[], []]);
});
