// Which run logs oasis_test_summary may read (lib/tools.ts runLogLocations, isRunLog,
// formatBackgroundRun): the shape of the named path, then its real path inside the checkout's
// real log locations. The symlink tests use a private temporary directory, removed afterwards.
import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { formatBackgroundRun, isRunLog, runLogLocations } from "../lib/tools.ts";

// tools/config.py values of a main checkout and of a linked worktree. LOGS_DIR is [tooling].logs, else (v0.17.0)
// the logs directory next to the workspace file: tools/config.py always sets it.
const WITH_LOGS = { PROJECT_ROOT: "/p/shop", LOGS_DIR: "/p/logs", CHECKOUT_KIND: "main", CHECKOUT_MAIN_ROOT: "/p/shop" };
const LINKED = { PROJECT_ROOT: "/p/shop-wt", LOGS_DIR: "/p/logs", CHECKOUT_KIND: "linked", CHECKOUT_MAIN_ROOT: "/p/shop" };
// Without LOGS_DIR (no tools/config.py of 0.17.0 gives that) no path is a run log.
const WITHOUT_LOGS = { ...LINKED, LOGS_DIR: "" };
// Lexical cases: every path resolves to itself.
const SAME = (path: string) => path;
const OPTIONS = { maxFailures: 10, traceLines: 6 };
const STAMP = "2026-11-23 18:00:00,123 4242";
const RESULT = `${STAMP} INFO db odoo.tests.result: 0 failed, 0 error(s) of 2 tests\n`;

function compactOutput(stdoutLog: string, stderrLog: string): string {
  return "phase=tests database=acme_test_coffee_r1a2b3c exit=0\ndatabase_lifecycle=disposable dropped=yes\n" +
    `stdout_log=${stdoutLog}\nstderr_log=${stderrLog}\n`;
}

const REFUSED = /test-module --compact/;

test("runLogLocations follows the compact log rules of tools/compact.sh", () => {
  // The logs directory only, whatever the checkout; no dev/logs/odoo19 since 0.17.0.
  assert.deepEqual(runLogLocations(WITH_LOGS), { logs: "/p/logs" });
  assert.deepEqual(runLogLocations({ ...LINKED, LOGS_DIR: "/p/logs/" }), { logs: "/p/logs" });
  assert.deepEqual(runLogLocations(WITHOUT_LOGS), {});
});

test("isRunLog accepts the run logs of each layout inside the project's log locations", () => {
  const withLogs = runLogLocations(WITH_LOGS);
  for (const path of [
    // <logs>/<main|slug>/run-<id>/ (0.8.0).
    "/p/logs/main/run-1/stdout.log",
    "/p/logs/shop_feature/run-x9/stderr.log",
    // <logs>/odoo19/<main|slug>/run-<id>/ of runs before 0.8.0.
    "/p/logs/odoo19/main/run-1/stdout.log",
    "/p/logs/odoo19/shop_feature/run-x9/stderr.log",
  ]) assert.equal(isRunLog(path, withLogs, SAME), true, path);
});

test("isRunLog rejects paths outside the project's log locations, even with a run log's shape", () => {
  const withLogs = runLogLocations(WITH_LOGS);
  for (const path of [
    "/tmp/x/main/run-1/stdout.log",
    "/tmp/odoo19/main/run-1/stdout.log",
    "/p/logs-other/main/run-1/stdout.log",
    "/p/logsmain/run-1/stdout.log",
    // dev/logs/odoo19 is not read.
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
  ]) assert.equal(isRunLog(path, withLogs, SAME), false, path);
  // The dev/logs/odoo19 of the checkout or of the main checkout (the default before 0.17.0) is no log location,
  // and without LOGS_DIR nothing is.
  for (const config of [LINKED, WITHOUT_LOGS]) {
    for (const path of [
      "/p/shop-wt/dev/logs/odoo19/run-ab_1/stdout.log",
      "/p/shop/dev/logs/odoo19/run-ab_1/stderr.log",
      ...(config === WITHOUT_LOGS ? ["/p/logs/main/run-1/stdout.log"] : []),
    ]) assert.equal(isRunLog(path, runLogLocations(config), SAME), false, path);
  }
});

test("isRunLog refuses a path that cannot be resolved", () => {
  const missing = (path: string): string => {
    throw Object.assign(new Error(`ENOENT: ${path}`), { code: "ENOENT" });
  };
  assert.equal(isRunLog("/p/logs/main/run-1/stdout.log", runLogLocations(WITH_LOGS), missing), false);
  assert.equal(isRunLog("/p/logs/main/run-1/stdout.log", runLogLocations(WITH_LOGS), realpathSync), false);
});

test("formatBackgroundRun summarizes a run of each layout", () => {
  for (const [config, stdoutLog, stderrLog] of [
    [WITH_LOGS, "/p/logs/shop_feature/run-1/stdout.log", "/p/logs/shop_feature/run-1/stderr.log"],
    [WITH_LOGS, "/p/logs/odoo19/main/run-1/stdout.log", "/p/logs/odoo19/main/run-1/stderr.log"],
    [LINKED, "/p/logs/shop_wt/run-1/stdout.log", "/p/logs/shop_wt/run-1/stderr.log"],
  ] as const) {
    const logs: Record<string, string> = { [stdoutLog]: RESULT, [stderrLog]: "" };
    assert.equal(
      formatBackgroundRun("coffee", compactOutput(stdoutLog, stderrLog), config,
        { realpath: SAME, readLog: (path) => logs[path] ?? "" }, OPTIONS),
      [
        "module=coffee database=acme_test_coffee_r1a2b3c exit=0 database_lifecycle=disposable dropped=yes",
        "result: 0 failed, 0 error(s) of 2 tests",
        "problems: 0",
        "log: 1 lines, 0 errors, 0 warnings",
        `logs: ${stdoutLog} ${stderrLog}`,
      ].join("\n"),
      stdoutLog,
    );
  }
});

test("formatBackgroundRun refuses, without reading anything, logs outside the project's log locations", () => {
  const files = { realpath: SAME, readLog: (): string => { throw new Error("must not read"); } };
  for (const output of ["", "exit=0\n", "phase=tests exit=0\nstdout_log=/p/config/odoo.conf\n",
    compactOutput("/p/logs/main/run-1/stdout.log", "/etc/passwd"),
    compactOutput("/tmp/x/main/run-1/stdout.log", "/tmp/x/main/run-1/stderr.log"),
    compactOutput("/p/logs/main/run-1/stdout.log", "/tmp/x/main/run-1/stderr.log")]) {
    assert.throws(() => formatBackgroundRun("coffee", output, WITH_LOGS, files, OPTIONS), REFUSED, output);
  }
});

/** A private directory tree for the symlink cases: `<scratch>/{projects, outside}`. */
function scratch(t: { after: (fn: () => void) => void }): string {
  const directory = realpathSync(mkdtempSync(join(tmpdir(), "oasis-run-logs-")));
  t.after(() => rmSync(directory, { recursive: true, force: true }));
  return directory;
}

function writeLog(path: string, text: string): void {
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, text);
}

const DISK = { realpath: realpathSync, readLog: (path: string) => readFileSync(path, "utf8") };

test("formatBackgroundRun reads real run directories of a configured logs directory", (t) => {
  const root = scratch(t);
  const logs = join(root, "projects/logs");
  writeLog(join(logs, "main/run-1/stdout.log"), RESULT);
  writeLog(join(logs, "main/run-1/stderr.log"), "");
  const config = { ...WITH_LOGS, PROJECT_ROOT: join(root, "projects/shop"), LOGS_DIR: logs };
  const report = formatBackgroundRun("coffee",
    compactOutput(join(logs, "main/run-1/stdout.log"), join(logs, "main/run-1/stderr.log")), config, DISK, OPTIONS);
  assert.match(report, /^result: 0 failed, 0 error\(s\) of 2 tests$/m);
});

test("formatBackgroundRun refuses a symlinked run directory or log file that points outside", (t) => {
  const root = scratch(t);
  const logs = join(root, "projects/logs");
  writeLog(join(root, "outside/run-9/stdout.log"), RESULT);
  writeLog(join(root, "outside/run-9/stderr.log"), "");
  writeLog(join(root, "outside/secret.log"), "secret\n");
  mkdirSync(join(logs, "main"), { recursive: true });
  // <logs>/main/run-1 -> <scratch>/outside/run-9
  symlinkSync(join(root, "outside/run-9"), join(logs, "main/run-1"));
  // <logs>/main/run-2/stdout.log -> <scratch>/outside/secret.log
  writeLog(join(logs, "main/run-2/stderr.log"), "");
  symlinkSync(join(root, "outside/secret.log"), join(logs, "main/run-2/stdout.log"));
  const config = { ...WITH_LOGS, PROJECT_ROOT: join(root, "projects/shop"), LOGS_DIR: logs };
  const files = { realpath: realpathSync, readLog: (): string => { throw new Error("must not read"); } };
  for (const run of ["run-1", "run-2"]) {
    const output = compactOutput(join(logs, "main", run, "stdout.log"), join(logs, "main", run, "stderr.log"));
    assert.throws(() => formatBackgroundRun("coffee", output, config, files, OPTIONS), REFUSED, run);
  }
  // A missing log is refused the same way.
  const missing = compactOutput(join(logs, "main/run-3/stdout.log"), join(logs, "main/run-3/stderr.log"));
  assert.throws(() => formatBackgroundRun("coffee", missing, config, files, OPTIONS), REFUSED);
});

test("formatBackgroundRun refuses the dev/logs/odoo19 runs of a checkout, linked or not (before 0.17.0)", (t) => {
  const root = scratch(t);
  const main = join(root, "projects/shop");
  const linked = join(root, "projects/shop-wt");
  writeLog(join(main, "dev/logs/odoo19/run-1/stdout.log"), RESULT);
  writeLog(join(main, "dev/logs/odoo19/run-1/stderr.log"), "");
  mkdirSync(join(linked, "dev"), { recursive: true });
  symlinkSync(join(main, "dev/logs"), join(linked, "dev/logs"));
  const files = { realpath: realpathSync, readLog: (): string => { throw new Error("must not read"); } };
  const logs = join(root, "projects/logs");
  for (const [checkout, config] of [
    [linked, { ...LINKED, PROJECT_ROOT: linked, CHECKOUT_MAIN_ROOT: main, LOGS_DIR: logs }],
    [main, { ...WITH_LOGS, PROJECT_ROOT: main, CHECKOUT_MAIN_ROOT: main, LOGS_DIR: logs }],
    [main, { ...WITH_LOGS, PROJECT_ROOT: main, CHECKOUT_MAIN_ROOT: main, LOGS_DIR: "" }],
  ] as const) {
    const output = compactOutput(join(checkout, "dev/logs/odoo19/run-1/stdout.log"),
      join(checkout, "dev/logs/odoo19/run-1/stderr.log"));
    assert.throws(() => formatBackgroundRun("coffee", output, config, files, OPTIONS), REFUSED, checkout);
  }
});
