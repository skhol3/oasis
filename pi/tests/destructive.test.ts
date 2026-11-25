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
const PURGE = "odoo19 --project /work/shop gc --apply --trash --older-than 0";
const SECONDS = ASK_TIMEOUT_MS / 1000;

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
  assert.deepEqual(await inProject.gate("oasis --project /p migrate --apply"),
    { block: true, reason: blockReason("migrate", "") });
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
    "oasis --project /work/shop status", "~/.agents/skills/odoo19/tools/stop --force",
    "~/.agents/skills/odoo19/tools/restart",
    "oasis --project /work/shop drop-database --help", "git status",
    // v0.12.1 S5: the native odoo-bin line only prints.
    "oasis --project /work/shop start --print-command -d shop_dev_x", "odoo19 --project /work/shop restart --print-command",
    "~/.agents/skills/odoo19/tools/restart --print-command --http-port 8070",
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

test("stop --database and gc --apply --trash ask to type yes", async () => {
  for (const [command, label] of [[STOP, "stop --database"], [PURGE, "gc --apply --trash"]]) {
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

// L7: the project an ask command targets (`--project`, or a tool script's OASIS_PROJECT_ROOT or
// ODOO19_PROJECT_ROOT) has a say too: the stricter of its setting and the session's decides.
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
    ["ODOO19_PROJECT_ROOT=/work/other ~/.agents/skills/odoo19/tools/stop --database", { settings: { [ROOT]: "allow" } }],
    ["OASIS_PROJECT_ROOT=$P ~/.agents/skills/odoo19/tools/stop --database", { settings: { [ROOT]: "allow" } }],
    // Set elsewhere on the line: the tool reads a root the text does not tell.
    ["export OASIS_PROJECT_ROOT=/work/other; ~/.agents/skills/odoo19/tools/stop --database", { settings: { [ROOT]: "allow" } }],
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
  assert.equal(await allowed.gate("env OASIS_PROJECT_ROOT=/work/other ~/.agents/skills/odoo19/tools/stop --database"), undefined);
  // deny there blocks a tool script too.
  const denied = harness({ roots, settings: { [ROOT]: "ask", [OTHER]: "deny" } });
  assert.match((await denied.gate("ODOO19_PROJECT_ROOT=/work/other ~/.agents/skills/odoo19/tools/stop --database") as
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
  assert.match((await denied.gate("odoo19 stop --database") as { reason: string }).reason,
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
  assert.deepEqual(await outside.gate("psql -l; oasis --project /p migrate --apply"),
    { block: true, reason: blockReason("migrate", "") });
  assert.deepEqual(await outside.gate("dropdb x && oasis --project /p menu"), { block: true, reason: blockReason("menu", "") });
  assert.deepEqual(await outside.gate("odoo-bin --version | oasis --project /p worktree-init f b"),
    { block: true, reason: blockReason("worktree-init", "") });
  // Single commands keep their tier: odoo-bin, dropdb and psql run outside Odoo projects.
  for (const command of ["psql -l", "dropdb x", "odoo-bin --version", "psql -l; dropdb x"]) {
    assert.equal(await outside.gate(command), undefined, command);
  }
  // In an Odoo project the first denied program still gives the reason, as before.
  const inProject = harness();
  assert.deepEqual(await inProject.gate("psql -l; oasis --project /p migrate --apply"),
    { block: true, reason: blockReason("psql", ROOT) });
  assert.deepEqual(await inProject.gate("psql -l"), { block: true, reason: blockReason("psql", ROOT) });
  assert.deepEqual(await inProject.gate("oasis --project /p migrate --apply; psql -l"),
    { block: true, reason: blockReason("migrate", "") });
  for (const run of [inProject, outside]) assert.deepEqual([run.prompts, run.entries], [[], []]);
});

const WORKSPACE = `${ROOT}/oasis-workspace.toml`;
const NOTE = "(it holds [tooling].agent_destructive)";

test("the agent's edit and write of a setting file ask to type yes, naming the file, and are recorded", async () => {
  for (const [tool, path, file] of [
    ["edit", "../oasis-workspace.toml", WORKSPACE],
    ["write", `${ROOT}/.odoo19-agent.toml`, `${ROOT}/.odoo19-agent.toml`],
    ["edit", "@../oasis-workspace.toml", WORKSPACE],
    ["write", "/work/oasis-workspace.toml", "/work/oasis-workspace.toml"],
    ["edit", "./.odoo19-agent.toml", `${ROOT}/addons/.odoo19-agent.toml`],
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
    `${ROOT}/addons/coffee/models/sale.py`, `${ROOT}/dev/odoo.conf`, `${ROOT}/oasis-checkout.toml`,
    `${ROOT}/addons/coffee/oasis-workspace.toml`, "/tmp/oasis-workspace.toml", `${ROOT}/oasis-workspace.toml.bak`,
  ]) {
    assert.equal(await run.file("write", path), undefined, path);
  }
  assert.deepEqual([run.prompts, run.entries, run.settingsRead], [[], [], []]);
  // A link (or a linked directory) that reaches a setting file is that file.
  const linked = harness({
    hasUI: false,
    realpath: (path) => (path === "/tmp/link.toml" ? WORKSPACE : path.replace(/^\/tmp\/dir\//, `${ROOT}/`)),
  });
  for (const path of ["/tmp/link.toml", "/tmp/dir/.odoo19-agent.toml"]) {
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
