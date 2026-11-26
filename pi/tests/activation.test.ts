import { test } from "node:test";
import assert from "node:assert/strict";
import * as activation from "../lib/activation.ts";
import { nextActiveTools, OASIS_TOOLS } from "../lib/activation.ts";

const OURS = ["ours_a", "ours_b"];

test("OASIS_TOOLS lists the layer tools once each", () => {
  assert.deepEqual([...OASIS_TOOLS].sort(), [
    "oasis_check_environment",
    "oasis_find_module",
    "oasis_lint_module",
    "oasis_model_info",
    "oasis_module_info",
    "oasis_module_status",
    "oasis_test_module",
    "oasis_test_summary",
    "oasis_update_module",
    "oasis_view_info",
    "oasis_xmlid_info",
  ]);
});

test("the oasis tools have no aliases (v0.17.0 S3)", () => {
  assert.deepEqual(Object.keys(activation).sort(), ["OASIS_TOOLS", "nextActiveTools"]);
});

test("the layer never activates or removes a tool outside its table, an old name included", () => {
  assert.deepEqual(nextActiveTools(["read"], true, OASIS_TOOLS), ["read", ...OASIS_TOOLS]);
  assert.deepEqual(
    nextActiveTools(["other_test_module", "oasis_test_module", "read"], false, OASIS_TOOLS),
    ["other_test_module", "read"],
  );
});

test("an Odoo project adds ours once after the other tools, keeping their order", () => {
  assert.deepEqual(nextActiveTools(["read", "bash", "edit"], true, OURS), ["read", "bash", "edit", "ours_a", "ours_b"]);
});

test("an Odoo project does not duplicate tools that are already active", () => {
  assert.deepEqual(
    nextActiveTools(["read", "ours_b", "bash"], true, OURS),
    ["read", "ours_b", "bash", "ours_a"],
  );
});

test("a non-Odoo project removes only ours and keeps the other tools in order", () => {
  assert.deepEqual(nextActiveTools(["ours_a", "read", "ours_b", "bash"], false, OURS), ["read", "bash"]);
});

test("already-correct input returns an equal array", () => {
  assert.deepEqual(nextActiveTools(["read", "ours_a", "ours_b"], true, OURS), ["read", "ours_a", "ours_b"]);
  assert.deepEqual(nextActiveTools(["read", "bash"], false, OURS), ["read", "bash"]);
  assert.deepEqual(nextActiveTools([], false, OURS), []);
});

test("the input array is not mutated", () => {
  const active = ["read", "ours_a"];
  nextActiveTools(active, true, OURS);
  nextActiveTools(active, false, OURS);
  assert.deepEqual(active, ["read", "ours_a"]);
});
