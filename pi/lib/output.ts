// Token-saving output shaping. No Pi imports: tested directly with node:test.

const LOG_LINE = /^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d,\d+ \d+ (\w+) \S+ ([\w.]+): (.*)$/;
const RESULT_LOGGER = "odoo.tests.result";

export interface SummaryOptions {
  /** Problems shown in full; the total is always reported. */
  maxFailures: number;
  /** Last traceback lines kept per problem (the end carries the assertion). */
  traceLines: number;
}

interface Problem {
  header: string;
  trace: string[];
}

/** Reduce an Odoo test run log to its result line and ERROR/CRITICAL entries. */
export function summarizeTestLog(stdout: string, stderr: string, options: SummaryOptions): string {
  let result = "not reported";
  const problems: Problem[] = [];
  let current: Problem | null = null;
  for (const line of `${stdout}\n${stderr}`.split("\n")) {
    const match = LOG_LINE.exec(line);
    if (!match) {
      if (current && line.trim()) current.trace.push(line);
      continue;
    }
    const [, level, logger, message] = match;
    current = null;
    if (logger === RESULT_LOGGER) {
      result = message;
    } else if (level === "ERROR" || level === "CRITICAL") {
      current = { header: `- ${message} [${logger}]`, trace: [] };
      problems.push(current);
    }
  }
  const lines = [`result: ${result}`];
  if (!problems.length) {
    lines.push("problems: 0");
    return lines.join("\n");
  }
  const shown = problems.slice(0, Math.max(0, options.maxFailures));
  lines.push(`problems: ${problems.length} (showing ${shown.length})`);
  for (const problem of shown) {
    lines.push(problem.header);
    const keep = options.traceLines > 0 ? problem.trace.slice(-options.traceLines) : [];
    for (const trace of keep) lines.push(`    ${trace}`);
  }
  return lines.join("\n");
}

/** Keep the first and last lines of long output and state how many were dropped. */
export function limitLines(text: string, maxLines: number): string {
  const lines = text.split("\n");
  if (lines.length <= maxLines) return text;
  const head = Math.floor(maxLines / 2);
  const tail = maxLines - head;
  return [
    ...lines.slice(0, head),
    `... ${lines.length - maxLines} lines omitted ...`,
    ...lines.slice(lines.length - tail),
  ].join("\n");
}
