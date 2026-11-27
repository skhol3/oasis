// Odoo project detection. No Pi imports: tested directly with node:test.
import { existsSync, readFileSync, realpathSync, statSync } from "node:fs";
import { dirname, isAbsolute, join, relative, resolve, sep } from "node:path";

/** The legacy per-checkout profile: tools/config.py no longer reads it and refuses a checkout
 * that has one (`oasis migrate` converts it); found here only so that refusal shows. */
export const PROFILE_NAME = ".odoo19-agent.toml";
export const WORKSPACE_NAME = "oasis-workspace.toml";
/** A checkout's own file at its root (tools/config.py CHECKOUT_NAME): checkout_slug and environment. */
export const CHECKOUT_NAME = "oasis-checkout.toml";

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

/** Nearest `oasis-workspace.toml` at or above `start`, else null (tools/config.py find_workspace). */
function nearestWorkspace(start: string): string | null {
  for (const directory of ancestors(start)) {
    const candidate = join(directory, WORKSPACE_NAME);
    if (existsSync(candidate)) return candidate;
  }
  return null;
}

/** A file's text, or null when it cannot be read. */
function readText(path: string): string | null {
  try {
    return readFileSync(path, "utf8");
  } catch {
    return null;
  }
}

/**
 * The linked git worktree holding `start`: its top level (the directory of the nearest `.git`, when
 * that is a file) and its main checkout (the parent of the common git directory), read as git reads
 * them: the `.git` file's `gitdir:` and that directory's `commondir`, each relative to where it is
 * written. Null in a main checkout, a submodule (no `commondir`), outside git, or when a file
 * cannot be read. tools/config.py asks git itself (`--git-common-dir`); both name the same main.
 */
export function linkedWorktree(start: string): { top: string; main: string } | null {
  let entry: string | null = null;
  for (const directory of ancestors(real(start))) {
    if (existsSync(join(directory, ".git"))) {
      entry = join(directory, ".git");
      break;
    }
  }
  if (entry === null) return null;
  try {
    if (!statSync(entry).isFile()) return null;
  } catch {
    return null;
  }
  const pointer = /^gitdir: (.+)$/m.exec(readText(entry) ?? "");
  if (!pointer) return null;
  const gitDir = resolve(dirname(entry), pointer[1].trim());
  const common = readText(join(gitDir, "commondir"));
  if (common === null || !common.trim()) return null;
  return { top: dirname(entry), main: real(dirname(resolve(gitDir, common.trim()))) };
}

/**
 * The workspace file a checkout at or below `start` reads, as tools/config.py workspace_file finds
 * it: the nearest `oasis-workspace.toml` at or above `start`, else, in a linked worktree, the one its
 * main checkout reads; else null.
 */
export function findWorkspaceFile(start: string): string | null {
  const nearest = nearestWorkspace(start);
  if (nearest) return nearest;
  const linked = linkedWorktree(start);
  return linked ? nearestWorkspace(linked.main) : null;
}

/** The machine file's path in the user's configuration directory, as tools/config.py machine_file
 * finds it: `$XDG_CONFIG_HOME/oasis/config.toml` when that variable is an absolute path, else
 * `<home>/.config/oasis/config.toml`. */
export function machineFile(environment: Record<string, string | undefined>, home: string): string {
  const configured = environment.XDG_CONFIG_HOME ?? "";
  return join(isAbsolute(configured) ? configured : join(home, ".config"), "oasis", "config.toml");
}

/** The legacy profile in `root` itself (the one tools/config.py refuses), else null. */
export function legacyProfile(root: string): string | null {
  const profile = join(root, PROFILE_NAME);
  return existsSync(profile) ? profile : null;
}

/** Why `cwd` is not an Odoo project (findProjectRoot returned null). */
export function notProject(cwd: string): string {
  return `no ${WORKSPACE_NAME} at or above ${cwd}`;
}

/** The nearest directory holding `name` at or above `start`, up to `last` included. */
function nearestHolding(name: string, start: string, last?: string): string | null {
  for (const directory of ancestors(start)) {
    if (existsSync(join(directory, name))) return directory;
    if (directory === last) break;
  }
  return null;
}

/**
 * Checkout root for `start`: the directory passed to tools/config.py as the project. Under a
 * workspace file: the real git top level of `start`; without git (or when the top level is not
 * inside the real workspace directory, where the workspace file would not be found again), the
 * directory git would report, the nearest one holding `.git` from `start` up to the workspace
 * directory, else `start` itself. A legacy profile never picks the root there: config.py checks
 * only `<root>/.odoo19-agent.toml`, so one in a directory between the workspace and the checkout
 * is crossed, with git or without. A linked worktree with no workspace file at or above it, whose
 * main checkout reads one (findWorkspaceFile), is its own top level. Without a workspace file: the
 * nearest directory holding a legacy profile, so config.py's refusal (run oasis migrate) shows
 * there; else null.
 */
export function findProjectRoot(start: string, gitTopLevel?: GitTopLevel): string | null {
  // Real paths, as tools/config.py resolves the checkout and git reports its top level: a
  // symlinked session directory still finds its workspace and resolves to the checkout root.
  const fallback = real(start);
  const workspace = nearestWorkspace(fallback);
  if (!workspace) {
    const linked = linkedWorktree(fallback);
    if (linked && nearestWorkspace(linked.main)) return linked.top;
    return nearestHolding(PROFILE_NAME, fallback);
  }
  const base = real(dirname(workspace));
  const top = gitTopLevel?.(fallback);
  const withoutGit = () => nearestHolding(".git", fallback, base) ?? fallback;
  if (!top) return withoutGit();
  const checkout = real(top);
  const inside = relative(base, checkout);
  const outside = inside === ".." || inside.startsWith(`..${sep}`) || isAbsolute(inside);
  return outside ? withoutGit() : checkout;
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
  oasis_test_module: "run a module's tests; only result and failures, full logs stay on disk.",
  oasis_test_summary: "the same for a background run; pass what test-module --compact printed.",
  oasis_update_module: "update a module in a database; errors/warnings only.",
  oasis_module_status: "a module's state in a database.",
  oasis_check_environment: "environment checks, quick by default.",
  oasis_lint_module: "Pylint a module without starting Odoo.",
  oasis_find_module: "module names from a functional name; no ls/grep.",
  oasis_model_info: "a model's definition, extensions, fields, methods; before reading Odoo files.",
  oasis_view_info: "a model's views and extensions; no XML search.",
  oasis_xmlid_info: "an XML id's definition, extensions, references.",
  oasis_module_info: "a module's models, views, menus, security, data, tests.",
};

/**
 * Compact system-prompt section for a detected project; `workspace` names its workspace file, null
 * (or omitted) for a root that holds a legacy profile, which no command reads any more.
 * `tools` are the session's tools: only the oasis tools among them are named, and a session with
 * none (a subagent without the overlay) is pointed to the CLI. Omitted: every oasis tool.
 * `version` is the configured Odoo series ("19.0"); it names the project and the series the odoo-<topic>
 * skills are read for: their recipes (odoo-<topic>/references/*.md) cover every series and say what
 * differs in a Changed in table (v0.18.0 S6). The last
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
  const skills = version ? `odoo-* skill for series ${version}` : "odoo-* skill";
  const source = workspace
    ? `workspace ${workspace}`
    : `legacy ${PROFILE_NAME}, no longer read: the user runs /oasis migrate`;
  const names = Object.keys(TOOL_LINES).filter((name) => !tools || tools.includes(name));
  const routing = names.length > 0
    ? [
        "Prefer oasis tools to raw shell (guarded, compact):",
        ...names.map((name) => `- ${name}: ${TOOL_LINES[name]}`),
        "Read logs only if a summary falls short. Do not browse Odoo source for",
      ]
    : [
        "This session has no oasis tools. Instead of raw odoo-bin, psql or dropdb, run the guarded CLI:",
        `\`oasis --project ${root} <command>\` (test-module --compact, module-status, doctor --environment --quick,`,
        "lint-module, model-info). Do not browse Odoo source for",
      ];
  return [
    `${odoo} project root: ${root} (${source}).`,
    ...routing,
    `framework APIs; load the ${skills} first.`,
    "Tier B commands (oasis policy --json) wait for the user's confirmation; never bypass a refusal.",
  ].join("\n");
}

/**
 * The --confirm value of a Tier B command from its dry-run plan (v0.16.0 S1): worktree-init's
 * `worktree: <path>` line, migrate's `write <dir>/oasis-workspace.toml` line; null when absent.
 */
export function planConfirmation(kind: "worktree" | "migrate", plan: string): string | null {
  for (const line of plan.split("\n")) {
    if (kind === "worktree" && line.startsWith("worktree: ")) return line.slice("worktree: ".length);
    if (kind === "migrate" && line.startsWith("write ") && line.endsWith(`/${WORKSPACE_NAME}`)) return line.slice("write ".length);
  }
  return null;
}

/**
 * What the user's /oasis worktree and /oasis migrate need: `run` runs the oasis CLI in the project
 * root with these arguments (after `--project <root>`), `ui` the session's dialogs.
 */
export interface PlanFlow {
  run(args: string[]): Promise<{ code: number; stdout: string; stderr: string }>;
  ui: {
    notify(message: string, level?: "info" | "warning" | "error"): void;
    confirm(title: string, message: string): Promise<boolean>;
  };
}

/** A run's stdout and stderr, trimmed, else its exit status. */
function shown(result: { code: number; stdout: string; stderr: string }): string {
  return [result.stdout.trim(), result.stderr.trim()].filter(Boolean).join("\n") || `exit ${result.code}`;
}

/**
 * The user's /oasis worktree: the dry-run plan in a dialog, then, on yes, `worktree-init <feature>
 * <branch> --confirm <the worktree path the plan names>` (Tier B, see planConfirmation). A plan
 * without that line runs unconfirmed, so the CLI's own refusal names the command.
 */
export async function worktreeFlow(flow: PlanFlow, feature: string, branch: string): Promise<void> {
  const args = ["worktree-init", feature, branch];
  try {
    const plan = await flow.run([...args, "--dry-run"]);
    if (plan.code !== 0) {
      flow.ui.notify(`oasis worktree: ${plan.stderr.trim() || `exit ${plan.code}`}`, "error");
      return;
    }
    const steps = plan.stdout.trim().split("\n").filter((line) => line !== "dry run: nothing changed");
    if (!(await flow.ui.confirm("oasis worktree", `${steps.join("\n")}\n\nCreate this worktree?`))) {
      flow.ui.notify("oasis worktree: nothing changed.", "info");
      return;
    }
    const path = planConfirmation("worktree", plan.stdout);
    const result = await flow.run(path === null ? args : [...args, "--confirm", path]);
    flow.ui.notify(`oasis worktree:\n${shown(result)}`, result.code === 0 ? "info" : "error");
  } catch (error) {
    flow.ui.notify(`oasis worktree failed: ${error instanceof Error ? error.message : String(error)}`, "error");
  }
}

/**
 * The user's /oasis migrate: the plan in a dialog, then, on yes, `migrate --apply --confirm <the
 * workspace file the plan writes>` (Tier B, see planConfirmation); `nothing to migrate` is only shown.
 */
export async function migrateFlow(flow: PlanFlow): Promise<void> {
  try {
    const plan = await flow.run(["migrate"]);
    if (plan.code !== 0) {
      flow.ui.notify(`oasis migrate: ${plan.stderr.trim() || `exit ${plan.code}`}`, "error");
      return;
    }
    const output = plan.stdout.trim();
    if (output.startsWith("nothing to migrate")) {
      flow.ui.notify(`oasis migrate: ${output}`, "info");
      return;
    }
    const steps = output.split("\n").filter((line) => !line.startsWith("dry run: "));
    if (!(await flow.ui.confirm("oasis migrate", `${steps.join("\n")}\n\nMigrate to this workspace file?`))) {
      flow.ui.notify("oasis migrate: nothing changed.", "info");
      return;
    }
    const workspace = planConfirmation("migrate", plan.stdout);
    const confirm = workspace === null ? [] : ["--confirm", workspace];
    const result = await flow.run(["migrate", "--apply", ...confirm]);
    flow.ui.notify(`oasis migrate:\n${shown(result)}`, result.code === 0 ? "info" : "error");
  } catch (error) {
    flow.ui.notify(`oasis migrate failed: ${error instanceof Error ? error.message : String(error)}`, "error");
  }
}
