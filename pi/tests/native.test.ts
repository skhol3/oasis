import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { type Answers, type CatalogAction, fillTemplate, parseCatalog } from "../lib/menu.ts";
import {
  abbreviateCommand, nativeCommands, parseNativeLine, printCommandArgv, shellSplit,
} from "../lib/native.ts";
import type { CoreResult } from "../lib/tools.ts";

// S4: the start / restart form's native odoo-bin line, from `start --print-command [options]`.
const catalog = parseCatalog(readFileSync(new URL("./fixtures/catalog.json", import.meta.url), "utf8"));
const PREFIX = ["/opt/oasis/oasis", "--project", "/work/a project"];

function action(id: string): CatalogAction {
  const found = catalog.actions.find((item) => item.id === id);
  assert.ok(found, id);
  return found;
}

test("printCommandArgv inserts --print-command after start or restart and drops --detach", () => {
  const print = (item: CatalogAction, answers: Answers) => printCommandArgv(item.command, fillTemplate(item, answers, true));
  const run = action("server.run");
  assert.deepEqual(print(run, {}), [...PREFIX, "start", "--print-command"]);
  assert.deepEqual(print(run, { database: "cc_dev_coffee", dev: "all", port: "8070" }),
    [...PREFIX, "start", "--print-command", "-d", "cc_dev_coffee", "--dev", "all", "--http-port", "8070"]);
  const restart = { ...run, command: "restart", argv: run.argv.map((token) => (token === "start" ? "restart" : token)) };
  assert.deepEqual(print(restart, { database: "x" }), [...PREFIX, "restart", "--print-command", "-d", "x"]);
  assert.equal(print(action("server.status"), {}), null);
  assert.equal(printCommandArgv("start", ["/opt/oasis/oasis", "status"]), null);
});

test("shellSplit reads shlex.join quoting and refuses an unterminated quote", () => {
  assert.deepEqual(shellSplit("a 'b c' 'it'\"'\"'s' \"d \\\"e\\\"\" f\\ g"), ["a", "b c", "it's", "d \"e\"", "f g"]);
  assert.deepEqual(shellSplit("  ''  x  "), ["", "x"]);
  assert.equal(shellSplit("a 'b"), null);
  assert.equal(shellSplit("a \"b"), null);
});

test("parseNativeLine takes one line on stdout with exit 0, else says why not", () => {
  const ok = (stdout: string, code = 0, stderr = ""): CoreResult => ({ code, stdout, stderr });
  assert.deepEqual(parseNativeLine(ok("/env/bin/python /odoo/odoo-bin -c /p/odoo.conf\n")),
    { state: "ready", line: "/env/bin/python /odoo/odoo-bin -c /p/odoo.conf" });
  assert.deepEqual(parseNativeLine(ok("", 2, "start: unknown option --print-command\n")),
    { state: "failed", reason: "exit 2" });
  assert.deepEqual(parseNativeLine(ok("a\nb\n")), { state: "failed", reason: "unexpected output" });
  assert.deepEqual(parseNativeLine(ok("\n")), { state: "failed", reason: "unexpected output" });
  assert.deepEqual(parseNativeLine(ok("a 'b\n")), { state: "failed", reason: "unexpected output" });
});

test("abbreviateCommand: the home directory as ~ and values over 40 characters shortened with …", () => {
  const home = "/home/dev";
  const addons = "/home/dev/odoo/19.0/odoo/addons,/home/dev/odoo/19.0/addons,/home/dev/Work/shop/addons";
  const line = `/home/dev/Work/shop/.venv/bin/python /home/dev/odoo/19.0/odoo-bin -c /home/dev/Work/shop/dev/odoo.conf ` +
    `--addons-path=${addons} --data-dir '/home/dev/a dir' --http-port 8070 -d cc_dev_coffee /home/devx`;
  const shown = abbreviateCommand(line, home);
  assert.equal(shown,
    "~/Work/shop/.venv/bin/python ~/odoo/19.0/odoo-bin -c ~/Work/shop/dev/odoo.conf " +
    "--addons-path=~/odoo/19.0/odoo/add…,~/Work/shop/addons --data-dir '~/a dir' --http-port 8070 -d cc_dev_coffee " +
    "/home/devx");
  // The rule: a value (after `--option=`) over 40 characters keeps its first 20 and last 19.
  const value = shown.split(" ")[4].slice("--addons-path=".length);
  assert.equal(value.length, 40);
  assert.equal(value, `${addons.replaceAll(home, "~").slice(0, 20)}…${addons.replaceAll(home, "~").slice(-19)}`);
  // A long word without an option prefix is shortened the same way; no home leaves paths alone.
  assert.equal(abbreviateCommand(`/opt/${"x".repeat(50)}`, undefined), `/opt/${"x".repeat(15)}…${"x".repeat(19)}`);
  assert.equal(abbreviateCommand("/home/dev/p", "/"), "/home/dev/p");
});

test("nativeCommands fetches once per argv, reports loading, ready and failures, and notifies", async () => {
  const calls: string[] = [];
  const pending: ((result: CoreResult) => void)[] = [];
  const native = nativeCommands((argv) => {
    calls.push(argv.join(" "));
    if (argv.includes("boom")) return Promise.reject(new Error("spawn python3 ENOENT"));
    return new Promise((resolve) => pending.push(resolve));
  });
  let changes = 0;
  const unsubscribe = native.onChange(() => {
    changes += 1;
  });
  assert.deepEqual(native.get(["start"]), { state: "loading" });
  assert.deepEqual(native.get(["start"]), { state: "loading" });
  assert.deepEqual(calls, ["start"]);
  pending[0]({ code: 0, stdout: "/env/python /odoo/odoo-bin\n", stderr: "" });
  assert.equal(await native.settled(["start"]), "/env/python /odoo/odoo-bin");
  assert.deepEqual(native.get(["start"]), { state: "ready", line: "/env/python /odoo/odoo-bin" });
  assert.equal(changes, 1);
  assert.equal(await native.settled(["boom"]), null);
  assert.deepEqual(native.get(["boom"]), { state: "failed", reason: "could not run" });
  assert.equal(changes, 2);
  unsubscribe();
  native.get(["start", "-d", "x"]);
  pending[1]({ code: 3, stdout: "", stderr: "" });
  assert.equal(await native.settled(["start", "-d", "x"]), null);
  assert.equal(changes, 2);
  assert.deepEqual(calls, ["start", "boom", "start -d x"]);
});
