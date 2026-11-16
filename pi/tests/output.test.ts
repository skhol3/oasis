import { test } from "node:test";
import assert from "node:assert/strict";
import { limitLines, summarizeTestLog } from "../lib/output.ts";

const STAMP = "2026-11-16 18:00:00,123 4242";

test("summarizeTestLog keeps the result line and each failure with the tail of its traceback", () => {
  const log = [
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

  const summary = summarizeTestLog(log, "", { maxFailures: 5, traceLines: 4 });

  assert.equal(
    summary,
    [
      "result: 1 failed, 1 error(s) of 14 tests when loading database 'cc_test_coffee'",
      "problems: 2 (showing 2)",
      "- FAIL: TestRoast.test_temperature [odoo.addons.coffee.tests.test_roast]",
      "      frame 29",
      '      File "/work/coffee/addons/coffee/tests/test_roast.py", line 12, in test_temperature',
      "        self.assertEqual(roast.temperature, 210)",
      "    AssertionError: 200 != 210",
      "- ERROR: TestBag.test_weight [odoo.addons.coffee.tests.test_bag]",
      "    Traceback (most recent call last):",
      "    KeyError: 'weight'",
    ].join("\n"),
  );
});

test("summarizeTestLog caps the number of problems and reports when none are found", () => {
  const many = Array.from(
    { length: 4 },
    (_, i) => `${STAMP} ERROR db odoo.addons.m.tests.t: FAIL: T.test_${i}`,
  ).join("\n");
  assert.equal(
    summarizeTestLog(many, "", { maxFailures: 2, traceLines: 0 }),
    ["result: not reported", "problems: 4 (showing 2)", "- FAIL: T.test_0 [odoo.addons.m.tests.t]", "- FAIL: T.test_1 [odoo.addons.m.tests.t]"].join("\n"),
  );
  assert.equal(
    summarizeTestLog(`${STAMP} INFO db odoo.tests.result: 0 failed, 0 error(s) of 3 tests`, "", { maxFailures: 2, traceLines: 2 }),
    "result: 0 failed, 0 error(s) of 3 tests\nproblems: 0",
  );
});

test("summarizeTestLog reads CRITICAL lines from stderr too", () => {
  const stderr = `${STAMP} CRITICAL db odoo.modules.module: Couldn't load module coffee`;
  assert.equal(
    summarizeTestLog("", stderr, { maxFailures: 3, traceLines: 1 }),
    "result: not reported\nproblems: 1 (showing 1)\n- Couldn't load module coffee [odoo.modules.module]",
  );
});

test("limitLines keeps head and tail and says how much it dropped", () => {
  const text = Array.from({ length: 10 }, (_, i) => `line ${i}`).join("\n");
  assert.equal(limitLines(text, 20), text);
  assert.equal(limitLines(text, 4), "line 0\nline 1\n... 6 lines omitted ...\nline 8\nline 9");
});
