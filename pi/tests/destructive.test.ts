import { test } from "node:test";
import assert from "node:assert/strict";
import { blockReason } from "../lib/bash-guard.ts";
import type { MenuEntry } from "../lib/menu.ts";
import { agentGate, ASK_TIMEOUT_MS, type GateContext, type GateEffects } from "../lib/destructive.ts";

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
}

function harness(options: Setup = {}) {
  const entries: MenuEntry[] = [];
  const prompts: { title: string; placeholder: string | undefined; options: { timeout?: number; signal?: AbortSignal } }[] = [];
  const settingsRead: string[] = [];
  const answers = [...(options.answers ?? [])];
  const effects: GateEffects = {
    projectRoot: async () => (options.root === undefined ? ROOT : options.root),
    home: "/home/u",
    exists: () => false,
    agentDestructive: async (root) => {
      settingsRead.push(root);
      return "setting" in options ? options.setting : "ask";
    },
    appendEntry: (entry) => entries.push(entry),
  };
  const signal = new AbortController().signal;
  const ctx: GateContext = {
    cwd: `${ROOT}/addons`,
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
  return { gate: (command: string) => gate(command, ctx), entries, prompts, settingsRead, signal };
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
    "oasis --project /work/shop drop-database --help", "git status",
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

test("the extension adapts Pi to the gate: hasUI, a timed input dialog, the profile setting and entries", async () => {
  const { readFileSync } = await import("node:fs");
  const source = readFileSync(new URL("../extensions/oasis.ts", import.meta.url), "utf8");
  const start = source.indexOf("  // Agent bash only; lib/destructive.ts decides.");
  assert.ok(start > 0);
  const block = source.slice(start, source.indexOf("  // Each tool is registered under its oasis_* name", start));
  const flat = block.split(/\s+/).join(" ");
  for (const part of [
    "pi.registerEntryRenderer(DECISION_ENTRY, renderMenuEntry);",
    "appendEntry: (entry) => pi.appendEntry(DECISION_ENTRY, entry),",
    "return (await profileConfig(root)).config?.AGENT_DESTRUCTIVE;",
    "hasUI: ctx.hasUI, signal: ctx.signal,",
    "ui: { input: (title, placeholder, options) => ctx.ui.input(title, placeholder, options) },",
  ]) {
    assert.ok(flat.includes(part), part);
  }
  // Decisions are entries, never messages for the model; the logic has no Pi imports.
  assert.ok(!/sendMessage|sendUserMessage/.test(block));
  const lib = readFileSync(new URL("../lib/destructive.ts", import.meta.url), "utf8");
  assert.deepEqual([...lib.matchAll(/ from "([^"]+)";/g)].map((match) => match[1]), ["./bash-guard.ts", "./menu.ts"]);
});
