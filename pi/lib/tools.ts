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
  // Odoo reports success when a class or method filter matches nothing: say so.
  const unmatched = only && /^result: .* of 0 tests\b/m.test(summary)
    ? [`no test matched only=${only}: check the class and method names`]
    : [];
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
 * tools/config.py values: `logs` is [tooling].logs (LOGS_DIR) when set; otherwise `devLogs` holds
 * the checkout's dev/logs/odoo19 and, for a linked worktree, the main checkout's.
 */
export interface RunLogLocations {
  logs?: string;
  devLogs: string[];
}

function withoutTrailingSlash(path: string): string {
  return path.length > 1 ? path.replace(/\/+$/, "") : path;
}

export function runLogLocations(config: Record<string, string>): RunLogLocations {
  if (config.LOGS_DIR) return { logs: withoutTrailingSlash(config.LOGS_DIR), devLogs: [] };
  const devLogs = [`${withoutTrailingSlash(config.PROJECT_ROOT ?? "")}/dev/logs/odoo19`];
  if (config.CHECKOUT_KIND === "linked" && config.CHECKOUT_MAIN_ROOT) {
    devLogs.push(`${withoutTrailingSlash(config.CHECKOUT_MAIN_ROOT)}/dev/logs/odoo19`);
  }
  return { devLogs };
}

const RUN_FILE = /^run-[A-Za-z0-9_]+\/(?:stdout|stderr)\.log$/;
// <logs>/<checkout>/run-<id>/ (since 0.8.0); <checkout> is `main` or a checkout slug.
const CHECKOUT_RUN = /^[a-z0-9][a-z0-9_]{0,19}\/run-[A-Za-z0-9_]+\/(?:stdout|stderr)\.log$/;
// <logs>/odoo19/<checkout>/run-<id>/ (before 0.8.0).
const LEGACY_CHECKOUT_RUN = /^odoo19\/[A-Za-z0-9_]+\/run-[A-Za-z0-9_]+\/(?:stdout|stderr)\.log$/;

function below(path: string, base: string): string | null {
  return base.startsWith("/") && path.startsWith(`${base}/`) ? path.slice(base.length + 1) : null;
}

/**
 * Whether a path is a log a compact run of this checkout writes: stdout.log or stderr.log in
 * <logs>/<checkout>/run-<id>/ or, from runs before 0.8.0, <logs>/odoo19/<checkout>/run-<id>/ when
 * [tooling].logs is set; otherwise in <dev logs>/run-<id>/ of one of `devLogs`.
 */
export function isRunLog(path: string, locations: RunLogLocations): boolean {
  if (!path.startsWith("/") || path.split("/").some((part) => part === ".." || part === ".")) return false;
  if (locations.logs) {
    const rest = below(path, locations.logs);
    return rest !== null && (CHECKOUT_RUN.test(rest) || LEGACY_CHECKOUT_RUN.test(rest));
  }
  return locations.devLogs.some((base) => {
    const rest = below(path, base);
    return rest !== null && RUN_FILE.test(rest);
  });
}

/**
 * Summary of a compact test run that was started outside the tool (for example in the
 * background): `output` is what `oasis ... test-module --compact` printed. Only the run logs it
 * names are read, and only inside the checkout's log locations (runLogLocations).
 */
export function formatBackgroundRun(
  module: string,
  output: string,
  readLog: (path: string) => string,
  options: SummaryOptions,
  locations: RunLogLocations,
  maxLines = 60,
): string {
  const values = keyValues(output);
  if (!values.stdout_log || !isRunLog(values.stdout_log, locations) ||
      (values.stderr_log && !isRunLog(values.stderr_log, locations))) {
    throw new Error(
      "Pass the output of `oasis --project <root> test-module --compact <module>`: " +
        "it must name the run's stdout_log and stderr_log.",
    );
  }
  const code = Number.parseInt(values.exit ?? "", 10);
  const result = { code: Number.isInteger(code) ? code : 1, stdout: output, stderr: "" };
  return formatTestRun(module, result, readLog, options, maxLines);
}
