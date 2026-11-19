// Odoo 19 project detection. No Pi imports: tested directly with node:test.
import { existsSync, realpathSync } from "node:fs";
import { dirname, isAbsolute, join, relative, resolve, sep } from "node:path";

export const PROFILE_NAME = ".odoo19-agent.toml";
export const WORKSPACE_NAME = "oasis-workspace.toml";

/** Git top level of a directory, or null when git cannot tell (injected: this lib runs no commands). */
export type GitTopLevel = (start: string) => string | null;

function real(path: string): string {
  try {
    return realpathSync(path);
  } catch {
    return resolve(path);
  }
}

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
 * file, the real git top level of `start` (`start` itself without git or when the top level is
 * not inside the real workspace directory, where the workspace file would not be found again),
 * else null.
 */
export function findProjectRoot(start: string, gitTopLevel?: GitTopLevel): string | null {
  for (const directory of ancestors(start)) {
    if (existsSync(join(directory, PROFILE_NAME))) return directory;
  }
  // Real paths, as tools/config.py resolves the checkout and git reports its top level: a
  // symlinked session directory still finds its workspace and resolves to the checkout root.
  const fallback = real(start);
  const workspace = findWorkspaceFile(fallback);
  if (!workspace) return null;
  const top = gitTopLevel?.(fallback);
  if (!top) return fallback;
  const checkout = real(top);
  const inside = relative(real(dirname(workspace)), checkout);
  const outside = inside === ".." || inside.startsWith(`..${sep}`) || isAbsolute(inside);
  return outside ? fallback : checkout;
}

/**
 * findProjectRoot with an asynchronous git lookup. A found top level is kept per directory;
 * a failed lookup is not, so the next call asks git again.
 */
export function projectRootResolver(
  gitTopLevel: (start: string) => Promise<string | null>,
): (cwd: string) => Promise<string | null> {
  const topLevels = new Map<string, string>();
  return async (cwd) => {
    let missing: string | null = null;
    const root = findProjectRoot(cwd, (start) => {
      const known = topLevels.get(start);
      if (known === undefined) missing = start;
      return known ?? null;
    });
    if (missing === null) return root;
    const asked: string = missing;
    const top = await gitTopLevel(asked);
    if (top) topLevels.set(asked, top);
    return findProjectRoot(cwd, (start) => (start === asked ? top : topLevels.get(start) ?? null));
  };
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

