// Odoo 19 project detection. No Pi imports: tested directly with node:test.
import { existsSync } from "node:fs";
import { dirname, join, resolve } from "node:path";

export const PROFILE_NAME = ".odoo19-agent.toml";

/** Nearest directory at or above `start` that holds the project profile, else null. */
export function findProjectRoot(start: string): string | null {
  let current = resolve(start);
  for (;;) {
    if (existsSync(join(current, PROFILE_NAME))) return current;
    const parent = dirname(current);
    if (parent === current) return null;
    current = parent;
  }
}

/** Compact system-prompt section for a detected project. */
export function projectContext(root: string): string {
  return [
    `Odoo 19 project root: ${root} (profile ${PROFILE_NAME}).`,
    "Prefer the odoo19 tools over raw shell; they apply the profile guards and return compact output:",
    "- odoo19_test_module: run one module's tests; returns the result line and failures only, full logs stay on disk.",
    "- odoo19_module_status: database and module state for a module.",
    "- odoo19_check_environment: environment diagnostics (quick by default).",
    "- odoo19_lint_module: Pylint for one module without starting Odoo.",
    "- odoo19_find_module: technical module names from a functional name (manifest name/summary); no ls/grep.",
    "- odoo19_model_info: a model's definition, extensions, fields and methods from source; use it before reading Odoo files.",
    "Open the logs a tool reports only when its summary is not enough. Do not browse the Odoo source tree to learn",
    "framework APIs; load the matching odoo19-* skill first.",
  ].join("\n");
}
