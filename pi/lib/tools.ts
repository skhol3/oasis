// Argument building and result formatting for the oasis tools. No Pi imports.
import { limitLines, summarizeTestLog, type SummaryOptions } from "./output.ts";

export interface CoreResult {
  code: number;
  stdout: string;
  stderr: string;
}

export function testModuleArgs(params: {
  module: string;
  database?: string;
  only?: string;
  reuse?: boolean;
}): string[] {
  return [
    "test-module", "--compact",
    ...(params.reuse ? ["--reuse"] : []),
    ...(params.only ? ["--only", params.only] : []),
    params.module,
    ...(params.database ? [params.database] : []),
  ];
}

export function updateModuleArgs(params: { module: string; database: string }): string[] {
  return ["update-module", "--compact", params.module, params.database];
}

export function viewInfoArgs(params: { model: string; type?: string; module?: string }): string[] {
  return [
    "view-info", params.model,
    ...(params.type ? ["--type", params.type] : []),
    ...(params.module ? ["--module", params.module] : []),
  ];
}

export function moduleInfoArgs(params: { module: string; section?: string }): string[] {
  // Only undefined means no section: an empty or unknown one reaches the CLI, which refuses it.
  return ["module-info", params.module, ...(params.section !== undefined ? ["--section", params.section] : [])];
}

export function keyValues(output: string): Record<string, string> {
  const values: Record<string, string> = {};
  for (const line of output.split("\n")) {
    const path = /^(stdout_log|stderr_log)=(.*)$/.exec(line);
    if (path) {
      values[path[1]] = path[2];
      continue;
    }
    for (const pair of line.split(" ")) {
      const index = pair.indexOf("=");
      if (index > 0) values[pair.slice(0, index)] = pair.slice(index + 1);
    }
  }
  return values;
}

/** Exit code plus bounded stdout/stderr, for commands whose output is already terse. */
export function formatPlain(result: CoreResult, maxLines: number): string {
  const body = [result.stdout.trim(), result.stderr.trim()].filter(Boolean).join("\n");
  return `exit=${result.code}\n${limitLines(body, maxLines)}`;
}

/** Compact test-module report: the result line, failures, and where the full logs are. */
export function formatTestRun(
  module: string,
  result: CoreResult,
  readLog: (path: string) => string,
  options: SummaryOptions,
  maxLines = 60,
  only?: string,
): string {
  const values = keyValues(result.stdout);
  // Without logs the core refused before running tests; its message is already short.
  if (!values.stdout_log) return formatPlain(result, maxLines);
  const stderrLog = values.stderr_log ?? "";
  // A disposable database (no explicit or configured one) is reported as dropped or not.
  // A reused one is reported with how the run prepared it (install or update).
  const detail = values.mode !== undefined ? `mode=${values.mode}` : `dropped=${values.dropped ?? ""}`;
  const lifecycle = values.database_lifecycle ? ` database_lifecycle=${values.database_lifecycle} ${detail}` : "";
  const summary = summarizeTestLog(readLog(values.stdout_log), stderrLog ? readLog(stderrLog) : "", options);
  // Odoo reports success when a class or method filter matches nothing, or when the module has no
  // tests at all: say so, so an install-only pass is not read as passing tests.
  const noTests = /^result: .* of 0 tests\b/m.test(summary);
  const unmatched = !noTests ? []
    : only ? [`no test matched only=${only}: check the class and method names`]
    : [`no tests ran: the run only ${values.mode === "update" ? "updated" : "installed"} ${module}`];
  return [
    `module=${module} database=${values.database ?? ""} exit=${result.code}${lifecycle}`,
    summary,
    ...unmatched,
    `logs: ${values.stdout_log} ${stderrLog}`.trimEnd(),
  ].join("\n");
}

/** Compact update-module report: errors, grouped warnings, and where the full logs are. */
export function formatUpdateRun(
  module: string,
  result: CoreResult,
  readLog: (path: string) => string,
  options: SummaryOptions,
  maxLines = 60,
): string {
  const values = keyValues(result.stdout);
  // Without logs the core refused before updating; its message is already short.
  if (!values.stdout_log) return formatPlain(result, maxLines);
  const stderrLog = values.stderr_log ?? "";
  return [
    `module=${module} database=${values.database ?? ""} exit=${result.code}`,
    summarizeTestLog(readLog(values.stdout_log), stderrLog ? readLog(stderrLog) : "", options, false),
    `logs: ${values.stdout_log} ${stderrLog}`.trimEnd(),
  ].join("\n");
}

/**
 * Where a checkout's compact runs write their logs (the rules of tools/compact.sh), from its
 * tools/config.py values. `logs` is [tooling].logs (LOGS_DIR, already resolved) when set.
 * Otherwise `devLogs` holds the checkout's dev/logs/odoo19 and, for a linked worktree, the main
 * checkout's; a dev logs directory counts only when its real path lies in one of
 * `devContainers`: the checkout, or (a linked worktree whose dev/logs links there) the main
 * checkout's dev/logs/odoo19.
 */
export interface RunLogLocations {
  logs?: string;
  devLogs: string[];
  devContainers: string[];
}

/** The real path of an existing path (node:fs realpathSync); throws when it cannot resolve. */
export type RealPath = (path: string) => string;

/** How the summary reaches the disk: injected so this module stays free of Pi and fs access. */
export interface RunLogFiles {
  realpath: RealPath;
  readLog: (path: string) => string;
}

function withoutTrailingSlash(path: string): string {
  return path.length > 1 ? path.replace(/\/+$/, "") : path;
}

export function runLogLocations(config: Record<string, string>): RunLogLocations {
  if (config.LOGS_DIR) return { logs: withoutTrailingSlash(config.LOGS_DIR), devLogs: [], devContainers: [] };
  const root = withoutTrailingSlash(config.PROJECT_ROOT ?? "");
  const devLogs = [`${root}/dev/logs/odoo19`];
  const devContainers = [root];
  if (config.CHECKOUT_KIND === "linked" && config.CHECKOUT_MAIN_ROOT) {
    const main = `${withoutTrailingSlash(config.CHECKOUT_MAIN_ROOT)}/dev/logs/odoo19`;
    devLogs.push(main);
    devContainers.push(main);
  }
  return { devLogs, devContainers };
}

const RUN_FILE = /^run-[A-Za-z0-9_]+\/(?:stdout|stderr)\.log$/;
// <logs>/<checkout>/run-<id>/ (since 0.8.0); <checkout> is `main` or a checkout slug.
const CHECKOUT_RUN = /^[a-z0-9][a-z0-9_]{0,19}\/run-[A-Za-z0-9_]+\/(?:stdout|stderr)\.log$/;
// <logs>/odoo19/<checkout>/run-<id>/ (before 0.8.0).
const LEGACY_CHECKOUT_RUN = /^odoo19\/[A-Za-z0-9_]+\/run-[A-Za-z0-9_]+\/(?:stdout|stderr)\.log$/;

function below(path: string, base: string): string | null {
  return base.startsWith("/") && path.startsWith(`${base}/`) ? path.slice(base.length + 1) : null;
}

function within(path: string, base: string): boolean {
  return path === base || below(path, base) !== null;
}

function lexical(path: string): boolean {
  return path.startsWith("/") && !path.split("/").some((part) => part === ".." || part === ".");
}

function resolve(realpath: RealPath, path: string): string | null {
  try {
    const real = realpath(path);
    return typeof real === "string" && lexical(real) ? real : null;
  } catch {
    return null;
  }
}

/** Whether `path` has the shape of a run log in these (lexical or real) locations. */
function runLogShape(path: string, logs: string | undefined, devLogs: string[]): boolean {
  if (!lexical(path)) return false;
  if (logs) {
    const rest = below(path, logs);
    return rest !== null && (CHECKOUT_RUN.test(rest) || LEGACY_CHECKOUT_RUN.test(rest));
  }
  return devLogs.some((base) => {
    const rest = below(path, base);
    return rest !== null && RUN_FILE.test(rest);
  });
}

/**
 * The real path of a log a compact run of this checkout writes, or null: stdout.log or stderr.log
 * in <logs>/<checkout>/run-<id>/ or, from runs before 0.8.0, <logs>/odoo19/<checkout>/run-<id>/
 * when [tooling].logs is set; otherwise in <dev logs>/run-<id>/ of one of `devLogs`. The named
 * path must have that shape, and so must its real path inside the real location, so a symlinked
 * run directory or log file cannot lead elsewhere. A path that cannot be resolved is refused.
 */
export function runLogRealPath(path: string, locations: RunLogLocations, realpath: RealPath): string | null {
  if (!runLogShape(path, locations.logs, locations.devLogs)) return null;
  const real = resolve(realpath, path);
  if (real === null) return null;
  if (locations.logs) {
    const logs = resolve(realpath, locations.logs);
    return logs !== null && runLogShape(real, logs, []) ? real : null;
  }
  const containers = locations.devContainers.map((path) => resolve(realpath, path))
    .filter((path): path is string => path !== null);
  const devLogs = locations.devLogs.map((path) => resolve(realpath, path))
    .filter((path): path is string => path !== null && containers.some((container) => within(path, container)));
  return runLogShape(real, undefined, devLogs) ? real : null;
}

export function isRunLog(path: string, locations: RunLogLocations, realpath: RealPath): boolean {
  return runLogRealPath(path, locations, realpath) !== null;
}

/**
 * Summary of a compact test run that was started outside the tool (for example in the
 * background): `output` is what `oasis ... test-module --compact` printed and `config` the
 * checkout's tools/config.py values. Only the run logs it names are read, through their real
 * paths, and only inside the checkout's log locations (runLogLocations, runLogRealPath).
 */
export function formatBackgroundRun(
  module: string,
  output: string,
  config: Record<string, string>,
  files: RunLogFiles,
  options: SummaryOptions,
  maxLines = 60,
): string {
  const values = keyValues(output);
  const locations = runLogLocations(config);
  const stdoutLog = values.stdout_log ? runLogRealPath(values.stdout_log, locations, files.realpath) : null;
  const stderrLog = values.stderr_log ? runLogRealPath(values.stderr_log, locations, files.realpath) : "";
  if (!stdoutLog || stderrLog === null) {
    throw new Error(
      "Pass the output of `oasis --project <root> test-module --compact <module>`: " +
        "it must name the run's stdout_log and stderr_log.",
    );
  }
  const checked = new Map([[values.stdout_log, stdoutLog], [values.stderr_log, stderrLog]]);
  const readLog = (path: string): string => {
    const real = checked.get(path);
    return real ? files.readLog(real) : "";
  };
  const code = Number.parseInt(values.exit ?? "", 10);
  const result = { code: Number.isInteger(code) ? code : 1, stdout: output, stderr: "" };
  return formatTestRun(module, result, readLog, options, maxLines);
}
