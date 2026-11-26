import { test } from "node:test";
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { limitLines, summarizeTestLog } from "../lib/output.ts";

const STAMP = "2026-11-16 18:00:00,123 4242";
const NO_ERRORS = { maxFailures: 3, traceLines: 2 };

const FAILURES_LOG = [
  `${STAMP} INFO cc_test_coffee odoo.modules.loading: loading 42 modules...`,
  ...Array.from({ length: 200 }, (_, i) => `${STAMP} INFO cc_test_coffee odoo.modules.registry: noise ${i}`),
  `${STAMP} ERROR cc_test_coffee odoo.addons.coffee.tests.test_roast: FAIL: TestRoast.test_temperature`,
  "Traceback (most recent call last):",
  ...Array.from({ length: 30 }, (_, i) => `  frame ${i}`),
  '  File "/work/coffee/addons/coffee/tests/test_roast.py", line 12, in test_temperature',
  "    self.assertEqual(roast.temperature, 210)",
  "AssertionError: 200 != 210",
  `${STAMP} ERROR cc_test_coffee odoo.addons.coffee.tests.test_bag: ERROR: TestBag.test_weight`,
  "Traceback (most recent call last):",
  "KeyError: 'weight'",
  `${STAMP} INFO cc_test_coffee odoo.tests.stats: coffee: 14 tests 0.52s 300 queries`,
  `${STAMP} ERROR cc_test_coffee odoo.tests.result: 1 failed, 1 error(s) of 14 tests when loading database 'cc_test_coffee'`,
].join("\n");

const CAPPED_LOG = Array.from(
  { length: 4 },
  (_, i) => `${STAMP} ERROR db odoo.addons.m.tests.t: FAIL: T.test_${i}`,
).join("\n");

const CRITICAL_STDERR = `${STAMP} CRITICAL db odoo.modules.module: Couldn't load module coffee`;

const TRANSLATE_LOG = [
  ...Array.from(
    { length: 13 },
    (_, i) =>
      `${STAMP} WARNING cc_test_corpus_cafe odoo.tools.translate: no translation language detected, skipping translation ` +
      `<frame at 0x7fb0245c${(0xa810 + i * 16).toString(16)}, file '/home/dev/addons/oa_x/models/y${i}.py', line ${10 + i}, code compute_${i}>`,
  ),
  `${STAMP} INFO cc_test_corpus_cafe odoo.tests.result: 0 failed, 0 error(s) of 193 tests`,
].join("\n");

const MIXED_WARNINGS_LOG = [
  `${STAMP} WARNING db odoo.models: coffee.bag: field weight has no string`,
  `${STAMP} WARNING db odoo.fields: Field coffee.roast.level (selection) has an invalid default`,
  `${STAMP} WARNING db odoo.fields: Field coffee.roast.level (selection) has an invalid default`,
  `${STAMP} WARNING db odoo.tests.common: test helper warning that must not be counted`,
  `${STAMP} WARNING db odoo.models: object at 0xdeadbeef reused`,
  `${STAMP} WARNING db odoo.models: object at 0xfeed reused`,
  `${STAMP} WARNING db odoo.http: ${"x".repeat(100)}`,
].join("\n");

const PROBLEMS_AND_WARNINGS_LOG = [
  `${STAMP} WARNING db odoo.models: slow compute`,
  `${STAMP} ERROR db odoo.addons.m.tests.t: FAIL: T.test_a`,
  "AssertionError: 1 != 2",
].join("\n");

const STATS_LOG = [
  ...Array.from({ length: 7 }, (_, i) => `${STAMP} INFO db odoo.tests.stats: oa_m${i}: ${i + 1} tests 0.5${i}s 70${i} queries   `),
  `${STAMP} INFO db odoo.tests.result: 0 failed, 0 error(s) of 28 tests`,
].join("\n");

test("summarizeTestLog keeps the result line and each failure with the tail of its traceback", () => {
  const log = FAILURES_LOG;

  const summary = summarizeTestLog(log, "", { maxFailures: 5, traceLines: 4 });

  assert.equal(
    summary,
    [
      "result: 1 failed, 1 error(s) of 14 tests when loading database 'cc_test_coffee'",
      "stats: coffee: 14 tests 0.52s 300 queries",
      "problems: 2 (showing 2)",
      "- FAIL: TestRoast.test_temperature [odoo.addons.coffee.tests.test_roast]",
      "      frame 29",
      '      File "/work/coffee/addons/coffee/tests/test_roast.py", line 12, in test_temperature',
      "        self.assertEqual(roast.temperature, 210)",
      "    AssertionError: 200 != 210",
      "- ERROR: TestBag.test_weight [odoo.addons.coffee.tests.test_bag]",
      "    Traceback (most recent call last):",
      "    KeyError: 'weight'",
      "log: 240 lines, 2 errors, 0 warnings",
    ].join("\n"),
  );
});

test("summarizeTestLog caps the number of problems and reports when none are found", () => {
  const many = CAPPED_LOG;
  assert.equal(
    summarizeTestLog(many, "", { maxFailures: 2, traceLines: 0 }),
    ["result: not reported", "problems: 4 (showing 2)", "- FAIL: T.test_0 [odoo.addons.m.tests.t]", "- FAIL: T.test_1 [odoo.addons.m.tests.t]", "log: 3 lines, 4 errors, 0 warnings"].join("\n"),
  );
  assert.equal(
    summarizeTestLog(`${STAMP} INFO db odoo.tests.result: 0 failed, 0 error(s) of 3 tests`, "", { maxFailures: 2, traceLines: 2 }),
    "result: 0 failed, 0 error(s) of 3 tests\nproblems: 0\nlog: 0 lines, 0 errors, 0 warnings",
  );
});

test("summarizeTestLog reads CRITICAL lines from stderr too", () => {
  const stderr = CRITICAL_STDERR;
  assert.equal(
    summarizeTestLog("", stderr, { maxFailures: 3, traceLines: 1 }),
    "result: not reported\nproblems: 1 (showing 1)\n- Couldn't load module coffee [odoo.modules.module]\nlog: 0 lines, 1 errors, 0 warnings",
  );
});

test("summarizeTestLog groups the field case of translate warnings that differ only by frame", () => {
  const log = TRANSLATE_LOG;
  assert.equal(
    summarizeTestLog(log, "", NO_ERRORS),
    [
      "result: 0 failed, 0 error(s) of 193 tests",
      "problems: 0",
      "warnings: 13 (odoo.tools.translate ×13: no translation language detected, skipping translation…)",
      "log: 13 lines, 0 errors, 13 warnings",
    ].join("\n"),
  );
});

test("summarizeTestLog orders warning groups by count then first seen and skips odoo.tests loggers", () => {
  const log = MIXED_WARNINGS_LOG;
  assert.equal(
    summarizeTestLog(log, "", NO_ERRORS),
    [
      "result: not reported",
      "problems: 0",
      "warnings: 6 (odoo.fields ×2: Field coffee.roast.level…; odoo.models ×2: object at reused; " +
        "odoo.models ×1: coffee.bag: field weight has no string; +1 more groups)",
      "log: 6 lines, 0 errors, 6 warnings",
    ].join("\n"),
  );
  assert.equal(
    summarizeTestLog(`${STAMP} WARNING db odoo.http: ${"x".repeat(100)}`, "", NO_ERRORS),
    `result: not reported\nproblems: 0\nwarnings: 1 (odoo.http ×1: ${"x".repeat(80)}…)\nlog: 0 lines, 0 errors, 1 warnings`,
  );
});

test("summarizeTestLog places warnings after the problems block", () => {
  const log = PROBLEMS_AND_WARNINGS_LOG;
  assert.equal(
    summarizeTestLog(log, "", NO_ERRORS),
    [
      "result: not reported",
      "problems: 1 (showing 1)",
      "- FAIL: T.test_a [odoo.addons.m.tests.t]",
      "    AssertionError: 1 != 2",
      "warnings: 1 (odoo.models ×1: slow compute)",
      "log: 2 lines, 1 errors, 1 warnings",
    ].join("\n"),
  );
});

test("summarizeTestLog adds trimmed stats lines after the result, at most five", () => {
  const log = STATS_LOG;
  assert.equal(
    summarizeTestLog(log, "", NO_ERRORS),
    [
      "result: 0 failed, 0 error(s) of 28 tests",
      ...Array.from({ length: 5 }, (_, i) => `stats: oa_m${i}: ${i + 1} tests 0.5${i}s 70${i} queries`),
      "problems: 0",
      "log: 7 lines, 0 errors, 0 warnings",
    ].join("\n"),
  );
  assert.equal(
    summarizeTestLog(
      `${STAMP} INFO cc_test_corpus_cafe odoo.tests.stats: oa_mrp_mass_production_order: 193 tests 90.62s 70974 queries `,
      "",
      NO_ERRORS,
    ),
    "result: not reported\nstats: oa_mrp_mass_production_order: 193 tests 90.62s 70974 queries\nproblems: 0\nlog: 0 lines, 0 errors, 0 warnings",
  );
});

/** Totals the summary already reports, read back from its text, next to the control line counts. */
function reportedTotals(summary: string) {
  const lines = summary.split("\n");
  const control = /^log: (\d+) lines, (\d+) errors, (\d+) warnings$/.exec(lines.at(-1) ?? "");
  assert.ok(control, `no control line last in:\n${summary}`);
  const problems = /^problems: (\d+)/m.exec(summary);
  const warnings = /^warnings: (\d+)/m.exec(summary);
  return {
    problems: Number(problems?.[1]),
    warnings: warnings ? Number(warnings[1]) : 0,
    controlErrors: Number(control[2]),
    controlWarnings: Number(control[3]),
  };
}

test("summarizeTestLog control line counts agree with the problems and warnings totals", () => {
  const fixtures: Array<[string, string]> = [
    [FAILURES_LOG, ""],
    [CAPPED_LOG, ""],
    ["", CRITICAL_STDERR],
    [TRANSLATE_LOG, ""],
    [MIXED_WARNINGS_LOG, ""],
    [PROBLEMS_AND_WARNINGS_LOG, ""],
    [STATS_LOG, ""],
    [MIXED_WARNINGS_LOG, FAILURES_LOG],
  ];
  for (const [stdout, stderr] of fixtures) {
    const totals = reportedTotals(summarizeTestLog(stdout, stderr, { maxFailures: 50, traceLines: 0 }));
    assert.equal(totals.controlErrors, totals.problems);
    assert.equal(totals.controlWarnings, totals.warnings);
  }
});

test("summarizeTestLog control line reports every error when the problems shown are capped", () => {
  const stdout = [
    ...Array.from({ length: 12 }, (_, i) => `${STAMP} ERROR db odoo.addons.m.tests.t: FAIL: T.test_${i}`),
    `${STAMP} WARNING db odoo.models: slow compute`,
    `${STAMP} ERROR db odoo.tests.result: 12 failed, 0 error(s) of 12 tests`,
  ].join("\n") + "\n";
  const stderr = `${STAMP} CRITICAL db odoo.modules.module: Couldn't load module coffee\n`;
  assert.equal(
    summarizeTestLog(stdout, stderr, { maxFailures: 0, traceLines: 6 }),
    [
      "result: 12 failed, 0 error(s) of 12 tests",
      "problems: 13 (showing 0)",
      "warnings: 1 (odoo.models ×1: slow compute)",
      "log: 15 lines, 13 errors, 1 warnings",
    ].join("\n"),
  );
  assert.equal(
    summarizeTestLog(CAPPED_LOG, "", { maxFailures: 1, traceLines: 0 }).split("\n").slice(1).join("\n"),
    "problems: 4 (showing 1)\n- FAIL: T.test_0 [odoo.addons.m.tests.t]\nlog: 3 lines, 4 errors, 0 warnings",
  );
});

test("summarizeTestLog control line counts lines like cat stdout stderr | wc -l", () => {
  const line = (level: string, logger: string) => `${STAMP} ${level} db ${logger}: message`;
  const cases: Array<[string, string]> = [
    ["", ""],
    ["\n", ""],
    [`${line("INFO", "odoo.modules")}\n${line("WARNING", "odoo.models")}\n`, `${line("ERROR", "odoo.sql_db")}\n`],
    // Without a final newline cat joins the last stdout line with the first stderr line.
    [`${line("INFO", "odoo.modules")}\ntrace`, `${line("INFO", "odoo.modules")}`],
    ["a\r\nb\r\n\n\n", "\n\nc"],
  ];
  const dir = mkdtempSync(join(tmpdir(), "oasis-output-"));
  try {
    for (const [index, [stdout, stderr]] of cases.entries()) {
      const out = join(dir, `${index}.out`);
      const err = join(dir, `${index}.err`);
      writeFileSync(out, stdout);
      writeFileSync(err, stderr);
      const expected = Number(execFileSync("sh", ["-c", 'cat "$1" "$2" | wc -l', "sh", out, err], { encoding: "utf8" }).trim());
      const control = summarizeTestLog(stdout, stderr, NO_ERRORS).split("\n").at(-1);
      assert.match(control ?? "", new RegExp(`^log: ${expected} lines, `), `case ${index}`);
    }
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
  assert.equal(
    summarizeTestLog("a\nb\n", "c\n", NO_ERRORS).split("\n").at(-1),
    "log: 3 lines, 0 errors, 0 warnings",
  );
  assert.equal(summarizeTestLog("a\nb", "c\n", NO_ERRORS).split("\n").at(-1), "log: 2 lines, 0 errors, 0 warnings");
});

test("summarizeTestLog control line excludes odoo.tests.result errors and odoo.tests.* warnings", () => {
  const stdout = [
    `${STAMP} ERROR db odoo.tests.result: 1 failed, 0 error(s) of 2 tests`,
    `${STAMP} WARNING db odoo.tests.common: helper warning`,
    `${STAMP} WARNING db odoo.tests.stats: odd stats warning`,
    `${STAMP} CRITICAL db odoo.service.server: Failed to initialize database`,
    `${STAMP} WARNING db odoo.models: slow compute`,
    `${STAMP} INFO db odoo.modules: ERROR in an info message`,
  ].join("\n") + "\n";
  assert.equal(
    summarizeTestLog(stdout, "", NO_ERRORS),
    [
      "result: 1 failed, 0 error(s) of 2 tests",
      "stats: odd stats warning",
      "problems: 1 (showing 1)",
      "- Failed to initialize database [odoo.service.server]",
      "warnings: 1 (odoo.models ×1: slow compute)",
      "log: 6 lines, 1 errors, 1 warnings",
    ].join("\n"),
  );
});

test("summarizeTestLog reads the Odoo 15 result logger odoo.tests.runner like odoo.tests.result", () => {
  // Odoo 15 logs the result through odoo.tests.runner (odoo/service/server.py), 16+ through odoo.tests.result.
  const failed = `${STAMP} ERROR db odoo.tests.runner: 1 failed, 0 error(s) of 2 tests when loading database 'db'\n`;
  assert.equal(
    summarizeTestLog(failed, "", NO_ERRORS),
    "result: 1 failed, 0 error(s) of 2 tests when loading database 'db'\nproblems: 0\nlog: 1 lines, 0 errors, 0 warnings",
  );
  const none = `${STAMP} WARNING db odoo.tests.runner: 0 failed, 0 error(s) of 0 tests when loading database 'db'\n`;
  assert.equal(
    summarizeTestLog(none, "", NO_ERRORS),
    "result: 0 failed, 0 error(s) of 0 tests when loading database 'db'\nproblems: 0\nlog: 1 lines, 0 errors, 0 warnings",
  );
});

test("limitLines keeps head and tail and says how much it dropped", () => {
  const text = Array.from({ length: 10 }, (_, i) => `line ${i}`).join("\n");
  assert.equal(limitLines(text, 20), text);
  assert.equal(limitLines(text, 4), "line 0\nline 1\n... 6 lines omitted ...\nline 8\nline 9");
});
