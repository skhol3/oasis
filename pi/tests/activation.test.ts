import { test } from "node:test";
import assert from "node:assert/strict";
import { aliasOf, nextActiveTools, OASIS_TOOLS, TOOL_ALIASES } from "../lib/activation.ts";

const OURS = ["odoo19_a", "odoo19_b"];

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

test("each oasis tool has one odoo19 alias, outside the activation table", () => {
  assert.equal(aliasOf("oasis_test_module"), "odoo19_test_module");
  assert.deepEqual(TOOL_ALIASES, OASIS_TOOLS.map((name) => name.replace(/^oasis_/, "odoo19_")));
  assert.ok(TOOL_ALIASES.every((alias) => !OASIS_TOOLS.includes(alias)));
});

test("the layer never activates or removes the odoo19 aliases", () => {
  assert.deepEqual(nextActiveTools(["read"], true, OASIS_TOOLS), ["read", ...OASIS_TOOLS]);
  assert.deepEqual(
    nextActiveTools(["odoo19_test_module", "oasis_test_module", "read"], false, OASIS_TOOLS),
    ["odoo19_test_module", "read"],
  );
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
