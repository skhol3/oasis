// The action panel's logic over the core catalog (`oasis menu --catalog`, tools/actions.py): template
// fill, input order and validation, confirmations, output and picker navigation. No Pi imports: the
// panel (pi/ui/menu-panel.ts, pi/extensions/oasis.ts) injects the dialogs and the command runner.
import { limitLines } from "./output.ts";
import { type CoreResult, formatTestRun, formatUpdateRun } from "./tools.ts";

export const CATALOG_VERSION = 1;
export const MENU_KEY_DEFAULT = "alt+o";
/** The select option that switches a choice to typing a value (allow_new). */
export const TYPE_OPTION = "(type a name)";
const NO_OUTPUT = "(no output)";
// Panel output is for the user, not the model: bounded only to keep the session file reasonable.
const OUTPUT_MAX_LINES = 1000;
// Compact test and update summaries use the agent tools' bounds.
const SUMMARY_MAX_LINES = 60;
const SUMMARY_OPTIONS = { maxFailures: 10, traceLines: 6 };

export type Token = string | { input: string; option?: string; flag?: string } | { compact: string };

export interface CatalogInput {
  id: string;
  label: string;
  kind: "choice" | "text" | "boolean";
  source: "modules" | "databases" | null;
  required: boolean;
  allow_new: boolean;
  pattern: string | null;
  error: string | null;
  default: boolean | null;
  hint: string | null;
}

export interface CatalogAction {
  id: string;
  group: string;
  label: string;
  kind: "command" | "log";
  command: string | null;
  argv: Token[];
  inputs: CatalogInput[];
  destructive: boolean;
  confirm: "database" | "yes" | null;
  user_run: boolean;
  terminal_only: boolean;
}

export interface Catalog {
  catalog_version: number;
  project: string;
  entrypoint: string;
  server_log: string;
  sources: {
    modules: { choices: string[] };
    databases: { argv: string[]; waiting: string };
  };
  groups: { id: string; label: string }[];
  actions: CatalogAction[];
}

export type Answers = Record<string, string | boolean>;
export type Level = "info" | "warning" | "error";
export type Source = "modules" | "databases";

/** The dialogs the panel asks with (ctx.ui select, input, confirm and notify). */
export interface Prompter {
  select(title: string, options: string[]): Promise<string | undefined>;
  input(title: string, placeholder?: string): Promise<string | undefined>;
  confirm(title: string, message: string): Promise<boolean>;
  notify(message: string, level: Level): void;
}

/** The catalog printed by `oasis menu --catalog`; throws an Error that says what is wrong. */
export function parseCatalog(text: string): Catalog {
  let data: unknown;
  try {
    data = JSON.parse(text);
  } catch (error) {
    throw new Error(`the catalog is not JSON: ${error instanceof Error ? error.message : String(error)}`);
  }
  const catalog = data as Partial<Catalog> | null;
  if (catalog?.catalog_version !== CATALOG_VERSION) {
    throw new Error(
      `unsupported catalog_version ${String(catalog?.catalog_version)} (this panel reads version ` +
        `${CATALOG_VERSION}); update the oasis layer.`,
    );
  }
  if (!Array.isArray(catalog.actions) || catalog.actions.length === 0) throw new Error("the catalog has no actions.");
  if (!Array.isArray(catalog.groups) || !catalog.sources) throw new Error("the catalog has no groups or sources.");
  return catalog as Catalog;
}

/** The argv of an action from its template and the answers (the rules of tools/actions.py build). */
export function fillTemplate(action: CatalogAction, answers: Answers, compact: boolean): string[] {
  const argv: string[] = [];
  for (const token of action.argv) {
    if (typeof token === "string") {
      argv.push(token);
    } else if ("compact" in token) {
      if (compact) argv.push(token.compact);
    } else if (token.flag !== undefined) {
      if (answers[token.input] === true) argv.push(token.flag);
    } else {
      const answer = answers[token.input];
      const value = typeof answer === "string" ? answer : "";
      if (value) argv.push(...(token.option !== undefined ? [token.option, value] : [value]));
    }
  }
  return argv;
}

const SHELL_SAFE = /^[A-Za-z0-9_@%+=:,./-]+$/;

function shellQuote(word: string): string {
  if (word === "") return "''";
  if (SHELL_SAFE.test(word)) return word;
  return `'${word.replaceAll("'", "'\"'\"'")}'`;
}

/** argv as one shell line, quoted like Python's shlex.join (the terminal menu's `Command:`). */
export function shellJoin(argv: string[]): string {
  return argv.map(shellQuote).join(" ");
}

/** The command of an action with placeholders for its inputs, to copy into a terminal. */
export function terminalCommand(action: CatalogAction): string {
  return action.argv.map((token) => {
    if (typeof token === "string") return shellQuote(token);
    if ("compact" in token) return token.compact;
    if (token.flag !== undefined) return `[${token.flag}]`;
    if (token.option !== undefined) return `[${token.option} <${token.input}>]`;
    return `<${token.input}>`;
  }).join(" ");
}

/** Why a typed value is refused (required, an option-like word, the catalog pattern), or null. */
export function textError(input: CatalogInput, value: string): string | null {
  if (!value) return input.required ? "A value is required." : null;
  if (value.startsWith("-")) return "A value cannot start with -.";
  if (input.pattern && !new RegExp(input.pattern).test(value)) return input.error ?? "Invalid value.";
  return null;
}

function skipOption(input: CatalogInput): string {
  const hint = input.hint?.replace(/^Enter\s+/, "");
  return hint ? `(skip: ${hint})` : "(skip)";
}

/** A typed value, asked again until it is valid; undefined when the user cancels. */
async function typed(input: CatalogInput, prompter: Prompter, placeholder?: string): Promise<string | undefined> {
  for (;;) {
    const answer = await prompter.input(input.label, placeholder);
    if (answer === undefined) return undefined;
    const value = answer.trim();
    const error = textError(input, value);
    if (error === null) return value;
    prompter.notify(error, "warning");
  }
}

async function answer(
  input: CatalogInput, prompter: Prompter, choices: (source: Source) => Promise<string[]>,
): Promise<string | boolean | undefined> {
  if (input.kind === "boolean") {
    const picked = await prompter.select(`${input.label}?`, ["No", "Yes"]);
    return picked === undefined ? undefined : picked === "Yes";
  }
  if (input.kind === "text") return typed(input, prompter, input.hint ?? undefined);
  const listed = input.source ? await choices(input.source) : [];
  if (listed.length === 0) {
    if (!input.allow_new) {
      prompter.notify(`No ${input.label.toLowerCase()}s found in this checkout.`, "warning");
      return undefined;
    }
    prompter.notify(`No ${input.label.toLowerCase()}s found.`, "info");
  }
  const skip = input.required ? [] : [skipOption(input)];
  const options = [...skip, ...listed, ...(input.allow_new ? [TYPE_OPTION] : [])];
  if (options.length === 1 && options[0] === TYPE_OPTION) return typed(input, prompter);
  const picked = await prompter.select(input.label, options);
  if (picked === undefined) return undefined;
  if (picked === TYPE_OPTION) return typed(input, prompter);
  if (skip.includes(picked)) return "";
  return picked;
}

/** The answers to an action's inputs, asked in catalog order; null when the user cancels. */
export async function askInputs(
  action: CatalogAction, prompter: Prompter, choices: (source: Source) => Promise<string[]>,
): Promise<Answers | null> {
  const answers: Answers = {};
  for (const input of action.inputs) {
    const value = await answer(input, prompter, choices);
    if (value === undefined) return null;
    answers[input.id] = value;
  }
  return answers;
}

export interface SourceHooks {
  exec: (argv: string[]) => Promise<CoreResult>;
  /** Show the waiting text while the databases are listed; called with undefined to clear it. */
  waiting: (text: string | undefined) => void;
  notify: (message: string, level: Level) => void;
}

/** Choices by source: modules from the catalog, databases from its list-databases command, once. */
export function sources(catalog: Catalog, hooks: SourceHooks): (source: Source) => Promise<string[]> {
  let databases: string[] | null = null;
  return async (source) => {
    if (source === "modules") return catalog.sources.modules.choices;
    if (databases !== null) return databases;
    const listing = catalog.sources.databases;
    let result: CoreResult;
    hooks.waiting(listing.waiting);
    try {
      result = await hooks.exec(listing.argv);
    } finally {
      hooks.waiting(undefined);
    }
    if (result.code !== 0) {
      const detail = result.stderr.trim();
      hooks.notify(`Cannot list the databases (exit ${result.code})${detail ? `:\n${detail}` : "."}`, "error");
      databases = [];
    } else {
      databases = result.stdout.split("\n").map((line) => line.trim()).filter(Boolean);
    }
    return databases;
  };
}

/**
 * Whether the action may run: destructive actions need the database name (confirm `database`) or
 * `yes` typed, as the terminal menu asks; a user-run action without that gets a yes/no confirmation;
 * any other action runs without asking. `command` is shown in the question.
 */
export async function confirmRun(
  action: CatalogAction, answers: Answers, command: string, prompter: Prompter,
): Promise<boolean> {
  if (action.confirm === "database") {
    const database = String(answers.database ?? "");
    const typedName = await prompter.input(
      `${action.label}\n${command}\nType the database name to confirm (${database})`,
    );
    return database !== "" && typedName?.trim() === database;
  }
  if (action.confirm === "yes") {
    return (await prompter.input(`${action.label}\n${command}\nType yes to confirm`))?.trim() === "yes";
  }
  if (action.user_run) return prompter.confirm(action.label, `${command}\n\nRun this command?`);
  return true;
}

/** What the panel shows of a finished run: compact summaries for tests and updates, else the output. */
export function menuOutput(
  action: CatalogAction, answers: Answers, result: CoreResult, readLog: (path: string) => string,
): string {
  const module = String(answers.module ?? "");
  if (action.command === "test-module") {
    const only = typeof answers.only === "string" && answers.only ? answers.only : undefined;
    return formatTestRun(module, result, readLog, SUMMARY_OPTIONS, SUMMARY_MAX_LINES, only);
  }
  if (action.command === "update-module") {
    return formatUpdateRun(module, result, readLog, SUMMARY_OPTIONS, SUMMARY_MAX_LINES);
  }
  const body = [result.stdout.trim(), result.stderr.trim()].filter(Boolean).join("\n");
  return body ? limitLines(body, OUTPUT_MAX_LINES) : NO_OUTPUT;
}

/** A panel result as stored in the session (a custom entry, never sent to the model). */
export interface MenuEntry {
  label: string;
  command: string;
  exit?: number;
  note?: string;
  output: string;
}

// CSI and OSC sequences, then any other control character (tabs become spaces first).
const ESCAPES = /\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)?/g;
const CONTROLS = /[\x00-\x1f\x7f-\x9f]/g;

function plainLine(line: string): string {
  return line.replace(ESCAPES, "").replaceAll("\t", "    ").replace(CONTROLS, "");
}

/** The lines of a result entry: title, command and output (its last lines unless expanded). */
export function entryLines(entry: MenuEntry, expanded: boolean, previewLines: number): string[] {
  const status = entry.note ?? (entry.exit !== undefined ? `exit ${entry.exit}` : "");
  const lines = [`oasis: ${entry.label}${status ? ` (${status})` : ""}`, `$ ${entry.command}`];
  if (!entry.output) return lines;
  const output = entry.output.split("\n").map(plainLine);
  if (expanded || output.length <= previewLines) return [...lines, ...output];
  const hidden = output.length - previewLines;
  return [...lines, `… ${hidden} earlier lines`, ...output.slice(hidden)];
}

export interface PickerRow {
  kind: "group" | "action";
  text: string;
  /** "terminal only", "confirm" (asks before running) or "". */
  tag: string;
  action?: CatalogAction;
}

/** The picker's rows: each group label followed by its actions, in catalog order. */
export function pickerRows(catalog: Catalog): PickerRow[] {
  const rows: PickerRow[] = [];
  for (const group of catalog.groups) {
    const members = catalog.actions.filter((item) => item.group === group.id);
    if (members.length === 0) continue;
    rows.push({ kind: "group", text: group.label, tag: "" });
    for (const item of members) {
      const tag = item.terminal_only ? "terminal only" : item.destructive || item.user_run ? "confirm" : "";
      rows.push({ kind: "action", text: item.label, tag, action: item });
    }
  }
  return rows;
}

/** The action row `delta` rows from `index` (clamped); group rows are skipped in the move's direction. */
export function moveSelection(rows: PickerRow[], index: number, delta: number): number {
  const last = rows.length - 1;
  const direction = delta < 0 ? -1 : 1;
  let target = Math.min(Math.max(index + delta, 0), last);
  for (const step of [direction, -direction]) {
    let probe = target;
    while (probe >= 0 && probe <= last && rows[probe].kind !== "action") probe += step;
    if (probe >= 0 && probe <= last) return probe;
  }
  return index;
}

/**
 * The first visible row of a list of `total` rows shown `height` at a time: the previous start
 * while the selection stays in view; scrolling up also shows the row above the selection (its
 * group label when it is the group's first action).
 */
export function visibleStart(total: number, selected: number, height: number, previous: number): number {
  if (total <= height) return 0;
  let start = previous;
  if (selected >= start + height) start = selected - height + 1;
  if (selected < start) start = selected - 1;
  return Math.min(Math.max(start, 0), total - height);
}

const MODIFIER = "(?:ctrl|shift|alt|super)";
const KEY_NAME = "[a-z0-9]|escape|esc|enter|return|tab|space|backspace|delete|insert|clear|home|end|pageup|pagedown" +
  "|up|down|left|right|f(?:[1-9]|1[0-2])|[`\\-=[\\]\\\\;',./!@#$%^&*()_+|~{}:<>?]";
const KEY = new RegExp(`^((?:${MODIFIER}\\+)*)(${KEY_NAME})$`, "i");

/**
 * The panel shortcut from OASIS_MENU_KEY: alt+o when unset, none when empty or `off`. A value that
 * is not a Pi key with ctrl, alt or super (or a function key alone) turns the shortcut off with an
 * error to show, so a plain letter never steals typing. The key is returned lowercased, the form Pi
 * parses, matches and compares key ids in (pi-tui parseKeyId, ExtensionRunner.getShortcuts), so
 * `ALT+O` and `alt+o` register the same shortcut; a repeated modifier never matches there, so it
 * is refused.
 */
export function menuShortcut(value: string | undefined): { key: string | null; error?: string } {
  if (value === undefined) return { key: MENU_KEY_DEFAULT };
  const key = value.trim().toLowerCase();
  if (key === "" || key === "off") return { key: null };
  const match = KEY.exec(key);
  const modifiers = match?.[1].split("+").filter(Boolean) ?? [];
  const repeated = new Set(modifiers).size !== modifiers.length;
  const usable = match !== null && !repeated &&
    (modifiers.some((name) => name !== "shift") || /^f\d+$/.test(match[2]));
  if (usable) return { key };
  return {
    key: null,
    error: `OASIS_MENU_KEY=${JSON.stringify(value)} is not a usable key (for example alt+o, ctrl+shift+m or f5); ` +
      "the menu shortcut is off, /oasis menu still opens the panel.",
  };
}
