import { test } from "node:test";
import assert from "node:assert/strict";
import {
  type AutocompleteSource, commandNameCompletions, parseCommand, registerSubcommandAutocomplete, SUBCOMMAND_SUMMARY,
  subcommandAutocomplete, SUBCOMMANDS, subcommandCompletions, USAGE, withSubcommandSuggestions,
} from "../lib/commands.ts";
import { readFileSync } from "node:fs";

test("subcommandCompletions offers every /oasis subcommand for an empty prefix", () => {
  const items = subcommandCompletions("");
  assert.deepEqual(items?.map((item) => item.value), ["setup", "doctor", "worktree ", "menu"]);
  assert.ok(items?.every((item) => item.label && item.description));
  assert.deepEqual(SUBCOMMANDS.map((item) => item.name), ["setup", "doctor", "worktree", "menu"]);
});

test("subcommandCompletions filters by prefix and stops after the first word", () => {
  assert.deepEqual(subcommandCompletions("m")?.map((item) => item.value), ["menu"]);
  assert.deepEqual(subcommandCompletions("me")?.map((item) => item.value), ["menu"]);
  assert.deepEqual(subcommandCompletions("  do")?.map((item) => item.value), ["doctor"]);
  assert.equal(subcommandCompletions("x"), null);
  assert.equal(subcommandCompletions("worktree shop"), null);
  assert.equal(subcommandCompletions("setup "), null);
});

test("parseCommand dispatches from the same table as completion and usage", () => {
  assert.deepEqual(parseCommand(""), { kind: "status" });
  assert.deepEqual(parseCommand("   "), { kind: "status" });
  for (const name of ["setup", "doctor", "menu"] as const) {
    assert.deepEqual(parseCommand(` ${name} `), { kind: "run", name, args: [] });
    assert.deepEqual(parseCommand(`${name} extra`), { kind: "usage" });
  }
  assert.deepEqual(parseCommand("worktree shop feature/shop"), {
    kind: "run", name: "worktree", args: ["shop", "feature/shop"],
  });
  assert.deepEqual(parseCommand("worktree shop"), { kind: "usage" });
  assert.deepEqual(parseCommand("worktree shop --force"), { kind: "usage" });
  assert.deepEqual(parseCommand("worktree a b c"), { kind: "usage" });
  assert.deepEqual(parseCommand("status"), { kind: "usage" });
  // v0.21.0 S6: migrate is gone (it only converted .odoo19-agent.toml).
  assert.deepEqual(parseCommand("migrate"), { kind: "usage" });
  assert.equal(USAGE, "Usage: /oasis [setup | doctor | worktree <feature> <branch> | menu]");
  for (const item of SUBCOMMANDS) assert.ok(SUBCOMMAND_SUMMARY.includes(`\`${item.name}`), item.name);
});

// S3: typing the command name suggests its subcommands before the space.
const OASIS_ITEMS = SUBCOMMANDS.map((item) => `oasis ${item.name}`);

test("commandNameCompletions offers the /oasis subcommands from two typed letters, before any space", () => {
  const oa = commandNameCompletions("/oa");
  assert.equal(oa?.prefix, "/oa");
  assert.deepEqual(oa?.items.map((item) => item.value), OASIS_ITEMS);
  assert.deepEqual(oa?.items.map((item) => item.label), OASIS_ITEMS);
  assert.deepEqual(oa?.items.map((item) => item.description), SUBCOMMANDS.map((item) => item.description));
  assert.deepEqual(commandNameCompletions("/oasis")?.items.map((item) => item.value), OASIS_ITEMS);
  assert.deepEqual(commandNameCompletions("  /oas")?.items.map((item) => item.value), OASIS_ITEMS);
  assert.equal(commandNameCompletions("  /oas")?.prefix, "/oas");
  // v0.17.0 S3: /odoo19 is gone, so `/od` suggests nothing of ours.
  for (const text of ["/o", "/", "oa", "/oasis ", "/oasis m", "/oax", "/od", "/odoo", "/odoo19", "/model", "say /oa"]) {
    assert.equal(commandNameCompletions(text), null, text);
  }
});

test("withSubcommandSuggestions adds the subcommands after their command and keeps other suggestions", () => {
  const base = { prefix: "/oa", items: [{ value: "load", label: "load" }, { value: "oasis", label: "oasis",
    description: "Odoo project status" }] };
  const merged = withSubcommandSuggestions("/oa", base);
  assert.deepEqual(merged?.items.map((item) => item.value), ["load", "oasis", ...OASIS_ITEMS]);
  assert.deepEqual(base.items.map((item) => item.value), ["load", "oasis"]);
  // Twice (a provider stacked twice) adds nothing more; no base gives the subcommands alone.
  assert.deepEqual(withSubcommandSuggestions("/oa", merged)?.items.map((item) => item.value), ["load", "oasis",
    ...OASIS_ITEMS]);
  assert.deepEqual(withSubcommandSuggestions("/oasis", null)?.items.map((item) => item.value), OASIS_ITEMS);
  // Without the command item, the subcommands go last; other text is returned unchanged.
  assert.deepEqual(withSubcommandSuggestions("/oas", { prefix: "/oas", items: [{ value: "model", label: "model" }] })
    ?.items.map((item) => item.value), ["model", ...OASIS_ITEMS]);
  const odoo = { prefix: "/od", items: [{ value: "model", label: "model" }] };
  assert.equal(withSubcommandSuggestions("/od", odoo), odoo);
  const files = { prefix: "src/", items: [{ value: "src/a.ts", label: "a.ts" }] };
  assert.equal(withSubcommandSuggestions("see src/", files), files);
  assert.equal(withSubcommandSuggestions("/model", null), null);
});

test("subcommandAutocomplete wraps the current provider and delegates everything else unchanged", async () => {
  const calls: string[] = [];
  const current: AutocompleteSource = {
    triggerCharacters: ["#"],
    async getSuggestions(lines, line, col, options) {
      calls.push(`get ${lines[line].slice(0, col)} force=${options.force ?? false}`);
      const text = lines[line].slice(0, col);
      return text.startsWith("/") ? { prefix: text, items: [{ value: "oasis", label: "oasis" }] } : null;
    },
    applyCompletion(lines, line, col, item, prefix) {
      calls.push(`apply ${item.value} ${prefix}`);
      return { lines: [`/${item.value} `], cursorLine: line, cursorCol: col };
    },
    shouldTriggerFileCompletion() {
      calls.push("files");
      return false;
    },
  };
  const provider = subcommandAutocomplete(current);
  const signal = new AbortController().signal;
  assert.deepEqual(provider.triggerCharacters, ["#"]);
  const suggested = await provider.getSuggestions(["/oa"], 0, 3, { signal });
  assert.deepEqual(suggested?.items.map((item) => item.value), ["oasis", ...OASIS_ITEMS]);
  assert.deepEqual(await provider.getSuggestions(["/oa"], 0, 3, { signal, force: true }),
    { prefix: "/oa", items: [{ value: "oasis", label: "oasis" }] });
  assert.equal(await provider.getSuggestions(["hello"], 0, 5, { signal }), null);
  assert.deepEqual(provider.applyCompletion(["/oa"], 0, 3, { value: "oasis menu", label: "oasis menu" }, "/oa"),
    { lines: ["/oasis menu "], cursorLine: 0, cursorCol: 3 });
  assert.equal(provider.shouldTriggerFileCompletion?.(["x"], 0, 1), false);
  assert.deepEqual(calls, ["get /oa force=false", "get /oa force=true", "get hello force=false",
    "apply oasis menu /oa", "files"]);
  const bare = subcommandAutocomplete({ getSuggestions: async () => null, applyCompletion: current.applyCompletion });
  assert.equal("triggerCharacters" in bare, false);
  assert.equal("shouldTriggerFileCompletion" in bare, false);
});

test("registerSubcommandAutocomplete adds the wrapping provider in the TUI only; the extension calls it per session",
  async () => {
    const signal = new AbortController().signal;
    const current: AutocompleteSource = {
      getSuggestions: async () => null,
      applyCompletion: (lines, cursorLine, cursorCol) => ({ lines, cursorLine, cursorCol }),
    };
    for (const mode of ["tui", "rpc", "json", "print"]) {
      const factories: ((current: AutocompleteSource) => AutocompleteSource)[] = [];
      const registered = registerSubcommandAutocomplete({ mode, ui: { addAutocompleteProvider: (f) => factories.push(f) } });
      assert.equal(registered, mode === "tui", mode);
      assert.equal(factories.length, mode === "tui" ? 1 : 0, mode);
      if (mode !== "tui") continue;
      // The factory wraps the provider it is given (subcommandAutocomplete): /oa gets the subcommands.
      const suggested = await factories[0](current).getSuggestions(["/oa"], 0, 3, { signal });
      assert.deepEqual(suggested?.items.map((item) => item.value), OASIS_ITEMS);
    }
    const flat = readFileSync(new URL("../extensions/oasis.ts", import.meta.url), "utf8").split(/\s+/).join(" ");
    assert.ok(flat.includes("pi.on(\"session_start\", async (_event, ctx) => { registerSubcommandAutocomplete(ctx); });"));
    assert.equal(flat.includes("addAutocompleteProvider"), false);
  });
