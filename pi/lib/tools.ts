// Argument building and result formatting for the oasis tools. No Pi imports.
import { limitLines, summarizeTestLog, type SummaryOptions } from "./output.ts";

export interface CoreResult {
  code: number;
  stdout: string;
  stderr: string;
}

export function testModuleArgs(params: { module: string; database?: string }): string[] {
  return ["test-module", "--compact", params.module, ...(params.database ? [params.database] : [])];
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
): string {
  const values = keyValues(result.stdout);
  // Without logs the core refused before running tests; its message is already short.
  if (!values.stdout_log) return formatPlain(result, maxLines);
  const stderrLog = values.stderr_log ?? "";
  // A disposable database (no explicit or configured one) is reported as dropped or not.
  const lifecycle = values.database_lifecycle
    ? ` database_lifecycle=${values.database_lifecycle} dropped=${values.dropped ?? ""}`
    : "";
  return [
    `module=${module} database=${values.database ?? ""} exit=${result.code}${lifecycle}`,
    summarizeTestLog(readLog(values.stdout_log), stderrLog ? readLog(stderrLog) : "", options),
    `logs: ${values.stdout_log} ${stderrLog}`.trimEnd(),
  ].join("\n");
}
