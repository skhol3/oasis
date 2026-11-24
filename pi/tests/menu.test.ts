import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  type Answers, askInputs, type Catalog, type CatalogAction, confirmRun, entryLines, fillTemplate, lastLines, logView,
  MENU_KEY_DEFAULT, menuHeader, menuOutput, menuShortcut, moveSelection, parseCatalog, pickerRows, type Prompter,
  RunForm, serverLine, shellJoin, sources, terminalCommand, textError, visibleStart, wrapLine,
} from "../lib/menu.ts";
import { nativeCommands } from "../lib/native.ts";
import type { CoreResult } from "../lib/tools.ts";

// A real `oasis menu --catalog` of the synthetic lifecycle fixture (tests/test_pi_layer.py checks it
// against the core), with the project at /work/a project and the entry point at /opt/oasis/oasis.
const FIXTURE = readFileSync(new URL("./fixtures/catalog.json", import.meta.url), "utf8");
const catalog = parseCatalog(FIXTURE);
const PREFIX = ["/opt/oasis/oasis", "--project", "/work/a project"];

function action(id: string): CatalogAction {
  const found = catalog.actions.find((item) => item.id === id);
  assert.ok(found, id);
  return found;
}

/** A prompter that answers from a script and records every call in order. */
function scripted(answers: (string | boolean | undefined)[]) {
  const calls: string[] = [];
  const notices: string[] = [];
  const queue = [...answers];
  const next = () => {
    assert.ok(queue.length > 0, `unexpected prompt after ${calls.join(" | ")}`);
    return queue.shift();
  };
  const prompter: Prompter = {
    async select(title, options) {
      calls.push(`select ${title} [${options.join(", ")}]`);
      return next() as string | undefined;
    },
    async input(title, placeholder) {
      calls.push(`input ${title}${placeholder ? ` (${placeholder})` : ""}`);
      return next() as string | undefined;
    },
    async confirm(title, message) {
      calls.push(`confirm ${title}: ${message}`);
      return next() as boolean;
    },
    notify(message, level) {
      notices.push(`${level}: ${message}`);
    },
  };
  return { prompter, calls, notices, left: () => queue.length };
}

function fixedChoices(modules: string[], databases: string[]) {
  const asked: string[] = [];
  return {
    asked,
    choices: async (source: "modules" | "databases") => {
      asked.push(source);
      return source === "modules" ? modules : databases;
    },
  };
}

test("parseCatalog reads the core catalog and refuses another version or malformed JSON", () => {
  assert.equal(catalog.project, "/work/a project");
  assert.deepEqual(catalog.groups.map((group) => group.id), ["server", "modules", "tests", "maintenance"]);
  assert.equal(catalog.actions.length, 27);
  assert.throws(() => parseCatalog(FIXTURE.replace('"catalog_version": 1', '"catalog_version": 2')),
    /^Error: unsupported catalog_version 2 \(this panel reads version 1\); update the oasis layer\.$/);
  assert.throws(() => parseCatalog("not json"), /^Error: the catalog is not JSON: /);
  assert.throws(() => parseCatalog("{\"catalog_version\": 1}"), /^Error: the catalog has no actions\.$/);
});

test("fillTemplate fills words, inputs, options, flags and compact in order", () => {
  assert.deepEqual(fillTemplate(action("server.start"), {}, true), [...PREFIX, "start", "--detach"]);
  assert.deepEqual(fillTemplate(action("server.start"), { database: "cc_dev_coffee" }, true),
    [...PREFIX, "start", "--detach", "-d", "cc_dev_coffee"]);
  assert.deepEqual(fillTemplate(action("modules.install"), { module: "coffee", database: "", demo: true }, true),
    [...PREFIX, "install-module", "--with-demo", "coffee"]);
  assert.deepEqual(fillTemplate(action("modules.install"), { module: "coffee", database: "cc_dev_x", demo: false }, true),
    [...PREFIX, "install-module", "coffee", "cc_dev_x"]);
  assert.deepEqual(fillTemplate(action("modules.update"), { module: "coffee", database: "cc_dev_x" }, true),
    [...PREFIX, "update-module", "--compact", "coffee", "cc_dev_x"]);
  assert.deepEqual(fillTemplate(action("modules.update"), { module: "coffee", database: "cc_dev_x" }, false),
    [...PREFIX, "update-module", "coffee", "cc_dev_x"]);
  assert.deepEqual(fillTemplate(action("tests.reuse"), { module: "coffee", only: "" }, true),
    [...PREFIX, "test-module", "--compact", "--reuse", "coffee"]);
  assert.deepEqual(fillTemplate(action("tests.class"), { module: "coffee", only: "TestCup.test_fill" }, true),
    [...PREFIX, "test-module", "--compact", "--only", "TestCup.test_fill", "coffee"]);
  assert.deepEqual(fillTemplate(action("maintenance.drop_database"), { database: "cc_dev_x", terminate: true }, true),
    [...PREFIX, "drop-database", "cc_dev_x", "--terminate"]);
  assert.deepEqual(fillTemplate(action("server.logs"), {}, true),
    ["tail", "-n", "200", "/work/a project/dev/logs/odoo19/server.log"]);
  // S6: restart with an optional database; the live log follows server.log.
  assert.deepEqual(fillTemplate(action("server.restart"), { database: "" }, true), [...PREFIX, "restart"]);
  assert.deepEqual(fillTemplate(action("server.restart"), { database: "cc_dev_coffee" }, true),
    [...PREFIX, "restart", "-d", "cc_dev_coffee"]);
  assert.deepEqual(fillTemplate(action("server.follow"), {}, true),
    ["tail", "-n", "200", "-f", "/work/a project/dev/logs/odoo19/server.log"]);
  assert.deepEqual([action("server.follow").kind, action("server.follow").follow, action("server.logs").follow],
    ["log", true, false]);
});

test("serverLine says how the checkout's server is: running on its port and pid, stopped or unknown", () => {
  assert.equal(serverLine({ server: { pid: 4242, port: 8070 } }), "server: running on port 8070 (pid 4242)");
  assert.equal(serverLine({ server: null }), "server: stopped");
  assert.equal(serverLine({ serverError: "ERROR: Runtime state directory is a symlink: /run/x" }),
    "server: unknown (Runtime state directory is a symlink: /run/x)");
  assert.equal(serverLine({}), "server: unknown");
});

test("lastLines and logView: the end of a log, without control sequences, that fits the height", () => {
  const text = Array.from({ length: 300 }, (_, index) => `line ${index + 1}`).join("\n") + "\n";
  assert.deepEqual(lastLines(text, 3), ["line 298", "line 299", "line 300"]);
  assert.deepEqual(lastLines("", 3), []);
  assert.deepEqual(lastLines("\x1b[31mred\x1b[0m\tx\r\nend", 5), ["red    x", "end"]);
  assert.deepEqual(logView(["a", "b", "c"], 5), ["a", "b", "c"]);
  assert.deepEqual(logView(["a", "b", "c"], 2), ["b", "c"]);
  assert.deepEqual(logView([], 4), ["(the server log is empty)"]);
});

test("shellJoin quotes like shlex.join and terminalCommand shows a terminal-only action with placeholders", () => {
  assert.equal(shellJoin(["a", "b c", "", "it's", "-d", "x=1", "/p/a_b.c"]), "a 'b c' '' 'it'\"'\"'s' -d x=1 /p/a_b.c");
  assert.equal(shellJoin(fillTemplate(action("server.stop"), {}, true)), "/opt/oasis/oasis --project '/work/a project' stop");
  assert.equal(terminalCommand(action("modules.init_dev")),
    "/opt/oasis/oasis --project '/work/a project' init-dev-database [--with-demo] <module> <database>");
  assert.equal(terminalCommand(action("tests.class")),
    "/opt/oasis/oasis --project '/work/a project' test-module --compact [--only <only>] <module>");
});

test("textError applies required, the catalog pattern and refuses option-like values", () => {
  const only = action("tests.class").inputs[1];
  const optional = action("tests.reuse").inputs[1];
  const feature = action("maintenance.worktree").inputs[0];
  assert.equal(textError(only, ""), "A value is required.");
  assert.equal(textError(optional, ""), null);
  assert.equal(textError(only, "Test Cup"), "--only takes a test class or Class.method.");
  assert.equal(textError(only, "TestCup.test_fill"), null);
  assert.equal(textError(feature, "--force"), "A value cannot start with -.");
  assert.equal(textError(feature, "shop"), null);
  const database = action("maintenance.create_database").inputs[0];
  assert.equal(textError(database, "bad-name"), "Database name must use only letters, numbers, and underscores.");
});

test("askInputs asks in catalog order: listed module, database with skip and typing, then the boolean", async () => {
  const { prompter, calls, notices, left } = scripted(["coffee", "(type a name)", "bad-name", "cc_new", "Yes"]);
  const { choices, asked } = fixedChoices(["coffee", "tea"], ["cc_dev_coffee"]);
  const answers = await askInputs(action("modules.install"), prompter, choices);
  assert.deepEqual(answers, { module: "coffee", database: "cc_new", demo: true });
  assert.deepEqual(calls, [
    "select Module [coffee, tea]",
    "select Database [(skip: for cc_dev_<module>), cc_dev_coffee, (type a name)]",
    "input Database",
    "input Database",
    "select Load demo data? [No, Yes]",
  ]);
  assert.deepEqual(notices, ["warning: Database name must use only letters, numbers, and underscores."]);
  assert.deepEqual(asked, ["modules", "databases"]);
  assert.equal(left(), 0);
});

test("askInputs: skip gives an empty value, a listed database is taken as is, No is false", async () => {
  let run = scripted(["coffee", "(skip: for cc_dev_<module>)", "No"]);
  assert.deepEqual(await askInputs(action("modules.install"), run.prompter, fixedChoices(["coffee"], []).choices),
    { module: "coffee", database: "", demo: false });
  run = scripted(["cc_dev_coffee", "Yes"]);
  assert.deepEqual(
    await askInputs(action("maintenance.drop_database"), run.prompter, fixedChoices([], ["cc_dev_coffee"]).choices),
    { database: "cc_dev_coffee", terminate: true });
  assert.deepEqual(run.calls, [
    "select Database [cc_dev_coffee, (type a name)]",
    "select Close its open sessions first (--terminate)? [No, Yes]",
  ]);
});

test("askInputs types a database when none are listed and re-asks an empty required value", async () => {
  const { prompter, calls, notices } = scripted(["", "cc_dev_x"]);
  const drop = action("maintenance.drop_database");
  const answers = await askInputs({ ...drop, inputs: drop.inputs.slice(0, 1) }, prompter, fixedChoices([], []).choices);
  assert.deepEqual(answers, { database: "cc_dev_x" });
  assert.deepEqual(calls, ["input Database", "input Database"]);
  assert.deepEqual(notices, ["info: No databases found.", "warning: A value is required."]);
});

test("askInputs uses the hint as placeholder of an optional text input", async () => {
  const { prompter, calls } = scripted(["coffee", ""]);
  assert.deepEqual(await askInputs(action("tests.reuse"), prompter, fixedChoices(["coffee"], []).choices),
    { module: "coffee", only: "" });
  assert.deepEqual(calls, ["select Module [coffee]",
    "input Test class (Class or Class.method) (Enter for every test of the module)"]);
});

test("askInputs stops at the first cancelled prompt and refuses an empty module list", async () => {
  for (const script of [[undefined], ["coffee", undefined], ["coffee", "(type a name)", undefined]]) {
    const { prompter, left } = scripted(script);
    assert.equal(await askInputs(action("modules.install"), prompter, fixedChoices(["coffee"], []).choices), null);
    assert.equal(left(), 0);
  }
  const boolean = scripted(["coffee", "(skip: for cc_dev_<module>)", undefined]);
  assert.equal(await askInputs(action("modules.install"), boolean.prompter, fixedChoices(["coffee"], []).choices), null);
  const empty = scripted([]);
  assert.equal(await askInputs(action("modules.update"), empty.prompter, fixedChoices([], ["cc_dev_x"]).choices), null);
  assert.deepEqual(empty.notices, ["warning: No modules found in this checkout."]);
  assert.deepEqual(empty.calls, []);
});

test("askInputs asks nothing for an action without inputs", async () => {
  const { prompter, calls } = scripted([]);
  assert.deepEqual(await askInputs(action("server.stop"), prompter, fixedChoices([], []).choices), {});
  assert.deepEqual(calls, []);
});

test("sources: modules from the catalog; databases listed once, with the waiting text, failures shown", async () => {
  const events: string[] = [];
  let result = { code: 0, stdout: "cc_dev_coffee\n\n cc_test_tea \n", stderr: "" };
  const listing = sources(catalog, {
    exec: async (argv) => {
      events.push(`exec ${argv.join(" ")}`);
      return result;
    },
    waiting: (text) => events.push(`waiting ${text ?? "-"}`),
    notify: (message, level) => events.push(`${level}: ${message}`),
  });
  assert.deepEqual(await listing("modules"), ["coffee"]);
  assert.deepEqual(await listing("databases"), ["cc_dev_coffee", "cc_test_tea"]);
  assert.deepEqual(await listing("databases"), ["cc_dev_coffee", "cc_test_tea"]);
  assert.deepEqual(events, [
    "waiting Listing databases (this may start the database service)...",
    "exec /opt/oasis/oasis --project /work/a project list-databases",
    "waiting -",
  ]);
  events.length = 0;
  result = { code: 2, stdout: "", stderr: "docker: not found\n" };
  const failing = sources(catalog, {
    exec: async () => result,
    waiting: (text) => events.push(`waiting ${text ?? "-"}`),
    notify: (message, level) => events.push(`${level}: ${message}`),
  });
  assert.deepEqual(await failing("databases"), []);
  assert.deepEqual(events.slice(1), ["waiting -", "error: Cannot list the databases (exit 2):\ndocker: not found"]);
});

test("confirmRun: typed database or yes for destructive actions, a plain confirm for user-run ones", async () => {
  const drop: Answers = { database: "cc_dev_x", terminate: false };
  const command = "oasis drop-database cc_dev_x";
  let run = scripted(["cc_dev_x"]);
  assert.equal(await confirmRun(action("maintenance.drop_database"), drop, command, run.prompter), true);
  assert.deepEqual(run.calls, [`input Move a database to the trash\n${command}\nType the database name to confirm (cc_dev_x)`]);
  for (const typed of ["cc_dev_y", "", undefined]) {
    run = scripted([typed]);
    assert.equal(await confirmRun(action("maintenance.drop_database"), drop, command, run.prompter), false);
  }
  for (const id of ["server.stop_database", "maintenance.gc_apply", "maintenance.migrate"]) {
    run = scripted(["yes"]);
    assert.equal(await confirmRun(action(id), {}, "c", run.prompter), true, id);
    assert.deepEqual(run.calls, [`input ${action(id).label}\nc\nType yes to confirm`]);
    run = scripted(["YES"]);
    assert.equal(await confirmRun(action(id), {}, "c", run.prompter), false, id);
  }
  run = scripted([true]);
  assert.equal(await confirmRun(action("maintenance.worktree"), {}, "c w b", run.prompter), true);
  assert.deepEqual(run.calls, ["confirm Create a linked worktree: c w b\n\nRun this command?"]);
  run = scripted([false]);
  assert.equal(await confirmRun(action("maintenance.worktree"), {}, "c w b", run.prompter), false);
  // v0.12.0 (S5): every other action shows its filled command and runs only after Yes.
  for (const id of ["server.status", "tests.module", "modules.install", "maintenance.migrate_plan", "server.logs"]) {
    run = scripted([true]);
    assert.equal(await confirmRun(action(id), {}, "c", run.prompter), true, id);
    assert.deepEqual(run.calls, [`confirm ${action(id).label}: c\n\nRun this command?`], id);
    run = scripted([false]);
    assert.equal(await confirmRun(action(id), {}, "c", run.prompter), false, id);
  }
  // Start or restart without a database says what Odoo will use instead (S3).
  run = scripted([true]);
  assert.equal(await confirmRun(action("server.start"), { database: "" }, "c", run.prompter, catalog), true);
  assert.deepEqual(run.calls, [
    "confirm Start the server in the background: c\n\nNo database chosen: odoo.conf sets no db_name, so Odoo " +
      "starts without a database.\n\nRun this command?",
  ]);
  run = scripted([true]);
  await confirmRun(action("server.start"), { database: "cc_dev_coffee" }, "c", run.prompter, catalog);
  assert.deepEqual(run.calls, ["confirm Start the server in the background: c\n\nRun this command?"]);
});

const STAMP = "2026-11-16 18:00:00,123 4242";
const LOGS: Record<string, string> = {
  "/w/run-1/stdout.log": `${STAMP} INFO db odoo.tests.result: 0 failed, 0 error(s) of 0 tests`,
  "/w/run-1/stderr.log": "",
};
const COMPACT = { code: 0, stdout: "phase=tests database=cc_test_coffee exit=0\nstdout_log=/w/run-1/stdout.log\n" +
  "stderr_log=/w/run-1/stderr.log\n", stderr: "" };

test("menuOutput summarizes test and update runs like the agent tools and shows other output whole", () => {
  const readLog = (path: string) => LOGS[path] ?? "";
  const tests = menuOutput(action("tests.class"), { module: "coffee", only: "TestNone" }, COMPACT, readLog);
  assert.match(tests, /^module=coffee database=cc_test_coffee exit=0\n/);
  assert.match(tests, /\nno test matched only=TestNone: check the class and method names\n/);
  assert.match(tests, /\nlogs: \/w\/run-1\/stdout.log \/w\/run-1\/stderr.log$/);
  const update = menuOutput(action("modules.update"), { module: "coffee", database: "cc_dev_x" },
    { ...COMPACT, stdout: COMPACT.stdout.replace("cc_test_coffee", "cc_dev_x") }, readLog);
  assert.match(update, /^module=coffee database=cc_dev_x exit=0\n/);
  assert.doesNotMatch(update, /result:/);
  const lines = Array.from({ length: 300 }, (_, index) => `line ${index + 1}`).join("\n");
  assert.equal(menuOutput(action("server.logs"), {}, { code: 0, stdout: `${lines}\n`, stderr: "" }, readLog), lines);
  assert.equal(menuOutput(action("server.status"), {}, { code: 1, stdout: "server: stopped\n", stderr: "warn\n" },
    readLog), "server: stopped\nwarn");
  assert.equal(menuOutput(action("server.stop"), {}, { code: 0, stdout: "", stderr: "" }, readLog), "(no output)");
});

test("entryLines shows the command and exit, and the last lines unless expanded", () => {
  const output = Array.from({ length: 30 }, (_, index) => `line ${index + 1}`).join("\n");
  const entry = { label: "Show the server status", command: "oasis status", exit: 0, output };
  const collapsed = entryLines(entry, false, 20);
  assert.deepEqual(collapsed.slice(0, 2), ["oasis: Show the server status (exit 0)", "$ oasis status"]);
  assert.equal(collapsed[2], "… 10 earlier lines");
  assert.deepEqual(collapsed.slice(3), output.split("\n").slice(10));
  assert.deepEqual(entryLines(entry, true, 20).slice(2), output.split("\n"));
  assert.deepEqual(entryLines({ label: "L", command: "c", note: "terminal only: run it in a terminal", output: "" },
    false, 20), ["oasis: L (terminal only: run it in a terminal)", "$ c"]);
  // Terminal control sequences in command output never reach the TUI.
  assert.deepEqual(entryLines({ label: "L", command: "c", exit: 1, output: "\x1b[31mred\x1b[0m\tx\r\nbell\x07" },
    false, 20).slice(2), ["red    x", "bell"]);
  // S4: the native odoo-bin line of a start / restart run follows the command, never cut.
  assert.deepEqual(entryLines({ label: "L", command: "c", exit: 0, native: "/env/python /odoo/odoo-bin", output: "x" },
    false, 20), ["oasis: L (exit 0)", "$ c", "native: /env/python /odoo/odoo-bin", "x"]);
});

test("pickerRows lists the groups with their actions; selection skips group rows", () => {
  const rows = pickerRows(catalog);
  // v0.12.0 (S3, S7): one start / restart action; the superseded ones stay in the catalog only.
  assert.deepEqual(rows.slice(0, 4).map((row) => row.text),
    ["Server", "Start / restart the server", "Stop the server", "Show the end of the server log"]);
  assert.equal(rows.some((row) => row.action?.superseded_by), false);
  assert.equal(rows.filter((row) => row.kind === "group").length, 4);
  assert.equal(rows.find((row) => row.action?.id === "modules.init_dev")?.tag, "terminal only");
  assert.equal(rows.find((row) => row.action?.id === "maintenance.drop_database")?.tag, "confirm");
  assert.equal(rows.find((row) => row.action?.id === "maintenance.worktree")?.tag, "confirm");
  assert.equal(rows.find((row) => row.action?.id === "server.stop")?.tag, "");
  assert.equal(rows.find((row) => row.action?.id === "server.run")?.tag, "");
  assert.equal(rows.find((row) => row.action?.id === "server.follow")?.tag, "");
  assert.equal(rows.find((row) => row.action?.id === "modules.overview")?.tag, "");
  assert.equal(moveSelection(rows, 0, 0), 1);
  const lastServer = rows.findIndex((row) => row.action?.id === "server.stop_database");
  assert.equal(rows[lastServer + 1].kind, "group");
  assert.equal(moveSelection(rows, lastServer, 1), lastServer + 2);
  assert.equal(moveSelection(rows, lastServer + 2, -1), lastServer);
  assert.equal(moveSelection(rows, 1, -1), 1);
  assert.equal(moveSelection(rows, rows.length - 1, 1), rows.length - 1);
  // Twelve rows below the first action is the Tests group row: the selection skips it.
  assert.equal(rows[13].kind, "group");
  assert.equal(moveSelection(rows, 1, 12), 14);
  assert.equal(moveSelection(rows, 1, 1000), rows.length - 1);
});

test("visibleStart keeps the selection in view and shows the row above it when scrolling up", () => {
  assert.equal(visibleStart(24, 1, 10, 0), 0);
  assert.equal(visibleStart(24, 15, 10, 0), 6);
  assert.equal(visibleStart(24, 15, 10, 8), 8);
  assert.equal(visibleStart(24, 3, 10, 8), 2);
  assert.equal(visibleStart(5, 4, 10, 3), 0);
});

test("menuShortcut: alt+o by default, configurable with OASIS_MENU_KEY, off when empty or off", () => {
  assert.equal(MENU_KEY_DEFAULT, "alt+o");
  assert.deepEqual(menuShortcut(undefined), { key: "alt+o" });
  assert.deepEqual(menuShortcut(""), { key: null });
  assert.deepEqual(menuShortcut("  "), { key: null });
  assert.deepEqual(menuShortcut("off"), { key: null });
  assert.deepEqual(menuShortcut("OFF"), { key: null });
  assert.deepEqual(menuShortcut(" ctrl+shift+m "), { key: "ctrl+shift+m" });
  assert.deepEqual(menuShortcut("f5"), { key: "f5" });
  // Pi lowercases key ids when it parses and matches them (pi-tui parseKeyId, ExtensionRunner.getShortcuts):
  // the registered key is that canonical form.
  assert.deepEqual(menuShortcut("ALT+O"), { key: "alt+o" });
  assert.deepEqual(menuShortcut("Alt+o"), { key: "alt+o" });
  assert.deepEqual(menuShortcut("alt+pageDown"), { key: "alt+pagedown" });
  assert.deepEqual(menuShortcut("Ctrl+Shift+PageUp"), { key: "ctrl+shift+pageup" });
  assert.deepEqual(menuShortcut("F5"), { key: "f5" });
  // A repeated modifier never matches in Pi (parseKeyId returns null).
  for (const bad of ["o", "shift+o", "alt+", "alt+oo", "hyper+o", "ctrl+f13", "alt+alt+o", "Alt+ALT+o"]) {
    assert.deepEqual(menuShortcut(bad), {
      key: null,
      error: `OASIS_MENU_KEY=${JSON.stringify(bad)} is not a usable key (for example alt+o, ctrl+shift+m or f5); ` +
        "the menu shortcut is off, /oasis menu still opens the panel.",
    }, bad);
  }
});

/** The fixture catalog with changes (a deep copy). */
function variant(change: (copy: Catalog) => void): Catalog {
  const copy = structuredClone(catalog);
  change(copy);
  return copy;
}

const RUN = "/opt/oasis/oasis --project '/work/a project'";
const NO_DATABASE = "No database chosen: odoo.conf sets no db_name, so Odoo starts without a database.";
const RELOAD = "reload needs inotify or watchdog importable by /env/bin/python; none is, so Odoo will log a warning and " +
  "disable reload.";

function withReloadWarning(copy: Catalog): void {
  for (const choice of copy.actions[0].inputs[1].choices ?? []) {
    if (choice.value === "all" || choice.value.split(",").includes("reload")) choice.warning = RELOAD;
  }
}

test("menuHeader: the checkout, its server and the default database of the start / restart flow", () => {
  assert.equal(menuHeader(catalog, "server: stopped"),
    "checkout: main\nserver: stopped\ndefault database: cc_dev_coffee");
  const worktree = variant((copy) => {
    copy.checkout!.name = "wt_1";
    copy.checkout!.default_database = null;
  });
  assert.equal(menuHeader(worktree, "server: running on port 8070 (pid 1)"),
    "checkout: wt_1\nserver: running on port 8070 (pid 1)\ndefault database: none");
});

test("pickerRows offers the last action of the checkout first, with its answers", () => {
  const remembered = variant((copy) => {
    copy.last = { action: "modules.update", answers: { module: "coffee", database: "cc_dev_coffee" },
      label: "Repeat: Update a module (coffee, cc_dev_coffee)" };
  });
  const rows = pickerRows(remembered);
  assert.deepEqual([rows[0].kind, rows[0].text, rows[0].tag, rows[0].action?.id, rows[0].answers],
    ["action", "Repeat: Update a module (coffee, cc_dev_coffee)", "", "modules.update",
      { module: "coffee", database: "cc_dev_coffee" }]);
  assert.equal(rows[1].text, "Server");
  assert.equal(moveSelection(rows, 0, 0), 0);
  assert.equal(pickerRows(catalog)[0].text, "Server");
  // A last action the catalog does not have is not offered.
  assert.equal(pickerRows(variant((copy) => {
    copy.last = { action: "server.gone", answers: {}, label: "Repeat: gone" };
  }))[0].text, "Server");
});

test("askInputs asks a closed choice by its labels and shows its warning", async () => {
  const run = action("server.run");
  const dev = { ...run, inputs: [run.inputs[1]] };
  let script = scripted(["all (access, qweb, reload, xml)"]);
  assert.deepEqual(await askInputs(dev, script.prompter, fixedChoices([], []).choices), { dev: "all" });
  assert.deepEqual(script.calls, ["select Dev mode [off, all (access, qweb, reload, xml), access, qweb, reload, " +
    "replica, xml, reload,xml]"]);
  assert.deepEqual(script.notices, []);
  const warned = variant(withReloadWarning).actions[0];
  script = scripted(["reload,xml"]);
  assert.deepEqual(await askInputs({ ...warned, inputs: [warned.inputs[1]] }, script.prompter,
    fixedChoices([], []).choices), { dev: "reload,xml" });
  assert.deepEqual(script.notices, [`warning: ${RELOAD}`]);
});

function texts(form: RunForm, width = 200, room?: number): string[] {
  return form.lines(width, room).map((line) => line.text);
}

test("RunForm asks database, dev mode and port in order; the last line is the command filled so far", () => {
  const form = new RunForm({
    catalog, action: action("server.run"), header: "checkout: main\nserver: stopped\ndefault database: cc_dev_coffee",
    databases: ["cc_dev_coffee", "cc_dev_tea"],
  });
  assert.deepEqual(texts(form), [
    "checkout: main", "server: stopped", "default database: cc_dev_coffee", "",
    "Database (Enter for cc_dev_coffee, - for none)",
    "› cc_dev_coffee (default)", "  cc_dev_tea", "  (none)", "  (type a name)",
    "", `$ ${RUN} start --detach`,
  ]);
  form.submit();
  assert.equal(texts(form).at(-1), `$ ${RUN} start --detach -d cc_dev_coffee`);
  assert.deepEqual(texts(form).slice(4, 7), ["Database: cc_dev_coffee", "Dev mode (Enter for off)", "› off"]);
  form.move(3);
  form.submit();
  assert.equal(texts(form).at(-1), `$ ${RUN} start --detach -d cc_dev_coffee --dev qweb`);
  // The port is typed over the one start will use; keeping it leaves the option out.
  assert.deepEqual(texts(form).slice(5, 8), ["Dev mode: qweb", "HTTP port (Enter for 8069)", "> 8069"]);
  form.submit();
  assert.deepEqual(texts(form).slice(4, 10), [
    "Database: cc_dev_coffee", "Dev mode: qweb", "HTTP port: 8069 (default)", "Run this command?", "› Run", "  Cancel",
  ]);
  assert.equal(form.finished, false);
  form.submit();
  assert.equal(form.finished, true);
  assert.deepEqual(form.result, { database: "cc_dev_coffee", dev: "qweb", port: "" });
});

test("RunForm: no database warns at the confirmation, a reload warning, a port re-asked until valid", () => {
  const warned = variant(withReloadWarning);
  const form = new RunForm({ catalog: warned, action: warned.actions[0], header: "h", databases: ["cc_dev_coffee"] });
  form.move(1);
  form.submit();
  assert.deepEqual(texts(form).slice(2, 3), ["Database: (none)"]);
  form.move(1);
  form.submit();
  assert.deepEqual(texts(form).slice(4, 5), [`  warning: ${RELOAD}`]);
  for (let index = 0; index < 4; index += 1) form.backspace();
  form.type("0");
  form.submit();
  assert.deepEqual(texts(form).slice(5, 8), ["HTTP port (Enter for 8069)", "> 0", "! Port must be a number from 1 to 65535."]);
  form.backspace();
  form.type("8070");
  form.submit();
  assert.deepEqual(texts(form), [
    "h", "", "Database: (none)", "Dev mode: all (access, qweb, reload, xml)", `  warning: ${RELOAD}`,
    "HTTP port: 8070", NO_DATABASE, "Run this command?", "› Run", "  Cancel",
    "", `$ ${RUN} start --detach --dev all --http-port 8070`,
  ]);
  form.move(1);
  form.submit();
  assert.deepEqual([form.finished, form.result], [true, undefined]);
});

test("RunForm types a database name checked by the catalog pattern; escape cancels", () => {
  const form = new RunForm({ catalog, action: action("server.run"), header: "h", databases: [] });
  assert.deepEqual(texts(form).slice(2, 6), [
    "Database (Enter for cc_dev_coffee, - for none)", "› cc_dev_coffee (default)", "  (none)", "  (type a name)",
  ]);
  form.move(2);
  form.submit();
  form.type("bad-name");
  form.submit();
  assert.deepEqual(texts(form).slice(2, 5), ["Database (Enter for cc_dev_coffee, - for none)", "> bad-name",
    "! Database name must use only letters, numbers, and underscores."]);
  for (let index = 0; index < 8; index += 1) form.backspace();
  form.type("cc_new\u0007");
  form.submit();
  assert.equal(texts(form)[2], "Database: cc_new");
  form.cancel();
  assert.deepEqual([form.finished, form.result], [true, undefined]);
});

test("RunForm repeats remembered answers from the confirmation", () => {
  const form = new RunForm({
    catalog, action: action("server.run"), header: "h", databases: [],
    answers: { database: "cc_dev_coffee", dev: "reload,xml", port: "8070" },
  });
  assert.deepEqual(texts(form), [
    "h", "", "Database: cc_dev_coffee", "Dev mode: reload,xml", "HTTP port: 8070", "Run this command?", "› Run",
    "  Cancel", "", `$ ${RUN} start --detach -d cc_dev_coffee --dev reload,xml --http-port 8070`,
  ]);
  form.submit();
  assert.deepEqual(form.result, { database: "cc_dev_coffee", dev: "reload,xml", port: "8070" });
});

test("RunForm wraps a long command instead of truncating it", () => {
  const deep = variant((copy) => {
    const run = copy.actions[0];
    run.argv = run.argv.map((token) => token === "/work/a project" ? `/work/${"nested/".repeat(12)}project` : token);
  });
  const form = new RunForm({ catalog: deep, action: deep.actions[0], header: "h", databases: [],
    answers: { database: "cc_dev_coffee", dev: "all", port: "8070" } });
  const lines = form.lines(40);
  const command = lines.slice(lines.findIndex((line) => line.text.startsWith("$ ")));
  assert.ok(command.length > 3, String(command.length));
  assert.ok(command.every((line) => line.text.length <= 40 && line.style === "command"));
  assert.ok(command.every((line) => !line.text.includes("…")));
  assert.equal(command.map((line) => line.text).join("").replaceAll(" ", ""),
    `$ ${shellJoin(fillTemplate(deep.actions[0], form.answers, true))}`.replaceAll(" ", ""));
});

test("wrapLine breaks at spaces, indents continuations and splits a word longer than the width", () => {
  assert.deepEqual(wrapLine("$ a bb ccc dddd", 8), ["$ a bb", "  ccc", "  dddd"]);
  assert.deepEqual(wrapLine("$ abcdefghijkl", 6), ["$", "  abcd", "  efgh", "  ijkl"]);
  assert.deepEqual(wrapLine("short", 40), ["short"]);
});

const MANY = Array.from({ length: 30 }, (_, index) => `cc_dev_${String(index).padStart(2, "0")}`);

test("RunForm shows a window of a long list around the selected row; header and command stay (S1)", () => {
  const header = "checkout: main\nserver: stopped\ndefault database: cc_dev_coffee";
  const form = new RunForm({ catalog, action: action("server.run"), header, databases: MANY });
  // 33 options (default, 30 databases, none, type a name) in 20 rows: 5 above the list, 2 below.
  const view = (selected: string, above: string[], below: string[]) => {
    const lines = texts(form, 200, 20);
    assert.ok(lines.length <= 20, String(lines.length));
    assert.deepEqual(lines.slice(0, 5), [...header.split("\n"), "", "Database (Enter for cc_dev_coffee, - for none)"]);
    assert.deepEqual(lines.slice(-2), ["", `$ ${RUN} start --detach`]);
    const list = lines.slice(5, -2);
    assert.ok(list.includes(`› ${selected}`), list.join(" | "));
    assert.deepEqual(list.filter((line) => line.includes(" more")), [...above, ...below]);
    if (above.length) assert.equal(list[0], above[0]);
    if (below.length) assert.equal(list.at(-1), below[0]);
    assert.equal(list.length - above.length - below.length, 11);
    return list;
  };
  const top = view("cc_dev_coffee (default)", [], ["  ↓ 22 more"]);
  assert.equal(top[0], "› cc_dev_coffee (default)");
  form.move(16);
  const middle = view("cc_dev_15", ["  ↑ 6 more"], ["  ↓ 16 more"]);
  assert.equal(middle.at(-2), "› cc_dev_15");
  form.move(100);
  const end = view("(type a name)", ["  ↑ 22 more"], []);
  assert.equal(end.at(-1), "› (type a name)");
  // The window stays while the selection is in it, and follows it when it leaves.
  form.move(-1);
  view("(none)", ["  ↑ 22 more"], []);
  form.move(-25);
  view("cc_dev_05", ["  ↑ 5 more"], ["  ↓ 17 more"]);
  // Without a height (or a short list) the whole list is shown, as before.
  assert.equal(texts(form).filter((line) => /^[ ›] /.test(line)).length, 33);
  // The next question starts at the top of its own list.
  form.submit();
  assert.deepEqual(texts(form, 200, 12).slice(5, 9), ["Dev mode (Enter for off)", "› off", "  all (access, qweb, reload, xml)",
    "  ↓ 6 more"]);
});

test("RunForm filters a list by typed text, case-insensitively; (none) and (type a name) stay (S2)", () => {
  const form = new RunForm({ catalog, action: action("server.run"), header: "h",
    databases: ["cc_dev_tea", "cc_test_COFFEE_old", "shop"] });
  assert.equal(form.hint(), "↑↓ move · type to filter · enter choose · esc cancel");
  form.type("Cof");
  assert.deepEqual(texts(form), ["h", "", "Database (Enter for cc_dev_coffee, - for none)", "filter: Cof",
    "› cc_dev_coffee (default)", "  cc_test_COFFEE_old", "  (none)", "  (type a name)", "", `$ ${RUN} start --detach`]);
  assert.equal(form.hint(), "↑↓ move · backspace edits the filter · enter choose · esc clears the filter");
  form.type("fee_");
  assert.deepEqual(texts(form).slice(3, 7), ["filter: Coffee_", "› cc_test_COFFEE_old", "  (none)", "  (type a name)"]);
  for (let index = 0; index < 5; index += 1) form.backspace();
  assert.deepEqual(texts(form).slice(3, 6), ["filter: Co", "› cc_dev_coffee (default)", "  cc_test_COFFEE_old"]);
  form.type("zz");
  assert.deepEqual(texts(form).slice(3, -2), ["filter: Cozz", "  no match: backspace edits the filter",
    "› (none)", "  (type a name)"]);
  // Typing a name starts from the filter text.
  form.move(1);
  form.submit();
  assert.deepEqual(texts(form).slice(2, 4), ["Database (Enter for cc_dev_coffee, - for none)", "> Cozz"]);
  form.submit();
  assert.equal(texts(form)[2], "Database: Cozz");
  // A closed choice filters by its labels; nothing matching leaves Enter without effect.
  form.type("REL");
  assert.deepEqual(texts(form).slice(4, 8), ["filter: REL", "› all (access, qweb, reload, xml)", "  reload",
    "  reload,xml"]);
  form.move(2);
  form.submit();
  assert.equal(texts(form)[3], "Dev mode: reload,xml");
  // A text input types as before; at the confirmation, typing filters nothing.
  form.submit();
  form.type("x");
  assert.deepEqual(texts(form).slice(-6), ["HTTP port: 8069 (default)", "Run this command?", "› Run", "  Cancel", "",
    `$ ${RUN} start --detach -d Cozz --dev reload,xml`]);
});

test("RunForm: esc clears a filter first, then cancels; a filter with no match ignores Enter (S2)", () => {
  const form = new RunForm({ catalog, action: action("server.run"), header: "h", databases: ["cc_dev_tea"] });
  form.type("tea");
  form.escape();
  assert.equal(form.finished, false);
  assert.deepEqual(texts(form).slice(2, 7), ["Database (Enter for cc_dev_coffee, - for none)", "› cc_dev_coffee (default)",
    "  cc_dev_tea", "  (none)", "  (type a name)"]);
  form.submit();
  form.type("nothing");
  assert.deepEqual(texts(form).slice(3, -2), ["Dev mode (Enter for off)", "filter: nothing",
    "  no match: backspace edits the filter"]);
  form.submit();
  assert.equal(form.input?.id, "dev");
  form.escape();
  form.escape();
  assert.deepEqual([form.finished, form.result], [true, undefined]);
});

test("RunForm shows the native odoo-bin line abbreviated; the oasis line with a note while loading or failed (S4)",
  async () => {
    const pending = new Map<string, (result: CoreResult) => void>();
    const native = nativeCommands((argv) => new Promise((resolve) => pending.set(argv.slice(3).join(" "), resolve)));
    const form = new RunForm({ catalog, action: action("server.run"), header: "h", databases: [], native,
      home: "/home/dev" });
    assert.deepEqual(texts(form).slice(-3), ["", `$ ${RUN} start --detach`, "  (loading the odoo-bin command…)"]);
    const line = "/home/dev/env/bin/python /home/dev/odoo/odoo-bin -c /home/dev/p/odoo.conf " +
      "--addons-path=/home/dev/odoo/addons,/home/dev/odoo/odoo/addons,/home/dev/p/addons --http-port 8069";
    pending.get("start --print-command")?.({ code: 0, stdout: `${line}\n`, stderr: "" });
    assert.equal(await native.settled([...PREFIX, "start", "--print-command"]), line);
    const shown = "$ ~/env/bin/python ~/odoo/odoo-bin -c ~/p/odoo.conf " +
      "--addons-path=~/odoo/addons,~/odoo…o/addons,~/p/addons --http-port 8069";
    assert.deepEqual(texts(form).slice(-2), ["", shown]);
    // Wrapped, never truncated.
    const narrow = form.lines(30).filter((item) => item.style === "command");
    assert.ok(narrow.length > 2 && narrow.every((item) => item.text.length <= 30));
    assert.equal(narrow.map((item) => item.text).join("").replaceAll(" ", ""), shown.replaceAll(" ", ""));
    // New answers: the next drawing (after every key) reads their native line, the oasis line meanwhile.
    form.submit();
    assert.deepEqual(texts(form).slice(-2), [`$ ${RUN} start --detach -d cc_dev_coffee`, "  (loading the odoo-bin command…)"]);
    assert.deepEqual([...pending.keys()], ["start --print-command", "start --print-command -d cc_dev_coffee"]);
    pending.get("start --print-command -d cc_dev_coffee")?.({ code: 2, stdout: "", stderr: "unknown option\n" });
    await native.settled([...PREFIX, "start", "--print-command", "-d", "cc_dev_coffee"]);
    assert.deepEqual(texts(form).slice(-2), [`$ ${RUN} start --detach -d cc_dev_coffee`,
      "  (the odoo-bin command is unavailable: exit 2; this is the oasis command)"]);
    assert.equal(pending.size, 2);
  });
