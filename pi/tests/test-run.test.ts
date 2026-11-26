// formatTestRun when the module has no tests (v0.16.0 S4.8): the report says no tests ran, so an
// install-only pass is not read as passing tests.
import { test } from "node:test";
import assert from "node:assert/strict";
import { formatTestRun } from "../lib/tools.ts";

const STAMP = "2026-11-16 18:00:00,123 4242";
const OPTIONS = { maxFailures: 10, traceLines: 6 };
const LOGS = "stdout_log=/l/out\nstderr_log=/l/err\n";

/** One result line as Odoo logs it: odoo.tests.result (16+) or odoo.tests.runner (15). */
function resultLine(count: number, logger = "odoo.tests.result"): string {
  const level = count ? "INFO" : "WARNING";
  return `${STAMP} ${level} db ${logger}: 0 failed, 0 error(s) of ${count} tests when loading database 'db'\n`;
}

function report(log: string, lifecycle = "", only?: string): string {
  const stdout = `phase=tests database=db exit=0\n${lifecycle}${LOGS}`;
  return formatTestRun("coffee", { code: 0, stdout, stderr: "" }, (path) => (path === "/l/out" ? log : ""),
    OPTIONS, 60, only);
}

test("formatTestRun says no tests ran when the module has none, on Odoo 19 and Odoo 15", () => {
  for (const logger of ["odoo.tests.result", "odoo.tests.runner"]) {
    assert.equal(
      report(resultLine(0, logger)),
      [
        "module=coffee database=db exit=0",
        "result: 0 failed, 0 error(s) of 0 tests when loading database 'db'",
        "problems: 0",
        "log: 1 lines, 0 errors, 0 warnings",
        "no tests ran: the run only installed coffee",
        "logs: /l/out /l/err",
      ].join("\n"),
    );
  }
});

test("formatTestRun says the run only updated the module on a reused database in update mode", () => {
  assert.ok(report(resultLine(0), "database_lifecycle=reused mode=update\n").split("\n")
    .includes("no tests ran: the run only updated coffee"));
  assert.ok(report(resultLine(0), "database_lifecycle=reused mode=install\n").split("\n")
    .includes("no tests ran: the run only installed coffee"));
  assert.ok(report(resultLine(0), "database_lifecycle=disposable dropped=yes\n").split("\n")
    .includes("no tests ran: the run only installed coffee"));
});

test("formatTestRun keeps its other reports unchanged", () => {
  // Tests ran: no extra line.
  assert.equal(
    report(resultLine(3)),
    "module=coffee database=db exit=0\nresult: 0 failed, 0 error(s) of 3 tests when loading database 'db'\n" +
      "problems: 0\nlog: 1 lines, 0 errors, 0 warnings\nlogs: /l/out /l/err",
  );
  // No result line at all (the run stopped before reporting): still "not reported".
  assert.equal(
    report(""),
    "module=coffee database=db exit=0\nresult: not reported\nproblems: 0\nlog: 0 lines, 0 errors, 0 warnings\n" +
      "logs: /l/out /l/err",
  );
  // An `only` filter that matched nothing keeps its own note, alone.
  assert.equal(
    report(resultLine(0), "", "TestNope"),
    "module=coffee database=db exit=0\nresult: 0 failed, 0 error(s) of 0 tests when loading database 'db'\n" +
      "problems: 0\nlog: 1 lines, 0 errors, 0 warnings\n" +
      "no test matched only=TestNope: check the class and method names\nlogs: /l/out /l/err",
  );
});
