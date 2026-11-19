// Odoo 19 project detection. No Pi imports: tested directly with node:test.
import { existsSync } from "node:fs";
import { dirname, isAbsolute, join, relative, resolve } from "node:path";

export const PROFILE_NAME = ".odoo19-agent.toml";
export const WORKSPACE_NAME = "oasis-workspace.toml";

/** Git top level of a directory, or null when git cannot tell (injected: this lib runs no commands). */
export type GitTopLevel = (start: string) => string | null;

function ancestors(start: string): string[] {
  const directories: string[] = [];
  let current = resolve(start);
  for (;;) {
    directories.push(current);
    const parent = dirname(current);
    if (parent === current) return directories;
    current = parent;
  }
}

/**
 * Nearest `oasis-workspace.toml` at or above `start`, else null. Like tools/config.py, the
 * search ends at a directory that holds the profile: that checkout owns the tree.
 */
export function findWorkspaceFile(start: string): string | null {
  for (const directory of ancestors(start)) {
    if (existsSync(join(directory, PROFILE_NAME))) return null;
    const candidate = join(directory, WORKSPACE_NAME);
    if (existsSync(candidate)) return candidate;
  }
  return null;
}

/**
 * Checkout root for `start`: the nearest directory with the profile, else, under a workspace
 * file, the git top level of `start` (`start` itself without git or when the top level is not
 * inside the workspace directory, where the workspace file would not be found again), else null.
 */
export function findProjectRoot(start: string, gitTopLevel?: GitTopLevel): string | null {
  for (const directory of ancestors(start)) {
    if (existsSync(join(directory, PROFILE_NAME))) return directory;
  }
  const workspace = findWorkspaceFile(start);
  if (!workspace) return null;
  const fallback = resolve(start);
  const top = gitTopLevel?.(fallback);
  if (!top) return fallback;
  const inside = relative(dirname(workspace), resolve(top));
  return inside.startsWith("..") || isAbsolute(inside) ? fallback : resolve(top);
}

/** Compact system-prompt section for a detected project; `workspace` names its workspace file. */
export function projectContext(root: string, workspace?: string | null): string {
  const source = workspace ? `workspace ${workspace}` : `profile ${PROFILE_NAME}`;
  return [
    `Odoo 19 project root: ${root} (${source}).`,
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
