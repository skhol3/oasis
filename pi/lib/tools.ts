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

const RUN_LOG = /\/odoo19\/(?:[A-Za-z0-9_]+\/)?run-[A-Za-z0-9_]+\/(?:stdout|stderr)\.log$/;

/** Whether a path is a log a compact run writes: stdout.log or stderr.log in <logs>/odoo19/[<checkout>/]run-<id>/. */
export function isRunLog(path: string): boolean {
  return path.startsWith("/") && !path.split("/").includes("..") && RUN_LOG.test(path);
}

/**
 * Summary of a compact test run that was started outside the tool (for example in the
 * background): `output` is what `oasis ... test-module --compact` printed. Only the run logs it
 * names are read.
 */
export function formatBackgroundRun(
  module: string,
  output: string,
  readLog: (path: string) => string,
  options: SummaryOptions,
  maxLines = 60,
): string {
  const values = keyValues(output);
  if (!values.stdout_log || !isRunLog(values.stdout_log) || (values.stderr_log && !isRunLog(values.stderr_log))) {
    throw new Error(
      "Pass the output of `oasis --project <root> test-module --compact <module>`: " +
        "it must name the run's stdout_log and stderr_log.",
    );
  }
  const code = Number.parseInt(values.exit ?? "", 10);
  const result = { code: Number.isInteger(code) ? code : 1, stdout: output, stderr: "" };
  return formatTestRun(module, result, readLog, options, maxLines);
}
