import { test } from "node:test";
import assert from "node:assert/strict";
import { nextActiveTools, ODOO19_TOOLS } from "../lib/activation.ts";

const OURS = ["odoo19_a", "odoo19_b"];

test("ODOO19_TOOLS lists the six layer tools once each", () => {
  assert.deepEqual([...ODOO19_TOOLS].sort(), [
    "odoo19_check_environment",
    "odoo19_find_module",
    "odoo19_lint_module",
    "odoo19_model_info",
    "odoo19_module_status",
    "odoo19_test_module",
  ]);
});

test("an Odoo project adds ours once after the other tools, keeping their order", () => {
  assert.deepEqual(nextActiveTools(["read", "bash", "edit"], true, OURS), ["read", "bash", "edit", "odoo19_a", "odoo19_b"]);
});

test("an Odoo project does not duplicate tools that are already active", () => {
  assert.deepEqual(
    nextActiveTools(["read", "odoo19_b", "bash"], true, OURS),
    ["read", "odoo19_b", "bash", "odoo19_a"],
  );
});

test("a non-Odoo project removes only ours and keeps the other tools in order", () => {
  assert.deepEqual(nextActiveTools(["odoo19_a", "read", "odoo19_b", "bash"], false, OURS), ["read", "bash"]);
});

test("already-correct input returns an equal array", () => {
  assert.deepEqual(nextActiveTools(["read", "odoo19_a", "odoo19_b"], true, OURS), ["read", "odoo19_a", "odoo19_b"]);
  assert.deepEqual(nextActiveTools(["read", "bash"], false, OURS), ["read", "bash"]);
  assert.deepEqual(nextActiveTools([], false, OURS), []);
});

test("the input array is not mutated", () => {
  const active = ["read", "odoo19_a"];
  nextActiveTools(active, true, OURS);
  nextActiveTools(active, false, OURS);
  assert.deepEqual(active, ["read", "odoo19_a"]);
});
