// /odoo19 status: parse the core's profile output and format a compact report. No Pi imports.
import { existsSync, readdirSync, type Dirent } from "node:fs";
import { join, resolve } from "node:path";

const SHOWN_MODULES = 10;

/** Parse `NAME=value` lines as printed by tools/config.py (shlex.quote values). */
export function parseAssignments(output: string): Record<string, string> {
  const values: Record<string, string> = {};
  let i = 0;
  while (i < output.length) {
    const name = /^[A-Z_][A-Z0-9_]*=/.exec(output.slice(i));
    if (!name) {
      const next = output.indexOf("\n", i);
      i = next < 0 ? output.length : next + 1;
      continue;
    }
    i += name[0].length;
    let value = "";
    while (i < output.length && output[i] !== "\n") {
      const quote = output[i];
      if (quote === "'" || quote === '"') {
        const end = output.indexOf(quote, i + 1);
        const stop = end < 0 ? output.length : end;
        value += output.slice(i + 1, stop);
        i = stop + 1;
      } else {
        value += quote;
        i++;
      }
    }
    values[name[0].slice(0, -1)] = value;
    i++;
  }
  return values;
}

export interface StatusInput {
  root: string;
  config?: Record<string, string>;
  configError?: string;
  modules: { root: string; names: string[] }[];
  git: { branch: string; linkedWorktree: boolean; changedFiles: number } | null;
}

/**
 * Build the git summary from `git rev-parse --abbrev-ref HEAD --git-dir --git-common-dir` and
 * `git status --porcelain` output. Relative dirs are resolved against the root; a linked worktree
 * has a git dir that differs from the common dir. Returns null on unexpected output.
 */
export function parseGit(root: string, revParse: string, porcelain: string): StatusInput["git"] {
  const [branch, gitDir, commonDir] = revParse.split("\n").map((line) => line.trim());
  if (!branch || !gitDir || !commonDir) return null;
  return {
    branch,
    linkedWorktree: resolve(root, gitDir) !== resolve(root, commonDir),
    changedFiles: porcelain.split("\n").filter((line) => line.trim()).length,
  };
}

export function formatStatus(input: StatusInput): string {
  const lines = [`odoo19 project: ${input.root}`];
  if (input.configError) lines.push(`profile: ${input.configError}`);
  const config = input.config;
  if (config) {
    lines.push(`odoo source: ${config.ODOO_SOURCE ?? "?"}`);
    const test = config.TEST_DATABASE
      ? `${config.TEST_DATABASE} (prefix ${config.TEST_PREFIX})`
      : `${config.TEST_PREFIX}<module>`;
    lines.push(`databases: dev ${config.DEV_PREFIX}<module>, test ${test}`);
  }
  for (const { root, names } of input.modules) {
    const shown = names.slice(0, SHOWN_MODULES).join(", ");
    const more = names.length > SHOWN_MODULES ? `, ... +${names.length - SHOWN_MODULES}` : "";
    lines.push(`addons: ${root} (${names.length}): ${shown}${more}`);
  }
  const git = input.git;
  if (!git) {
    lines.push("git: not a git checkout");
  } else {
    const kind = git.linkedWorktree ? "linked worktree" : "main checkout";
    const state = git.changedFiles ? `${git.changedFiles} changed files` : "clean";
    lines.push(`git: ${git.branch}, ${kind}, ${state}`);
  }
  return lines.join("\n");
}

/** Technical names of the modules (directories with __manifest__.py) directly under an addons root. */
export function listModules(addonsRoot: string): string[] {
  let entries: Dirent[];
  try {
    entries = readdirSync(addonsRoot, { withFileTypes: true });
  } catch {
    return [];
  }
  return entries
    .filter((entry) => entry.isDirectory() && existsSync(join(addonsRoot, entry.name, "__manifest__.py")))
    .map((entry) => entry.name)
    .sort();
}
