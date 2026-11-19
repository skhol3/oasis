import { test } from "node:test";
import assert from "node:assert/strict";
import { formatPlain, formatTestRun, testModuleArgs } from "../lib/tools.ts";

const STAMP = "2026-11-16 18:00:00,123 4242";

test("testModuleArgs always asks the core for compact output", () => {
  assert.deepEqual(testModuleArgs({ module: "coffee" }), ["test-module", "--compact", "coffee"]);
  assert.deepEqual(testModuleArgs({ module: "coffee", database: "cc_test_x" }), [
    "test-module", "--compact", "coffee", "cc_test_x",
  ]);
});

test("formatTestRun summarizes the logs the core reported", () => {
  const logs: Record<string, string> = {
    "/p/dev/logs/odoo19/run-1/stdout.log": `${STAMP} INFO db odoo.tests.result: 0 failed, 0 error(s) of 3 tests`,
    "/p/dev/logs/odoo19/run-1/stderr.log": "",
  };
  const core = {
    code: 0,
    stdout:
      "phase=tests database=cc_test_coffee exit=0\n" +
      "stdout_log=/p/dev/logs/odoo19/run-1/stdout.log\nstderr_log=/p/dev/logs/odoo19/run-1/stderr.log\n",
    stderr: "",
  };
  assert.equal(
    formatTestRun("coffee", core, (path) => logs[path] ?? "", { maxFailures: 10, traceLines: 6 }),
    [
      "module=coffee database=cc_test_coffee exit=0",
      "result: 0 failed, 0 error(s) of 3 tests",
      "problems: 0",
      "logs: /p/dev/logs/odoo19/run-1/stdout.log /p/dev/logs/odoo19/run-1/stderr.log",
    ].join("\n"),
  );
});

test("formatTestRun carries the disposable database lifecycle line", () => {
  const logs: Record<string, string> = {
    "/p/run-2/stdout.log": `${STAMP} INFO db odoo.tests.result: 1 failed, 0 error(s) of 3 tests`,
    "/p/run-2/stderr.log": "",
  };
  const core = {
    code: 1,
    stdout:
      "phase=tests database=cc_test_coffee_r1a2b3c exit=1\n" +
      "database_lifecycle=disposable dropped=yes\n" +
      "stdout_log=/p/run-2/stdout.log\nstderr_log=/p/run-2/stderr.log\n",
    stderr: "",
  };
  const report = formatTestRun("coffee", core, (path) => logs[path] ?? "", { maxFailures: 10, traceLines: 6 });
  assert.equal(
    report.split("\n")[0],
    "module=coffee database=cc_test_coffee_r1a2b3c exit=1 database_lifecycle=disposable dropped=yes",
  );
  assert.equal(report.split("\n").at(-1), "logs: /p/run-2/stdout.log /p/run-2/stderr.log");
});

test("formatTestRun relays a core refusal unchanged when no logs were produced", () => {
  const core = { code: 2, stdout: "", stderr: "Test databases must use the cc_test_ prefix.\n" };
  assert.equal(
    formatTestRun("coffee", core, () => "", { maxFailures: 10, traceLines: 6 }),
    "exit=2\nTest databases must use the cc_test_ prefix.",
  );
});

test("formatPlain joins stdout and stderr and bounds the length", () => {
  const stdout = Array.from({ length: 100 }, (_, i) => `PASS check_${i}`).join("\n");
  const text = formatPlain({ code: 1, stdout, stderr: "FAIL missing_file:dev/requirements/lock.sha256\n" }, 6);
  assert.equal(
    text,
    "exit=1\nPASS check_0\nPASS check_1\nPASS check_2\n... 95 lines omitted ...\nPASS check_98\nPASS check_99\nFAIL missing_file:dev/requirements/lock.sha256",
  );
});

test("keyValues keeps log paths that contain spaces", async () => {
  const { keyValues } = await import("../lib/tools.ts");
  assert.deepEqual(keyValues("phase=tests database=cc_test_a exit=1\nstdout_log=/my project/run 1/stdout.log\n"), {
    phase: "tests", database: "cc_test_a", exit: "1", stdout_log: "/my project/run 1/stdout.log",
  });
});
