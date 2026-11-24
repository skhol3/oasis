// Odoo project detection. No Pi imports: tested directly with node:test.
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

const TOOL_LINES: Record<string, string> = {
  oasis_test_module: "run one module's tests; result line and failures only.",
  oasis_test_summary: "the same summary for a background compact run.",
  oasis_update_module: "update a module in a database; errors and warnings only.",
  oasis_module_status: "a module's state in a database.",
  oasis_check_environment: "environment diagnostics (quick by default).",
  oasis_lint_module: "Pylint one module without starting Odoo.",
  oasis_find_module: "module names from a functional name; no ls/grep.",
  oasis_model_info: "a model's definition, extensions, fields, methods; before reading Odoo files.",
  oasis_view_info: "a model's views and extensions; no XML search.",
  oasis_xmlid_info: "an XML id's definition, extensions, references.",
  oasis_module_info: "a module's models, views, menus, security, data, tests.",
};

/**
 * Compact system-prompt section for a detected project; `workspace` names its workspace file.
 * `tools` are the session's tools: only the oasis tools among them are named, and a session with
 * none (a subagent without the overlay) is pointed to the CLI. Omitted: every oasis tool.
 * `version` is the configured Odoo series ("19.0"); it names the project and its skills. The last
 * line names the commands the bash guard asks the user about (docs/bash-guard.md).
 */
export function projectContext(
  root: string,
  workspace?: string | null,
  tools?: readonly string[],
  version?: string,
): string {
  // The series comes from the project's configuration; without it no number is made up.
  const odoo = version ? `Odoo ${version}` : "Odoo";
  const skills = version ? `odoo${version.split(".")[0]}-*` : "Odoo";
  const source = workspace ? `workspace ${workspace}` : `profile ${PROFILE_NAME}`;
  const names = Object.keys(TOOL_LINES).filter((name) => !tools || tools.includes(name));
  const routing = names.length > 0
    ? [
        "Prefer the oasis tools to raw shell (profile guards, compact output):",
        ...names.map((name) => `- ${name}: ${TOOL_LINES[name]}`),
        "Open reported logs only if the summary falls short. Do not browse the Odoo source tree to learn",
      ]
    : [
        "This session has no oasis tools. Instead of raw odoo-bin, psql or dropdb, run the guarded CLI:",
        `\`oasis --project ${root} <command>\` (test-module --compact, module-status, check-environment --quick,`,
        "lint-module, model-info). Do not browse the Odoo source tree to learn",
      ];
  return [
    `${odoo} project root: ${root} (${source}).`,
    ...routing,
    `framework APIs; load the matching ${skills} skill first.`,
    "drop-database, stop --database, gc --apply --trash ask the user; never bypass a refusal.",
  ].join("\n");
}
