import { test } from "node:test";
import assert from "node:assert/strict";
import {
  formatPlain, formatTestRun, formatUpdateRun, testModuleArgs, updateModuleArgs, viewInfoArgs,
} from "../lib/tools.ts";

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
      "log: 0 lines, 0 errors, 0 warnings",
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

// tools/config.py values of a checkout with [tooling].logs, and of a linked worktree without it.
const WITH_LOGS = { PROJECT_ROOT: "/p/shop", LOGS_DIR: "/p/logs", CHECKOUT_KIND: "main", CHECKOUT_MAIN_ROOT: "/p/shop" };
const LINKED = { PROJECT_ROOT: "/p/shop-wt", LOGS_DIR: "", CHECKOUT_KIND: "linked", CHECKOUT_MAIN_ROOT: "/p/shop" };

test("runLogLocations follows the compact log rules of tools/compact.sh", async () => {
  const { runLogLocations } = await import("../lib/tools.ts");
  // [tooling].logs: only that directory, whatever the checkout.
  assert.deepEqual(runLogLocations(WITH_LOGS), { logs: "/p/logs", devLogs: [] });
  assert.deepEqual(runLogLocations({ ...LINKED, LOGS_DIR: "/p/logs/" }), { logs: "/p/logs", devLogs: [] });
  // Without it: the checkout's dev/logs/odoo19, and the main checkout's for a linked worktree.
  assert.deepEqual(runLogLocations({ ...WITH_LOGS, LOGS_DIR: "" }), { devLogs: ["/p/shop/dev/logs/odoo19"] });
  assert.deepEqual(runLogLocations(LINKED), { devLogs: ["/p/shop-wt/dev/logs/odoo19", "/p/shop/dev/logs/odoo19"] });
  // A linked worktree whose main checkout is unknown (git failed, profile slug) has only its own.
  assert.deepEqual(runLogLocations({ ...LINKED, CHECKOUT_MAIN_ROOT: "" }), { devLogs: ["/p/shop-wt/dev/logs/odoo19"] });
  assert.deepEqual(runLogLocations({ ...LINKED, CHECKOUT_KIND: "none", CHECKOUT_MAIN_ROOT: "" }),
    { devLogs: ["/p/shop-wt/dev/logs/odoo19"] });
});

test("isRunLog accepts the run logs of each layout inside the project's log locations", async () => {
  const { isRunLog, runLogLocations } = await import("../lib/tools.ts");
  const withLogs = runLogLocations(WITH_LOGS);
  for (const path of [
    // <logs>/<main|slug>/run-<id>/ (0.8.0).
    "/p/logs/main/run-1/stdout.log",
    "/p/logs/shop_feature/run-x9/stderr.log",
    // <logs>/odoo19/<main|slug>/run-<id>/ of runs before 0.8.0.
    "/p/logs/odoo19/main/run-1/stdout.log",
    "/p/logs/odoo19/shop_feature/run-x9/stderr.log",
  ]) assert.equal(isRunLog(path, withLogs), true, path);
  const linked = runLogLocations(LINKED);
  for (const path of [
    "/p/shop-wt/dev/logs/odoo19/run-ab_1/stdout.log",
    // A linked worktree's dev/logs may stay linked to the main checkout's.
    "/p/shop/dev/logs/odoo19/run-ab_1/stderr.log",
  ]) assert.equal(isRunLog(path, linked), true, path);
});

test("isRunLog rejects paths outside the project's log locations, even with a run log's shape", async () => {
  const { isRunLog, runLogLocations } = await import("../lib/tools.ts");
  const withLogs = runLogLocations(WITH_LOGS);
  for (const path of [
    "/tmp/x/main/run-1/stdout.log",
    "/tmp/odoo19/main/run-1/stdout.log",
    "/p/logs-other/main/run-1/stdout.log",
    "/p/logsmain/run-1/stdout.log",
    // dev/logs/odoo19 is not read when [tooling].logs is set.
    "/p/shop/dev/logs/odoo19/run-1/stdout.log",
    "/p/logs/run-1/stdout.log",
    "/p/logs/a/b/run-1/stdout.log",
    "/p/logs/Shop-Feature/run-1/stdout.log",
    "/p/logs/main/run-1/other.log",
    "/p/logs/main/run-1/sub/stdout.log",
    "/p/logs/main/run-1/../../../shop/config/odoo.conf",
    "/p/logs/main/../main/run-1/stdout.log",
    "p/logs/main/run-1/stdout.log",
    "/etc/passwd",
  ]) assert.equal(isRunLog(path, withLogs), false, path);
  const linked = runLogLocations(LINKED);
  for (const path of [
    "/tmp/x/dev/logs/odoo19/run-1/stdout.log",
    "/p/other/dev/logs/odoo19/run-1/stdout.log",
    "/p/shop-wt/dev/logs/odoo19/main/run-1/stdout.log",
    "/p/shop-wt/dev/logs/odoo19/run-1/../../../../.env",
    "/p/logs/main/run-1/stdout.log",
  ]) assert.equal(isRunLog(path, linked), false, path);
  // The main checkout's dev/logs only counts for a linked worktree.
  assert.equal(isRunLog("/p/shop/dev/logs/odoo19/run-1/stdout.log",
    runLogLocations({ ...WITH_LOGS, PROJECT_ROOT: "/p/other", LOGS_DIR: "" })), false);
});

test("formatBackgroundRun summarizes a compact run that finished in the background", async () => {
  const { formatBackgroundRun, runLogLocations } = await import("../lib/tools.ts");
  const stamp = "2026-11-16 18:00:00,123 4242";
  const logs: Record<string, string> = {
    "/p/logs/odoo19/main/run-1/stdout.log": "",
    "/p/logs/odoo19/main/run-1/stderr.log": `${stamp} INFO db odoo.tests.result: 0 failed, 0 error(s) of 3 tests\n`,
  };
  const output =
    "phase=tests database=acme_test_coffee_r1a2b3c exit=0\ndatabase_lifecycle=disposable dropped=yes\n" +
    "stdout_log=/p/logs/odoo19/main/run-1/stdout.log\nstderr_log=/p/logs/odoo19/main/run-1/stderr.log\n";
  assert.equal(
    formatBackgroundRun("coffee", output, (path) => logs[path] ?? "", { maxFailures: 10, traceLines: 6 },
      runLogLocations(WITH_LOGS)),
    [
      "module=coffee database=acme_test_coffee_r1a2b3c exit=0 database_lifecycle=disposable dropped=yes",
      "result: 0 failed, 0 error(s) of 3 tests",
      "problems: 0",
      "log: 1 lines, 0 errors, 0 warnings",
      "logs: /p/logs/odoo19/main/run-1/stdout.log /p/logs/odoo19/main/run-1/stderr.log",
    ].join("\n"),
  );
});

test("formatBackgroundRun summarizes a run of the <logs>/<checkout> layout", async () => {
  const { formatBackgroundRun, runLogLocations } = await import("../lib/tools.ts");
  const stamp = "2026-11-23 18:00:00,123 4242";
  const logs: Record<string, string> = {
    "/p/logs/shop_feature/run-1/stdout.log": `${stamp} INFO db odoo.tests.result: 0 failed, 0 error(s) of 2 tests\n`,
    "/p/logs/shop_feature/run-1/stderr.log": "",
  };
  const output =
    "phase=tests database=acme_test_shop_feature_coffee_r1a2b3c exit=0\ndatabase_lifecycle=disposable dropped=yes\n" +
    "stdout_log=/p/logs/shop_feature/run-1/stdout.log\nstderr_log=/p/logs/shop_feature/run-1/stderr.log\n";
  assert.equal(
    formatBackgroundRun("coffee", output, (path) => logs[path] ?? "", { maxFailures: 10, traceLines: 6 },
      runLogLocations(WITH_LOGS)),
    [
      "module=coffee database=acme_test_shop_feature_coffee_r1a2b3c exit=0 database_lifecycle=disposable dropped=yes",
      "result: 0 failed, 0 error(s) of 2 tests",
      "problems: 0",
      "log: 1 lines, 0 errors, 0 warnings",
      "logs: /p/logs/shop_feature/run-1/stdout.log /p/logs/shop_feature/run-1/stderr.log",
    ].join("\n"),
  );
});

test("formatBackgroundRun reads only run logs named by a compact run in the project's log locations", async () => {
  const { formatBackgroundRun, runLogLocations } = await import("../lib/tools.ts");
  const read = () => { throw new Error("must not read"); };
  for (const output of ["", "exit=0\n", "phase=tests exit=0\nstdout_log=/p/config/odoo.conf\n",
    "phase=tests exit=0\nstdout_log=/p/logs/main/run-1/stdout.log\nstderr_log=/etc/passwd\n",
    "phase=tests exit=0\nstdout_log=/tmp/x/main/run-1/stdout.log\nstderr_log=/tmp/x/main/run-1/stderr.log\n",
    "phase=tests exit=0\nstdout_log=/p/logs/main/run-1/stdout.log\nstderr_log=/tmp/x/main/run-1/stderr.log\n"]) {
    assert.throws(
      () => formatBackgroundRun("coffee", output, read, { maxFailures: 1, traceLines: 1 }, runLogLocations(WITH_LOGS)),
      /test-module --compact/, output);
  }
});

test("testModuleArgs passes one class or method with --only", () => {
  assert.deepEqual(testModuleArgs({ module: "coffee" }), ["test-module", "--compact", "coffee"]);
  assert.deepEqual(testModuleArgs({ module: "coffee", only: "TestOrder.test_total" }), [
    "test-module", "--compact", "--only", "TestOrder.test_total", "coffee",
  ]);
  assert.deepEqual(testModuleArgs({ module: "coffee", database: "cc_test_x", only: "TestOrder" }), [
    "test-module", "--compact", "--only", "TestOrder", "coffee", "cc_test_x",
  ]);
});

test("formatUpdateRun reports errors and warnings of a compact update, without a test result line", () => {
  assert.deepEqual(updateModuleArgs({ module: "coffee", database: "cc_dev_coffee" }), [
    "update-module", "--compact", "coffee", "cc_dev_coffee",
  ]);
  const logs: Record<string, string> = {
    "/p/logs/odoo19/run-a/stdout.log": [
      "2026-11-20 10:00:00,000 1 INFO cc_dev_coffee odoo.modules.loading: Modules loaded.",
      "2026-11-20 10:00:01,000 1 WARNING cc_dev_coffee odoo.models: field x has no label",
      "2026-11-20 10:00:02,000 1 ERROR cc_dev_coffee odoo.modules.registry: Failed to load registry",
      "Traceback (most recent call last):",
      "ValueError: bad view",
      "",
    ].join("\n"),
    "/p/logs/odoo19/run-a/stderr.log": "",
  };
  const stdout = "phase=update database=cc_dev_coffee exit=1\nstdout_log=/p/logs/odoo19/run-a/stdout.log\nstderr_log=/p/logs/odoo19/run-a/stderr.log\n";
  const report = formatUpdateRun("coffee", { code: 1, stdout, stderr: "" }, (path) => logs[path], { maxFailures: 10, traceLines: 6 });
  assert.deepEqual(report.split("\n"), [
    "module=coffee database=cc_dev_coffee exit=1",
    "problems: 1 (showing 1)",
    "- Failed to load registry [odoo.modules.registry]",
    "    Traceback (most recent call last):",
    "    ValueError: bad view",
    "warnings: 1 (odoo.models ×1: field x has no label)",
    "log: 5 lines, 1 errors, 1 warnings",
    "logs: /p/logs/odoo19/run-a/stdout.log /p/logs/odoo19/run-a/stderr.log",
  ]);
});

test("formatUpdateRun passes a refusal through when no log was written", () => {
  const refused = { code: 2, stdout: "", stderr: "Database does not exist: cc_dev_coffee\n" };
  assert.equal(
    formatUpdateRun("coffee", refused, () => { throw new Error("no log to read"); }, { maxFailures: 10, traceLines: 6 }),
    "exit=2\nDatabase does not exist: cc_dev_coffee",
  );
});

test("formatTestRun says so when `only` matched no test", () => {
  const line = (count: number) =>
    `2026-11-20 10:00:00,000 1 INFO db odoo.tests.result: 0 failed, 0 error(s) of ${count} tests when loading database 'db'\n`;
  const stdout = "phase=tests database=db exit=0\nstdout_log=/l/out\nstderr_log=/l/err\n";
  const report = (count: number, only?: string) =>
    formatTestRun("coffee", { code: 0, stdout, stderr: "" }, (path) => (path === "/l/out" ? line(count) : ""),
      { maxFailures: 10, traceLines: 6 }, 60, only);
  const note = "no test matched only=TestNope: check the class and method names";
  assert.ok(report(0, "TestNope").split("\n").includes(note));
  assert.ok(!report(3, "TestNope").includes("no test matched"));
  assert.ok(!report(10, "TestNope").includes("no test matched"));
  assert.ok(!report(0).includes("no test matched"), "a module without tests is not a filter mistake");
});

test("testModuleArgs and formatTestRun handle a reused test database", () => {
  assert.deepEqual(testModuleArgs({ module: "coffee", reuse: true, only: "TestOrder" }), [
    "test-module", "--compact", "--reuse", "--only", "TestOrder", "coffee",
  ]);
  assert.deepEqual(testModuleArgs({ module: "coffee", reuse: false }), ["test-module", "--compact", "coffee"]);
  const stdout = "phase=tests database=cc_test_coffee exit=0\ndatabase_lifecycle=reused mode=update\nstdout_log=/l/out\nstderr_log=/l/err\n";
  const report = formatTestRun("coffee", { code: 0, stdout, stderr: "" }, () => "", { maxFailures: 10, traceLines: 6 });
  assert.equal(report.split("\n")[0], "module=coffee database=cc_test_coffee exit=0 database_lifecycle=reused mode=update");
});

test("viewInfoArgs forwards the optional type and module filters", () => {
  assert.deepEqual(viewInfoArgs({ model: "sale.order" }), ["view-info", "sale.order"]);
  assert.deepEqual(viewInfoArgs({ model: "sale.order", type: "form" }), ["view-info", "sale.order", "--type", "form"]);
  assert.deepEqual(viewInfoArgs({ model: "sale.order", module: "sale_stock", type: "list" }), [
    "view-info", "sale.order", "--type", "list", "--module", "sale_stock",
  ]);
});
