import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  type Answers, askInputs, type CatalogAction, confirmRun, entryLines, fillTemplate, MENU_KEY_DEFAULT, menuOutput,
  menuShortcut, moveSelection, parseCatalog, pickerRows, type Prompter, shellJoin, sources, terminalCommand,
  textError, visibleStart,
} from "../lib/menu.ts";

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
  assert.equal(catalog.actions.length, 20);
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
  assert.deepEqual(run.calls, [`input Drop a database\n${command}\nType the database name to confirm (cc_dev_x)`]);
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
  for (const id of ["server.status", "tests.module", "modules.install", "maintenance.migrate_plan"]) {
    run = scripted([]);
    assert.equal(await confirmRun(action(id), {}, "c", run.prompter), true, id);
    assert.deepEqual(run.calls, [], id);
  }
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
});

test("pickerRows lists the groups with their actions; selection skips group rows", () => {
  const rows = pickerRows(catalog);
  assert.deepEqual(rows.slice(0, 3).map((row) => row.text), ["Server", "Start the server in the background", "Stop the server"]);
  assert.equal(rows.filter((row) => row.kind === "group").length, 4);
  assert.equal(rows.find((row) => row.action?.id === "modules.init_dev")?.tag, "terminal only");
  assert.equal(rows.find((row) => row.action?.id === "maintenance.drop_database")?.tag, "confirm");
  assert.equal(rows.find((row) => row.action?.id === "maintenance.worktree")?.tag, "confirm");
  assert.equal(rows.find((row) => row.action?.id === "server.stop")?.tag, "");
  assert.equal(moveSelection(rows, 0, 0), 1);
  const lastServer = rows.findIndex((row) => row.action?.id === "server.stop_database");
  assert.equal(rows[lastServer + 1].kind, "group");
  assert.equal(moveSelection(rows, lastServer, 1), lastServer + 2);
  assert.equal(moveSelection(rows, lastServer + 2, -1), lastServer);
  assert.equal(moveSelection(rows, 1, -1), 1);
  assert.equal(moveSelection(rows, rows.length - 1, 1), rows.length - 1);
  assert.equal(moveSelection(rows, 1, 10), 12);
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
  assert.deepEqual(menuShortcut("alt+pageDown"), { key: "alt+pageDown" });
  for (const bad of ["o", "shift+o", "alt+", "alt+oo", "hyper+o", "ctrl+f13"]) {
    assert.deepEqual(menuShortcut(bad), {
      key: null,
      error: `OASIS_MENU_KEY=${JSON.stringify(bad)} is not a usable key (for example alt+o, ctrl+shift+m or f5); ` +
        "the menu shortcut is off, /oasis menu still opens the panel.",
    }, bad);
  }
});
