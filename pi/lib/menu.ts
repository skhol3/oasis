// The action panel's logic over the core catalog (`oasis menu --catalog`, tools/actions.py): template
// fill, input order and validation, confirmations, output and picker navigation. No Pi imports: the
// panel (pi/ui/menu-panel.ts, pi/extensions/oasis.ts) injects the dialogs and the command runner.
import { abbreviateCommand, type NativeSource, printCommandArgv } from "./native.ts";
import { limitLines } from "./output.ts";
import { type CoreResult, formatTestRun, formatUpdateRun } from "./tools.ts";

const CATALOG_VERSION = 1;
export const MENU_KEY_DEFAULT = "alt+o";
/** The start / restart flow (S3): the panel asks it in one form (RunForm). */
export const RUN_ACTION = "server.run";
const SERVER_COMMANDS = ["start", "restart"] as const;
/** The select option that switches a choice to typing a value (allow_new). */
const TYPE_OPTION = "(type a name)";
const NO_OUTPUT = "(no output)";
// Panel output is for the user, not the model: bounded only to keep the session file reasonable.
const OUTPUT_MAX_LINES = 1000;
// Compact test and update summaries use the agent tools' bounds.
const SUMMARY_MAX_LINES = 60;
const SUMMARY_OPTIONS = { maxFailures: 10, traceLines: 6 };

export type Token = string | { input: string; option?: string; flag?: string } | { compact: string };

/** One value of a closed choice, and what to warn about when it is chosen. */
export interface CatalogChoice {
  value: string;
  label: string;
  warning: string | null;
}

export interface CatalogInput {
  id: string;
  label: string;
  kind: "choice" | "text" | "boolean";
  source: "modules" | "databases" | null;
  required: boolean;
  allow_new: boolean;
  pattern: string | null;
  error: string | null;
  /** Booleans: false; a choice: the value an empty answer takes; a text input: only shown. */
  default: boolean | string | null;
  hint: string | null;
  /** A closed choice without source (v0.12.0; absent in older catalogs). */
  choices?: CatalogChoice[] | null;
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
  /** A log action that keeps showing what the server writes (the panel's live view). */
  follow: boolean;
  /** The action that replaces this one in the menus (v0.12.0): not listed, kept for older panels. */
  superseded_by?: string | null;
}

/** What the headers show and the start / restart flow needs (v0.12.0). */
interface CheckoutInfo {
  name: string;
  server: { state: "running" | "stopped" | "unknown"; pid: number | null; port: number | null;
    database: string | null; error: string | null };
  default_database: string | null;
  no_database: { start: string; restart: string };
}

/** The last action run from a menu in this checkout, still valid (v0.12.0). */
interface LastAction {
  action: string;
  answers: Answers;
  label: string;
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
  checkout?: CheckoutInfo;
  last?: LastAction | null;
}

export type Answers = Record<string, string | boolean>;
type Level = "info" | "warning" | "error";
type Source = "modules" | "databases";

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
  if (input.choices) {
    const picked = await prompter.select(input.label, input.choices.map((choice) => choice.label));
    const chosen = input.choices.find((choice) => choice.label === picked);
    if (!chosen) return undefined;
    if (chosen.warning) prompter.notify(chosen.warning, "warning");
    return chosen.value;
  }
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

/** What to show when start or restart gets no database (the catalog's checkout), else null. */
export function noDatabaseWarning(catalog: Catalog | undefined, action: CatalogAction, answers: Answers): string | null {
  const command = SERVER_COMMANDS.find((name) => name === action.command);
  if (!command || answers.database || !catalog?.checkout) return null;
  return catalog.checkout.no_database[command];
}

/** The warnings of the chosen closed choices (for example reload without its packages). */
export function choiceWarnings(action: CatalogAction, answers: Answers): string[] {
  return action.inputs.flatMap((input) => {
    const warning = input.choices?.find((choice) => choice.value === answers[input.id])?.warning;
    return warning ? [warning] : [];
  });
}

/**
 * Whether the action may run: destructive actions need the database name (confirm `database`) or
 * `yes` typed, as the terminal menu asks; any other action asks yes/no (v0.12.0). The filled
 * `command` is shown in the question, then what start or restart will do without a database and
 * the warnings of the chosen choices.
 */
export async function confirmRun(
  action: CatalogAction, answers: Answers, command: string, prompter: Prompter, catalog?: Catalog,
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
  const notes = [noDatabaseWarning(catalog, action, answers), ...choiceWarnings(action, answers)].filter(Boolean);
  return prompter.confirm(action.label, [command, ...notes, "Run this command?"].join("\n\n"));
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

/** This checkout's server as the extension reads it from `runtime_state.py show` (StatusInput). */
export interface ServerState {
  server?: { pid: number; port: number } | null;
  serverError?: string;
}

/** The panel header's server line: running on its port and pid, stopped, or unknown with the reason. */
export function serverLine(state: ServerState): string {
  if (state.server) return `server: running on port ${state.server.port} (pid ${state.server.pid})`;
  if (state.server === null) return "server: stopped";
  const reason = (state.serverError ?? "").split("\n").map((line) => line.trim()).filter(Boolean).at(-1)
    ?.replace(/^ERROR: /, "");
  return reason ? `server: unknown (${plainLine(reason)})` : "server: unknown";
}

/** The last `count` lines of a log text, without terminal control sequences (plainLine). */
export function lastLines(text: string, count: number): string[] {
  const lines = text.split("\n");
  if (lines.at(-1) === "") lines.pop();
  return lines.slice(Math.max(0, lines.length - count)).map(plainLine);
}

/** What the live log view shows in `height` rows: the last lines, or a placeholder for an empty log. */
export function logView(lines: string[], height: number): string[] {
  if (lines.length === 0) return ["(the server log is empty)"];
  return lines.slice(Math.max(0, lines.length - height));
}

/** A panel result as stored in the session (a custom entry, never sent to the model). */
export interface MenuEntry {
  label: string;
  command: string;
  exit?: number;
  note?: string;
  /** The native odoo-bin line of a start / restart run (S4), when it could be read. */
  native?: string;
  output: string;
}

// CSI and OSC sequences, then any other control character (tabs become spaces first).
const ESCAPES = /\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)?/g;
const CONTROLS = /[\x00-\x1f\x7f-\x9f]/g;

/** A line without terminal control sequences (CSI, OSC, other control characters); tabs become spaces. */
export function plainLine(line: string): string {
  return line.replace(ESCAPES, "").replaceAll("\t", "    ").replace(CONTROLS, "");
}

/** The lines of a result entry: title, command and output (its last lines unless expanded). */
export function entryLines(entry: MenuEntry, expanded: boolean, previewLines: number): string[] {
  const status = entry.note ?? (entry.exit !== undefined ? `exit ${entry.exit}` : "");
  const lines = [`oasis: ${entry.label}${status ? ` (${status})` : ""}`, `$ ${entry.command}`];
  if (entry.native) lines.push(`native: ${entry.native}`);
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
  /** The Repeat row: the remembered answers of its action. */
  answers?: Answers;
}

/** What the picker returns: an action, with answers when it is the Repeat row. */
export interface PickerChoice {
  action: CatalogAction;
  answers?: Answers;
}

/** The menu header: the checkout, its server line (serverLine) and the start / restart flow's default database. */
export function menuHeader(catalog: Catalog, server: string): string {
  const checkout = catalog.checkout;
  return [`checkout: ${checkout?.name ?? "unknown"}`, server,
    `default database: ${checkout?.default_database ?? "none"}`].join("\n");
}

/**
 * The picker's rows: the last action of the checkout first ("Repeat: ..."), when the catalog has
 * it, then each group label followed by its actions in catalog order, without superseded actions.
 */
export function pickerRows(catalog: Catalog): PickerRow[] {
  const rows: PickerRow[] = [];
  const last = catalog.last;
  const repeated = last ? catalog.actions.find((item) => item.id === last.action) : undefined;
  if (last && repeated) rows.push({ kind: "action", text: last.label, tag: "", action: repeated, answers: last.answers });
  for (const group of catalog.groups) {
    const members = catalog.actions.filter((item) => item.group === group.id && !item.superseded_by);
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

/**
 * A line wrapped at spaces to `width` columns, never truncated: continuation lines start with
 * `indent`, and a word longer than a line is split.
 */
export function wrapLine(text: string, width: number, indent = "  "): string[] {
  const room = Math.max(width, indent.length + 1);
  const lines: string[] = [];
  let current = "";
  const push = (line: string) => {
    let rest = line;
    while (rest.length > room) {
      const head = rest.slice(0, room);
      lines.push(head);
      rest = indent + rest.slice(room);
    }
    lines.push(rest);
  };
  for (const word of text.split(" ")) {
    if (current === "") current = word;
    else if (`${current} ${word}`.length <= room) current = `${current} ${word}`;
    else {
      push(current);
      current = indent + word;
    }
  }
  push(current);
  return lines;
}

/** What the start / restart form is opened with. */
export interface FormSpec {
  catalog: Catalog;
  action: CatalogAction;
  /** The menu header (menuHeader), shown first. */
  header: string;
  /** The databases list-databases printed (not listed again on a repeat). */
  databases: string[];
  /** Remembered answers (Repeat): the form opens at its confirmation. */
  answers?: Answers;
  /** The native odoo-bin lines (S4): shown instead of the oasis command once read. */
  native?: NativeSource;
  /** The home directory the native line shows as `~`. */
  home?: string;
}

export interface FormOption {
  label: string;
  value: string;
  /** Choosing it switches to typing a value. */
  type?: boolean;
  /** Always listed, whatever the filter: (none) and (type a name). */
  keep?: boolean;
  /** What the filter matches (default: the label). */
  match?: string;
}

export interface FormLine {
  text: string;
  style: "header" | "answer" | "warning" | "question" | "option" | "selected" | "typed" | "error" | "command" | "more" |
    "plain";
}

const NONE_OPTION = "(none)";
const CONFIRM_OPTIONS: FormOption[] = [{ label: "Run", value: "run" }, { label: "Cancel", value: "cancel" }];
const PRINTABLE = /[^\x00-\x1f\x7f-\x9f]/g;
const NO_MATCH = "  no match: backspace edits the filter";
const NATIVE_LOADING = "(loading the odoo-bin command…)";
// Marker rows around a window of a long list (one above, one below).
const MARKER_ROWS = 2;

/**
 * The start / restart flow as one form (S3, S5): its inputs in catalog order, then a Run / Cancel
 * confirmation; lines() ends with the command filled with the answers so far (the native odoo-bin
 * line once read, v0.12.1 S4). A long list shows a window around the selected row (S1); typing in
 * a list filters it (S2). Pure state: the overlay (pi/ui/menu-panel.ts RunFormPanel) maps keys to
 * move, type, backspace, submit and escape.
 */
export class RunForm {
  readonly spec: FormSpec;
  readonly answers: Answers = {};
  step = 0;
  /** The highlighted row of the shown (filtered) options; -1 (none) while a filter matches no real option. */
  selected = 0;
  typing = false;
  buffer = "";
  /** The text that narrows the current list (S2). */
  filter = "";
  error: string | null = null;
  finished = false;
  result: Answers | undefined = undefined;
  /** The first shown row of a windowed list, kept while the selection stays in it (visibleStart). */
  private listStart = 0;

  constructor(spec: FormSpec) {
    this.spec = spec;
    if (spec.answers) {
      Object.assign(this.answers, spec.answers);
      this.step = spec.action.inputs.length;
    }
    this.enter();
  }

  /** The input being asked, or undefined at the confirmation. */
  get input(): CatalogInput | undefined {
    return this.spec.action.inputs[this.step];
  }

  /** Every option of the current list (the confirmation: Run and Cancel). */
  options(): FormOption[] {
    const input = this.input;
    if (!input) return CONFIRM_OPTIONS;
    if (input.choices) return input.choices.map((choice) => ({ label: choice.label, value: choice.value }));
    if (input.kind === "boolean") return [{ label: "No", value: "" }, { label: "Yes", value: "yes" }];
    if (input.kind === "text") return [];
    const listed = input.source === "databases" ? this.spec.databases
      : input.source === "modules" ? this.spec.catalog.sources.modules.choices : [];
    const preset = typeof input.default === "string" && input.default ? input.default : null;
    const options: FormOption[] = preset ? [{ label: `${preset} (default)`, value: preset, match: preset }] : [];
    if (!input.required && !preset) options.push({ label: `${NONE_OPTION} (default)`, value: "", keep: true });
    options.push(...listed.filter((name) => name !== preset).map((name) => ({ label: name, value: name })));
    if (!input.required && preset) options.push({ label: NONE_OPTION, value: "", keep: true });
    if (input.allow_new) options.push({ label: TYPE_OPTION, value: "", type: true, keep: true });
    return options;
  }

  /** The options shown: those containing the filter (case-insensitive), and the kept ones. */
  shownOptions(): FormOption[] {
    const filter = this.filter.toLowerCase();
    if (!filter) return this.options();
    return this.options().filter((option) => option.keep || (option.match ?? option.label).toLowerCase().includes(filter));
  }

  /** Whether typing filters the current list: an input's list, not a typed value or the confirmation. */
  private filtering(): boolean {
    return this.input !== undefined && !this.typing && !this.finished;
  }

  private defaultIndex(): number {
    const input = this.input;
    const index = input?.choices ? input.choices.findIndex((choice) => choice.value === input.default) : 0;
    return Math.max(0, index);
  }

  /**
   * After the filter changed: the first matching option, from the top of the list. Without a real
   * match no row is highlighted, so Enter answers nothing until the user moves to a kept row.
   */
  private refilter(): void {
    this.listStart = 0;
    if (!this.filter) {
      this.selected = this.defaultIndex();
      return;
    }
    this.selected = this.shownOptions().findIndex((option) => !option.keep);
  }

  private enter(): void {
    const input = this.input;
    this.error = null;
    this.filter = "";
    this.listStart = 0;
    this.typing = input?.kind === "text";
    this.buffer = this.typing && typeof input?.default === "string" ? input.default : "";
    this.selected = this.defaultIndex();
  }

  move(delta: number): void {
    if (this.typing || this.finished) return;
    this.selected = Math.min(Math.max(this.selected + delta, 0), Math.max(0, this.shownOptions().length - 1));
  }

  /** Printable text: the typed value, or the filter of a list. */
  type(text: string): void {
    const printable = (text.match(PRINTABLE) ?? []).join("");
    if (this.finished || !printable) return;
    if (this.typing) {
      this.buffer += printable;
    } else if (this.filtering()) {
      this.filter += printable;
      this.refilter();
    }
  }

  backspace(): void {
    if (this.typing) {
      this.buffer = Array.from(this.buffer).slice(0, -1).join("");
    } else if (this.filtering() && this.filter) {
      this.filter = Array.from(this.filter).slice(0, -1).join("");
      this.refilter();
    }
  }

  cancel(): void {
    this.finished = true;
    this.result = undefined;
  }

  /** Escape: clears a list's filter first; otherwise cancels the form (nothing runs). */
  escape(): void {
    if (this.filtering() && this.filter) {
      this.filter = "";
      this.refilter();
      return;
    }
    this.cancel();
  }

  /** The key hint under the form. */
  hint(): string {
    if (this.typing) return "type · enter accept · esc cancel";
    if (!this.filtering()) return "↑↓ move · enter choose · esc cancel";
    if (this.filter) return "↑↓ move · backspace edits the filter · enter choose · esc clears the filter";
    return "↑↓ move · type to filter · enter choose · esc cancel";
  }

  /** Enter: accept the highlighted option or the typed value (checked like textError), or run / cancel. */
  submit(): void {
    if (this.finished) return;
    const input = this.input;
    if (!input) {
      this.finished = true;
      this.result = this.options()[this.selected]?.value === "run" ? { ...this.answers } : undefined;
      return;
    }
    if (this.typing) {
      const value = this.buffer.trim();
      const error = textError(input, value);
      if (error !== null) {
        this.error = error;
        return;
      }
      // Keeping a text input's shown default leaves its option out: the command applies its own rule.
      this.accept(input, input.kind === "text" && value === input.default ? "" : value);
      return;
    }
    const option = this.shownOptions()[this.selected];
    if (!option) return;
    if (option.type) {
      // Typing starts from the filter: a name that is not listed yet.
      this.typing = true;
      this.buffer = this.filter;
      this.filter = "";
      return;
    }
    this.accept(input, input.kind === "boolean" ? option.value === "yes" : option.value);
  }

  private accept(input: CatalogInput, value: string | boolean): void {
    this.answers[input.id] = value;
    this.step += 1;
    this.enter();
  }

  /** The filled command of the answers so far, as it will run. */
  command(): string {
    return shellJoin(fillTemplate(this.spec.action, this.answers, true));
  }

  /**
   * The command lines, wrapped to `width`: the native odoo-bin line of the answers so far
   * (abbreviated) once read, else the oasis command with a note while it loads or when it failed.
   * Reading the native line of new answers starts here.
   */
  private commandLines(width: number): FormLine[] {
    const action = this.spec.action;
    const argv = this.spec.native ? printCommandArgv(action.command, fillTemplate(action, this.answers, true)) : null;
    const native = argv ? this.spec.native?.get(argv) : undefined;
    const shown = native?.state === "ready" ? abbreviateCommand(native.line, this.spec.home) : this.command();
    const lines: FormLine[] = wrapLine(`$ ${shown}`, width).map((text) => ({ text, style: "command" }));
    const note = native?.state === "loading" ? NATIVE_LOADING
      : native?.state === "failed" ? `(the odoo-bin command is unavailable: ${native.reason}; this is the oasis command)`
        : null;
    // The note is indented under the command; wrapLine drops leading spaces, so they are added here.
    if (note) lines.push(...wrapLine(note, width - 2).map((text): FormLine => ({ text: `  ${text}`, style: "command" })));
    return lines;
  }

  /**
   * The options as rows that fit in `room` rows (S1): all of them when they fit, else a window
   * around the selected row (visibleStart, keeping its start while the selection stays in view)
   * with `↑ n more` and `↓ n more` markers.
   */
  private optionLines(room: number): FormLine[] {
    const options = this.shownOptions();
    this.selected = Math.min(this.selected, Math.max(0, options.length - 1));
    const row = (option: FormOption, index: number): FormLine => {
      const chosen = index === this.selected;
      return { text: `${chosen ? "›" : " "} ${option.label}`, style: chosen ? "selected" : "option" };
    };
    if (options.length <= room) {
      this.listStart = 0;
      return options.map(row);
    }
    const height = Math.max(1, room - MARKER_ROWS);
    const start = visibleStart(options.length, this.selected, height, this.listStart);
    this.listStart = start;
    const lines: FormLine[] = [];
    if (start > 0) lines.push({ text: `  ↑ ${start} more`, style: "more" });
    lines.push(...options.slice(start, start + height).map((option, offset) => row(option, start + offset)));
    const below = options.length - start - height;
    if (below > 0) lines.push({ text: `  ↓ ${below} more`, style: "more" });
    return lines;
  }

  private shown(input: CatalogInput): string {
    const value = this.answers[input.id];
    if (typeof value === "boolean") return value ? "Yes" : "No";
    if (input.choices) return input.choices.find((choice) => choice.value === value)?.label ?? value;
    if (value) return value;
    if (input.kind === "text") return typeof input.default === "string" && input.default ? `${input.default} (default)` : "(default)";
    return NONE_OPTION;
  }

  /**
   * The form's lines at `width` columns. With `room` (the rows it may use), a long list is a window
   * so the header, the answers, the question and the command lines stay visible.
   */
  lines(width: number, room = Number.POSITIVE_INFINITY): FormLine[] {
    const lines: FormLine[] = this.spec.header.split("\n").map((text) => ({ text, style: "header" }));
    lines.push({ text: "", style: "plain" });
    for (const input of this.spec.action.inputs.slice(0, this.step)) {
      lines.push({ text: `${input.label}: ${this.shown(input)}`, style: "answer" });
      const warning = input.choices?.find((choice) => choice.value === this.answers[input.id])?.warning;
      if (warning) lines.push({ text: `  warning: ${warning}`, style: "warning" });
    }
    if (!this.finished) {
      const input = this.input;
      if (!input) {
        const warning = noDatabaseWarning(this.spec.catalog, this.spec.action, this.answers);
        if (warning) lines.push({ text: warning, style: "warning" });
        lines.push({ text: "Run this command?", style: "question" });
      } else {
        lines.push({ text: input.hint ? `${input.label} (${input.hint})` : input.label, style: "question" });
      }
      if (this.typing) {
        lines.push({ text: `> ${this.buffer}`, style: "typed" });
        if (this.error) lines.push({ text: `! ${this.error}`, style: "error" });
      } else {
        if (this.filter) {
          lines.push({ text: `filter: ${this.filter}`, style: "typed" });
          if (!this.shownOptions().some((option) => !option.keep)) lines.push({ text: NO_MATCH, style: "more" });
        }
        const bottom = 1 + this.commandLines(width).length;
        lines.push(...this.optionLines(room - lines.length - bottom));
      }
    }
    lines.push({ text: "", style: "plain" });
    lines.push(...this.commandLines(width));
    return lines;
  }
}
