// Token-saving output shaping. No Pi imports: tested directly with node:test.

const LOG_LINE = /^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d,\d+ \d+ (\w+) \S+ ([\w.]+): (.*)$/;
const RESULT_LOGGER = "odoo.tests.result";
const STATS_LOGGER = "odoo.tests.stats";
const MAX_STATS = 5;
const SHOWN_WARNING_GROUPS = 3;
const WARNING_MESSAGE_CHARS = 80;
const HEX_ADDRESS = /0x[0-9a-fA-F]+/g;

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

interface WarningGroup {
  logger: string;
  message: string;
  count: number;
}

/**
 * Stable grouping text for a warning: hex addresses removed, cut before the first ` <` or `(`
 * detail part (frames, ids) and at most WARNING_MESSAGE_CHARS characters; "…" marks a cut.
 */
function warningKey(message: string): string {
  const clean = message.replace(HEX_ADDRESS, "").replace(/\s+/g, " ").trim();
  const detail = [clean.indexOf(" <"), clean.indexOf("(")].filter((at) => at > 0);
  let cut = detail.length ? Math.min(...detail) : clean.length;
  cut = Math.min(cut, WARNING_MESSAGE_CHARS);
  if (cut >= clean.length) return clean;
  return `${clean.slice(0, cut).trimEnd()}…`;
}

function formatWarnings(groups: WarningGroup[]): string {
  const total = groups.reduce((sum, group) => sum + group.count, 0);
  // Array.prototype.sort is stable, so equal counts keep their first-seen order.
  const ordered = [...groups].sort((a, b) => b.count - a.count);
  const shown = ordered.slice(0, SHOWN_WARNING_GROUPS).map((group) => `${group.logger} ×${group.count}: ${group.message}`);
  if (ordered.length > SHOWN_WARNING_GROUPS) shown.push(`+${ordered.length - SHOWN_WARNING_GROUPS} more groups`);
  return `warnings: ${total} (${shown.join("; ")})`;
}

/** Newline characters in a text: what `wc -l` reports for it, so an unterminated last line is not counted. */
function countNewlines(text: string): number {
  return text.split("\n").length - 1;
}

/**
 * Reduce an Odoo test run log to its result line, up to MAX_STATS stats lines, the ERROR/CRITICAL
 * entries, one line of grouped warnings (omitted when there are none) and, always last, the control
 * line `log: <lines> lines, <errors> errors, <warnings> warnings`. Its counts are never capped, so
 * a reader can check the summary against the full logs: lines as `cat stdout stderr | wc -l`,
 * errors as ERROR/CRITICAL log lines except odoo.tests.result, warnings as WARNING log lines except
 * odoo.tests.* loggers.
 */
export function summarizeTestLog(stdout: string, stderr: string, options: SummaryOptions): string {
  let result = "not reported";
  const problems: Problem[] = [];
  const stats: string[] = [];
  const warnings = new Map<string, WarningGroup>();
  let errorCount = 0;
  let warningCount = 0;
  let current: Problem | null = null;
  for (const line of `${stdout}\n${stderr}`.split("\n")) {
    const match = LOG_LINE.exec(line);
    if (!match) {
      if (current && line.trim()) current.trace.push(line);
      continue;
    }
    const [, level, logger, message] = match;
    current = null;
    if ((level === "ERROR" || level === "CRITICAL") && logger !== RESULT_LOGGER) errorCount++;
    if (level === "WARNING" && !logger.startsWith("odoo.tests.")) warningCount++;
    if (logger === RESULT_LOGGER) {
      result = message;
    } else if (logger === STATS_LOGGER) {
      if (stats.length < MAX_STATS) stats.push(`stats: ${message.trim()}`);
    } else if (level === "WARNING") {
      if (logger.startsWith("odoo.tests.")) continue;
      const text = warningKey(message);
      const key = `${logger}\0${text}`;
      const group = warnings.get(key);
      if (group) group.count++;
      else warnings.set(key, { logger, message: text, count: 1 });
    } else if (level === "ERROR" || level === "CRITICAL") {
      current = { header: `- ${message} [${logger}]`, trace: [] };
      problems.push(current);
    }
  }
  const lines = [`result: ${result}`, ...stats];
  if (!problems.length) {
    lines.push("problems: 0");
  } else {
    const shown = problems.slice(0, Math.max(0, options.maxFailures));
    lines.push(`problems: ${problems.length} (showing ${shown.length})`);
    for (const problem of shown) {
      lines.push(problem.header);
      const keep = options.traceLines > 0 ? problem.trace.slice(-options.traceLines) : [];
      for (const trace of keep) lines.push(`    ${trace}`);
    }
  }
  if (warnings.size) lines.push(formatWarnings([...warnings.values()]));
  const logLines = countNewlines(stdout) + countNewlines(stderr);
  lines.push(`log: ${logLines} lines, ${errorCount} errors, ${warningCount} warnings`);
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
