// Classify bash commands that bypass the oasis guards (the deny tier) or that the user confirms
// first (the ask tier, see AskAction). No Pi imports: the extension injects the session's
// directory, home and a file check (GuardContext).
// Only programs in command position count, so searching or printing their
// names stays allowed. This is a guard rail for agents, not a sandbox.
import { posix } from "node:path";
import { COMMANDS, findEntry, operationOf, policyEntry, type PolicyEntry, PROGRAMS, stricter, tierOf } from "./policy.ts";

// The tiers come from the core policy table (tools/policy.py, see lib/policy.ts): a Tier C program or
// oasis command is denied, a Tier B one asks, a Tier A one runs.
const BLOCKED = new Set([...PROGRAMS].filter((program) => tierOf(program) !== "A"));
// worktree-init's scripts count in any directory (unchanged).
export const WORKTREE_INIT = "worktree-init";
const WORKTREE_INIT_SCRIPTS = new Set([WORKTREE_INIT, "worktree_init.py"]);
// create-database's Python scripts create the database themselves (v0.20.0 L19): in any directory, with any
// arguments, they ask like create-database (its Tier B row, never its plan's or dry run's).
export const CREATE_DATABASE = "create-database";
const CREATE_DATABASE_SCRIPTS = new Set(["dev_users.py", "dev_users_runtime.py"]);
// The interactive action menu (its catalog included) is for the user, in a terminal or the Gentle
// Shell panel; agents run the commands it lists directly.
export const MENU = "menu";
// Its scripts are blocked by what they are, not by their spelling: `tools/menu` and
// `tools/actions.py` are common names in other projects, and the menu itself refuses to run
// without a terminal. With a GuardContext, a script word is resolved against the session's
// directory and the literal `cd`/`pushd` targets before it in the same command, and blocked when
// it is an oasis menu script (see menuScript). Without one, only the installed bundle's spelling
// counts (MENU_SCRIPT).
const MENU_NAMES = new Set([MENU, "actions.py"]);
// The other oasis tool scripts, recognized like the menu's (see oasisScript): `stop`, `gc`, `setup`
// and `setup.py` are common names too.
const SCRIPT_NAMES = new Set([...COMMANDS, "setup.py"]);
// A managed database name as the tools accept it; anything else is not known from the text.
const DATABASE_NAME = /^[A-Za-z0-9_]+$/;
// Expansion, globs or substitution leftovers: the word's path is not known from the text. A bare
// `_` is what substitutions() leaves for `$(...)` and backticks.
const NOT_LITERAL = /[$*?[\]{}`\\]/;
const CHANGE_DIRECTORY = new Set(["cd", "pushd"]);

/**
 * Where the session runs, from the extension: its cwd, the home directory and a file check.
 * `settingFile` names the file that holds [tooling].agent_destructive a bash write reaches: called
 * with the write target's absolute path, or null when the text does not tell it, and the word as
 * written; it returns the file to name in the dialog, or null when the target is not such a file.
 * Without it, no write is an ask command.
 */
export interface GuardContext {
  cwd: string;
  home: string;
  exists(path: string): boolean;
  settingFile?(path: string | null, word: string): string | null;
}

/**
 * The session context and the directory the next command runs in (null when unknown). `unsure`: the
 * command is in a substitution of a line that changes directory, so `dir` may not be where it runs.
 */
interface Where {
  context: GuardContext;
  dir: string | null;
  unsure?: boolean;
}
// The entry point (v0.21.0 S6: only this name).
const ENTRY_POINTS = new Set(["oasis"]);
// The installed bundle's tools directory.
const BUNDLE_TOOLS = ["skills/oasis/tools"];
const SHELLS = new Set(["bash", "sh", "zsh", "dash"]);
// Programs that run what they read from a heredoc; its body is then classified as commands.
const HEREDOC_SHELLS = new Set([...SHELLS, "ksh", "mksh", "ash", "fish", "csh", "tcsh"]);
const HEREDOC_READERS = new Set([...HEREDOC_SHELLS, "source", ".", "eval", "ssh", "su"]);
const HELP_FLAGS = new Set(["--help", "-h"]);
const REDIRECTION = /^\d*[<>]/;
// A path bash passes as written: no expansion, substitution or glob.
const LITERAL_PATH = /^\/[A-Za-z0-9_.\/-]*$/;
const ASSIGNMENT = /^[A-Za-z_][A-Za-z0-9_]*=/;
// Reserved words that precede a command inside compound commands.
const KEYWORDS = new Set(["if", "then", "else", "elif", "while", "until", "do", "!"]);
// A short-option cluster that includes -c, e.g. -c, -lc, -ec.
const SHELL_COMMAND_FLAG = /^-[A-Za-z]*c[A-Za-z]*$/;
// Wrappers that run the next word as the command, with options that take a value.
const WRAPPERS: Record<string, Set<string>> = {
  sudo: new Set(["-u", "-g", "-h", "-p", "-C", "-D", "-U", "--user", "--group", "--chdir"]),
  env: new Set(["-u", "-C", "--unset", "--chdir"]),
  time: new Set(),
  nohup: new Set(),
  exec: new Set(["-a"]),
  command: new Set(),
  nice: new Set(["-n"]),
  timeout: new Set(["-s", "-k", "--signal", "--kill-after"]),
  xargs: new Set(["-I", "-n", "-P", "-d", "-L", "-s", "-E"]),
  watch: new Set(["-n", "--interval", "-d", "--differences"]),
  setsid: new Set(),
  stdbuf: new Set(["-i", "-o", "-e"]),
  ionice: new Set(["-c", "-n", "-p"]),
  doas: new Set(["-u", "-C"]),
};
// The wrapper options that run the command in another directory (`env -C <dir>`, `sudo -D <dir>`).
const CHANGE_DIRECTORY_OPTIONS: Record<string, { short: string; long: string }> = {
  env: { short: "-C", long: "--chdir" },
  sudo: { short: "-D", long: "--chdir" },
};
const DOCKER_VALUE_OPTIONS = new Set([
  "-f", "--file", "-p", "--project-name", "--project-directory", "--env-file", "--profile",
  "-u", "--user", "-w", "--workdir", "-e", "--env", "--index",
]);
const PYTHON_VALUE_OPTIONS = new Set(["-X", "-W", "-c", "-m"]);

function basename(word: string): string {
  return word.slice(word.lastIndexOf("/") + 1);
}

/** The absolute path a word names, or null when it depends on expansion or an unknown directory. */
function literalPath(word: string, where: Where): string | null {
  if (word === "_" || NOT_LITERAL.test(word)) return null;
  let path = word;
  if (path === "~" || path.startsWith("~/")) path = where.context.home + path.slice(1);
  else if (path.startsWith("~")) return null; // ~user
  if (!path.startsWith("/")) {
    if (where.dir === null) return null;
    path = posix.join(where.dir, path);
  }
  return posix.normalize(path);
}

/** Whether dir holds an oasis tree: the `oasis` entry point and `tools/actions.py`. */
function oasisTree(dir: string, context: GuardContext): boolean {
  return context.exists(posix.join(dir, "oasis")) && context.exists(posix.join(dir, "tools/actions.py"));
}

function insideOasisTree(dir: string, context: GuardContext): boolean {
  for (let current = posix.normalize(dir); ; current = posix.dirname(current)) {
    if (oasisTree(current, context)) return true;
    if (current === posix.dirname(current)) return false;
  }
}

/** Whether a word ends in `<directory>/<its name>`, or is exactly that. */
function spelledIn(word: string, directory: string): boolean {
  const tail = `${directory}/${basename(word)}`;
  return word === tail || word.endsWith(`/${tail}`);
}

/**
 * Whether a word names one of oasis's tool scripts `names` (the menu's `menu` or `actions.py`, or
 * an ask command's). Resolved to a file, it must sit in a `tools` directory whose parent is an
 * oasis tree. When its path is unknown (expansion, an unknown `cd` target), it counts when spelled
 * like the installed bundle (`.../skills/oasis/tools/menu`) or, spelled `tools/<name>`, when the
 * session works inside an oasis tree. Without a context, only the installed bundle's spelling counts.
 */
function oasisScript(word: string, names: Set<string>, where: Where | undefined): boolean {
  if (!names.has(basename(word))) return false;
  // The installed bundle's spelling counts from anywhere, as before the session context,
  // also when the rest of the path is an expansion (`$HOME/...`, `${HOME}/...`).
  const bundled = BUNDLE_TOOLS.some((directory) => spelledIn(word, directory));
  if (bundled || !where) return bundled;
  const path = literalPath(word, where);
  if (path === null) return spelledIn(word, "tools") && insideOasisTree(where.context.cwd, where.context);
  const tools = posix.dirname(path);
  return posix.basename(tools) === "tools" && oasisTree(posix.dirname(tools), where.context);
}

function menuScript(word: string, where: Where | undefined): boolean {
  return oasisScript(word, MENU_NAMES, where);
}

/**
 * The directory after a `cd`/`pushd` segment: the literal target resolved from the current one,
 * home without a target, null (unknown) for `-`, `+N` or anything expanded.
 */
function changedDirectory(args: string[], where: Where): string | null {
  const rest = args.filter((word) => !REDIRECTION.test(word));
  let i = 0;
  while (i < rest.length && /^-[LPe@]+$/.test(rest[i])) i++;
  if (rest[i] === "--") i++;
  const target = rest[i];
  if (target === undefined) return where.context.home;
  if (target === "-" || /^[+-]\d+$/.test(target)) return null;
  return literalPath(target, where);
}
/**
 * Whether a `#` at `index` starts a comment: at the start of a word, which an escaped character
 * (`a\ #b`, with the escaped one at `escapedAt`) does not begin.
 */
function startsComment(text: string, index: number, escapedAt: number): boolean {
  return index === 0 || (escapedAt !== index - 1 && /[\s;&|(]/.test(text[index - 1]));
}

/**
 * Pull out $(...) and `...` bodies so they are classified as commands too. With `quotes`, text
 * inside single quotes is left alone, as bash does; heredoc bodies pass `quotes = false`, because
 * quotes are literal there.
 */
function substitutions(command: string, quotes = true): { outer: string; inner: string[] } {
  const inner: string[] = [];
  let outer = "";
  let inDouble = false;
  let escapedAt = -1;
  for (let i = 0; i < command.length; i++) {
    const c = command[i];
    if (quotes && c === "\\" && i + 1 < command.length) {
      outer += c + command[++i];
      escapedAt = i;
    } else if (quotes && !inDouble && c === "#" && startsComment(command, i, escapedAt)) {
      // A comment runs to the end of the line; quotes inside it mean nothing.
      const end = command.indexOf("\n", i);
      i = (end < 0 ? command.length : end) - 1;
    } else if (quotes && !inDouble && c === "$" && command[i + 1] === "'") {
      // ANSI-C quoting: $'...' with backslash escapes.
      let j = i + 2;
      while (j < command.length && command[j] !== "'") j += command[j] === "\\" ? 2 : 1;
      outer += command.slice(i, j + 1);
      i = j;
    } else if (quotes && c === '"') {
      inDouble = !inDouble;
      outer += c;
    } else if (quotes && c === "'" && !inDouble) {
      const end = command.indexOf("'", i + 1);
      const stop = end < 0 ? command.length - 1 : end;
      outer += command.slice(i, stop + 1);
      i = stop;
    } else if (c === "$" && command[i + 1] === "(") {
      let depth = 1;
      let j = i + 2;
      for (; j < command.length && depth; j++) {
        if (command[j] === "(") depth++;
        else if (command[j] === ")") depth--;
      }
      inner.push(command.slice(i + 2, j - 1));
      outer += " _ ";
      i = j - 1;
    } else if (c === "`") {
      const end = command.indexOf("`", i + 1);
      const stop = end < 0 ? command.length : end;
      inner.push(command.slice(i + 1, stop));
      outer += " _ ";
      i = stop;
    } else {
      outer += c;
    }
  }
  return { outer, inner };
}

interface Heredoc {
  delimiter: string;
  stripTabs: boolean;
  quoted: boolean;
}

/** The heredocs a line opens, ignoring `<<` inside quotes and here-strings (`<<<`). */
function heredocsOpened(line: string): Heredoc[] {
  const found: Heredoc[] = [];
  let quote = "";
  let escapedAt = -1;
  for (let i = 0; i < line.length; i++) {
    const c = line[i];
    if (quote) {
      if (c === quote) quote = "";
      else if (c === "\\" && quote === '"') i++;
    } else if (c === "'" || c === '"') {
      quote = c;
    } else if (c === "\\") {
      escapedAt = ++i;
    } else if (c === "#" && startsComment(line, i, escapedAt)) {
      break; // the rest of the line is a comment
    } else if (c === "<" && line[i + 1] === "<" && line[i + 2] !== "<" && line[i - 1] !== "<") {
      const match = /^<<(-?)\s*(\\?)(['"]?)([A-Za-z_][A-Za-z0-9_]*)\3/.exec(line.slice(i));
      if (match) {
        found.push({ delimiter: match[4], stripTabs: match[1] === "-", quoted: Boolean(match[2] || match[3]) });
        i += match[0].length - 1;
      }
    }
  }
  return found;
}

/**
 * Whether a command on the heredoc's opening line runs what it reads (`bash <<EOF`,
 * `cat <<EOF | sh`, `docker exec db sh <<EOF`). Only words in command position count, so
 * `git add . && git commit -F - <<EOF` does not. A shell name counts as any whole word, since
 * wrappers this guard does not know also run it (`kubectl exec pod -- sh <<EOF`). Any command on
 * the line counts, not only the one the heredoc is attached to: the check errs towards
 * classifying the body.
 */
function readsCommands(opener: string): boolean {
  return segments(opener).some((segment) => {
    // `bash<<EOF` is one word here; redirections are not part of the command.
    const words = segment.map((word) => word.split(/[<>]/)[0]).filter(Boolean);
    if (words.some((word) => HEREDOC_SHELLS.has(basename(word)))) return true;
    let i = 0;
    for (;;) {
      while (i < words.length && (ASSIGNMENT.test(words[i]) || KEYWORDS.has(words[i]))) i++;
      if (i >= words.length) return false;
      // xargs runs its input lines as arguments of any command, or as the command itself.
      if (basename(words[i]) === "xargs") return true;
      const next = unwrap(words, i);
      if (next === undefined) return HEREDOC_READERS.has(basename(words[i]));
      if (next === null) return false;
      i = next;
    }
  });
}

/**
 * Separate heredoc bodies from commands. A body is data unless a command on its opening line runs
 * what it reads (see readsCommands): then it stays in `text` and is classified as commands. The
 * opening line includes the lines it continues and the lines that continue it (`\` + newline;
 * the body starts after them) and, after a trailing `|`, the line that follows the body. `data` holds the bodies of unquoted heredocs, where bash still
 * runs substitutions. An unterminated heredoc is left as commands.
 */
function heredocs(command: string): { text: string; data: string[] } {
  const lines = command.split("\n");
  const text: string[] = [];
  const data: string[] = [];
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    text.push(line);
    let opener = line;
    for (let k = i - 1; k >= 0 && lines[k].endsWith("\\"); k--) opener = `${lines[k].slice(0, -1)} ${opener}`;
    const opened = heredocsOpened(line);
    // Lines that continue the opening line come before the body.
    while (opened.length > 0 && lines[i].endsWith("\\") && i + 1 < lines.length) {
      opener = `${opener.slice(0, -1)} ${lines[++i]}`;
      text.push(lines[i]);
    }
    for (const heredoc of opened) {
      const matches = (candidate: string) =>
        (heredoc.stripTabs ? candidate.replace(/^\t+/, "") : candidate) === heredoc.delimiter;
      const end = lines.findIndex((candidate, index) => index > i && matches(candidate));
      if (end < 0) break;
      const body = lines.slice(i + 1, end);
      const piped = /\|\s*$/.test(opener) ? ` ${lines[end + 1] ?? ""}` : "";
      if (readsCommands(opener + piped)) text.push(...body);
      else if (!heredoc.quoted) data.push(body.join("\n"));
      i = end;
    }
  }
  return { text: text.join("\n"), data };
}

/** Split into simple commands (word lists), honoring quotes and control operators. */
function segments(command: string): string[][] {
  const result: string[][] = [];
  let words: string[] = [];
  let word = "";
  let inWord = false;
  const endWord = () => {
    if (inWord) words.push(word);
    word = "";
    inWord = false;
  };
  const endSegment = () => {
    endWord();
    if (words.length) result.push(words);
    words = [];
  };
  for (let i = 0; i < command.length; i++) {
    const c = command[i];
    if (c === "'" || c === '"') {
      const end = command.indexOf(c, i + 1);
      const stop = end < 0 ? command.length : end;
      word += command.slice(i + 1, stop);
      inWord = true;
      i = stop;
    } else if (c === "\\" && i + 1 < command.length) {
      word += command[++i];
      inWord = true;
    } else if (";&|\n(){}".includes(c)) {
      endSegment();
    } else if (c === " " || c === "\t") {
      endWord();
    } else {
      word += c;
      inWord = true;
    }
  }
  endSegment();
  return result;
}

function skipOptions(words: string[], index: number, valueOptions: Set<string>): number {
  while (index < words.length && words[index].startsWith("-")) {
    const option = words[index];
    index += valueOptions.has(option) && !option.includes("=") ? 2 : 1;
  }
  return index;
}

/**
 * Whether a word is the entry point's --project option without its value: argparse also takes an
 * unambiguous prefix of it (`--p` to `--project`; its other option is --help).
 */
function projectOption(word: string): boolean {
  return word.length >= 3 && "--project".startsWith(word);
}

/** Whether a word is the entry point's --help as argparse takes it: `-h`, or a prefix of `--help` from `--h`. */
function helpOption(word: string): boolean {
  return word === "-h" || (word.length >= 3 && "--help".startsWith(word));
}

/**
 * The entry point's options before its command: the index of the command (the first word after
 * them; --project and its prefixes take a value, `--project=<dir>` holds it), the --project value
 * argparse keeps (the last one given), undefined without one, and whether an option the entry point
 * does not have came before the command (`unknown`: argparse refuses that line, and which word it
 * would run is not known from the text).
 */
function entryPointOptions(
  words: string[], index: number,
): { command: number; project?: string; joined: boolean; unknown: boolean } {
  let i = index + 1;
  let project: string | undefined;
  let joined = false;
  let unknown = false;
  while (i < words.length && words[i].startsWith("-")) {
    const word = words[i];
    const equals = word.indexOf("=");
    if (equals > 0 && projectOption(word.slice(0, equals))) {
      project = word.slice(equals + 1);
      joined = true;
      i += 1;
    } else if (projectOption(word)) {
      project = words[i + 1];
      joined = false;
      i += 2;
    } else {
      if (word !== "--" && !helpOption(word)) unknown = true;
      i += 1;
    }
  }
  return { command: i, project, joined, unknown };
}

/**
 * The strictest row of any oasis command word among an entry point's words (its options and
 * arguments), or null without one: what a line runs when its command word is not known.
 */
function strictestPresent(words: string[]): PolicyEntry | null {
  let found: PolicyEntry | null = null;
  for (const word of words) {
    const entry = COMMANDS.has(word) ? operationOf(word, [], false) : null;
    if (entry) found = found ? stricter(found, entry) : entry;
  }
  return found;
}

/** Whether the arguments only ask for help: one help flag, redirections aside. */
function onlyHelp(args: string[]): boolean {
  const rest = args.filter((word) => !REDIRECTION.test(word));
  return rest.length === 1 && HELP_FLAGS.has(rest[0]);
}

/** Whether every argument is literal: none can expand to another option. Redirections aside. */
function literalArguments(args: string[]): boolean {
  return args.filter((word) => !REDIRECTION.test(word)).every((word) => word !== "_" && !NOT_LITERAL.test(word));
}

/**
 * The oasis command a script word runs, or null: worktree-init's scripts anywhere, the menu's and
 * every other tool script's only when they are an oasis tree's or
 * spelled like the installed bundle (see oasisScript), since the names are common.
 */
function scriptCommand(word: string, where: Where | undefined): string | null {
  const name = basename(word);
  if (WORKTREE_INIT_SCRIPTS.has(name)) return WORKTREE_INIT;
  if (CREATE_DATABASE_SCRIPTS.has(name)) return CREATE_DATABASE;
  if (menuScript(word, where)) return MENU;
  if (oasisScript(word, SCRIPT_NAMES, where)) return name === "setup.py" ? "setup" : name;
  return null;
}

/**
 * An ask-tier command, a Tier B operation of the policy table (drop-database, gc --apply --trash,
 * worktree-init, ...; `command` is the operation): the user confirms it before it
 * runs (the extension's dialog), unless the project's `[tooling].agent_destructive` says otherwise.
 * `database` is drop-database's first argument when it is a literal database name, else null (the
 * user could not confirm it).
 */
export type AskAction =
  | ({ command: "drop-database"; database: string | null } & Target)
  | ({ command: string } & Target)
  | { command: "edit"; file: string };

/**
 * The project an ask command names (see targetOf): an absolute path, null when the text does not
 * tell it (an expansion, an unknown directory), absent when the command names none or runs the
 * entry point without --project in the session's own directory (the session's project applies).
 */
export interface Target {
  project?: string | null;
}

// The variable a tool script reads its project root from (tools/oasis_env.sh oasis_variable), when it is not empty.
const ROOT_VARIABLE = "OASIS_PROJECT_ROOT";

/** A target path as written: absolute (normalized), or null when the text does not tell it. */
function targetPath(value: string, where: Where | undefined, tilde: boolean): string | null {
  // ` _ ` is what substitutions() leaves of `$(...)` inside quotes.
  if ((!tilde && value.startsWith("~")) || /(^|\s)_(\s|$)/.test(value)) return null;
  if (where) return literalPath(value, where);
  return LITERAL_PATH.test(value) ? posix.normalize(value) : null;
}

/**
 * The project the ask command at words[index] targets: the entry point's --project value, or the
 * root variable a tool script gets from the assignments before it (`VAR=<dir> tool`, `env VAR=<dir>
 * tool`; the last one counts). Bash expands `~` in an assignment, not in `--project=~`.
 * Without --project the entry point takes the git top level of the directory it runs in (v0.14.0
 * S8): that directory after a literal `cd` or `env -C`, null when it is not known, absent when it is
 * the session's own directory.
 */
function targetOf(words: string[], index: number, where: Where | undefined): Target {
  if (ENTRY_POINTS.has(basename(words[index]))) {
    const { project, joined } = entryPointOptions(words, index);
    if (project !== undefined) return { project: targetPath(project, where, !joined) };
    if (!where) return {};
    if (where.unsure || where.dir === null) return { project: null };
    return where.dir === posix.normalize(where.context.cwd) ? {} : { project: where.dir };
  }
  let value: string | undefined;
  for (const word of words.slice(0, index)) {
    const equals = word.indexOf("=");
    if (ASSIGNMENT.test(word) && word.slice(0, equals) === ROOT_VARIABLE) value = word.slice(equals + 1);
  }
  return value === undefined || value === "" ? {} : { project: targetPath(value, where, true) };
}

/** What a simple command runs: a denied program, or an ask command. */
type Finding = { program: string } | { ask: AskAction };

/**
 * What the oasis command words[index] runs (through an entry point or its tool script) is, by its
 * tier in the policy table (see operationOf): nothing (A), an ask command (B) or a denied program
 * (C, the operation). Asking only for help (`--help` or `-h` as the single argument) runs nothing.
 */
function toolFinding(words: string[], index: number, where?: Where): Finding[] {
  let tool: string | null | undefined;
  let args: string[];
  // The entry point's command word is not known from the text: an option it does not have before it,
  // or a word that is not literal or not a command of the table. Then the strictest row of any
  // command word on the line applies (`oasis --x y worktree-init f b` asks), none without one.
  let undetermined = false;
  if (ENTRY_POINTS.has(basename(words[index]))) {
    const { command, unknown } = entryPointOptions(words, index);
    tool = words[command];
    args = words.slice(command + 1);
    undetermined = tool !== undefined && (unknown || NOT_LITERAL.test(tool) || tool === "_" || !COMMANDS.has(tool));
  } else {
    tool = scriptCommand(words[index], where);
    args = words.slice(index + 1);
  }
  const rest = args.filter((arg) => !REDIRECTION.test(arg));
  // create-database's Python scripts have no plan, dry run or help of their own: always its Tier B row.
  const creating = !ENTRY_POINTS.has(basename(words[index])) && CREATE_DATABASE_SCRIPTS.has(basename(words[index]));
  if (!tool || (!undetermined && !creating && onlyHelp(rest))) return [];
  const entry = creating
    ? policyEntry(CREATE_DATABASE)
    : undetermined
    ? strictestPresent(words.slice(index + 1).filter((word) => !REDIRECTION.test(word)))
    : operationOf(tool, rest, literalArguments(rest));
  if (entry === null || entry.tier === "A") return [];
  if (entry.tier === "C") return [{ program: entry.operation }];
  const target = targetOf(words, index, where);
  if (entry.operation === "drop-database") {
    const database = undetermined ? undefined : rest[0];
    return [{ ask: { command: entry.operation, database: database !== undefined && DATABASE_NAME.test(database) ? database : null, ...target } }];
  }
  return [{ ask: { command: entry.operation, ...target } }];
}

// The policy table's operation of a write to a setting file (GuardContext.settingFile).
const EDIT_SETTING = "edit a setting file";

// A redirection to a file: `>`, `>>`, `2>`, `&>` (segments() leaves `>` of `&>` and `>|`), with
// its target in the word or, when bare, in the next word. `>&2` duplicates a descriptor instead.
const OUTPUT_REDIRECTION = /^\d*>>?(.*)$/;

/** The words a simple command writes through redirections, and the command's other words. */
function redirections(words: string[]): { targets: string[]; rest: string[] } {
  const targets: string[] = [];
  const rest: string[] = [];
  for (let k = 0; k < words.length; k++) {
    const match = OUTPUT_REDIRECTION.exec(words[k]);
    if (!match) {
      // An input redirection (`<`, `<<<`) reads its target, which is not the command's word either.
      if (/^\d*<+$/.test(words[k])) k++;
      else if (!REDIRECTION.test(words[k])) rest.push(words[k]);
      continue;
    }
    const target = match[1].replace(/^\|/, "");
    if (target === "" && match[1] === "") {
      if (k + 1 < words.length) targets.push(words[++k]);
    } else if (!target.startsWith("&")) {
      targets.push(target);
    }
  }
  return { targets, rest };
}

/** The operands of a command (its words that are not options; all of them after `--`). */
function operands(args: string[]): string[] {
  const end = args.indexOf("--");
  const before = (end < 0 ? args : args.slice(0, end)).filter((word) => !word.startsWith("-"));
  return end < 0 ? before : [...before, ...args.slice(end + 1)];
}

/** The files `tee`, `sed -i`, `mv` and `cp` at words[index] write (as words). */
function writtenFiles(words: string[], index: number): string[] {
  const name = basename(words[index]);
  const args = words.slice(index + 1);
  if (name === "tee") return operands(args);
  if (name === "sed") {
    const inPlace = args.some((word) => /^-[A-Za-z]*i/.test(word) || word.startsWith("--in-place"));
    return inPlace ? operands(args) : [];
  }
  if (name !== "mv" && name !== "cp") return [];
  let target: string | undefined;
  const rest: string[] = [];
  for (let k = 0; k < args.length; k++) {
    const word = args[k];
    if (word === "-t" || word === "--target-directory") target = args[++k];
    else if (word.startsWith("--target-directory=")) target = word.slice("--target-directory=".length);
    else if (/^-t./.test(word)) target = word.slice(2);
    else rest.push(word);
  }
  const files = operands(rest);
  const destination = target ?? files.pop();
  if (destination === undefined) return [];
  // Onto the destination, or into it when it is a directory.
  return [destination, ...files.map((source) => `${destination.replace(/\/+$/, "")}/${basename(source)}`)];
}

/**
 * The setting files (GuardContext.settingFile) one simple command writes: through its
 * redirections, or as `tee`, `sed -i`, `mv` or `cp`, also behind wrappers. `carried` is a target
 * the previous segment's bare redirection left (`>|`: segments() splits at the `|`).
 */
function settingWrites(words: string[], where: Where | undefined, carried: string | undefined): Finding[] {
  const settingFile = where?.context.settingFile;
  if (!where || !settingFile) return [];
  const { targets, rest } = redirections(words);
  if (carried !== undefined) targets.unshift(carried);
  let i = 0;
  for (;;) {
    while (i < rest.length && (ASSIGNMENT.test(rest[i]) || KEYWORDS.has(rest[i]))) i++;
    if (i >= rest.length) break;
    const next = unwrap(rest, i);
    if (next === undefined) targets.push(...writtenFiles(rest, i));
    if (typeof next !== "number") break;
    i = next;
  }
  const found: Finding[] = [];
  for (const word of targets) {
    const file = settingFile(literalPath(word, where), word);
    if (file === null) continue;
    // Tier B in the policy table: the dialog, which agent_destructive = allow never skips (lib/destructive.ts).
    const tier = tierOf(EDIT_SETTING);
    if (tier === "B") found.push({ ask: { command: "edit", file } });
    else if (tier === "C") found.push({ program: EDIT_SETTING });
  }
  return found;
}

/**
 * The index of the command a wrapper at words[index] runs (`sudo -u x cmd`, `docker exec db cmd`):
 * undefined when words[index] is not a wrapper, null when it runs no further command.
 */
function unwrap(words: string[], index: number): number | null | undefined {
  const name = basename(words[index]);
  const wrapper = WRAPPERS[name];
  if (wrapper) {
    const next = skipOptions(words, index + 1, wrapper);
    return name === "timeout" && next < words.length ? next + 1 : next; // the duration
  }
  if (name !== "docker") return undefined;
  let i = skipOptions(words, index + 1, DOCKER_VALUE_OPTIONS);
  if (words[i] === "compose") i = skipOptions(words, i + 1, DOCKER_VALUE_OPTIONS);
  if (words[i] !== "exec" && words[i] !== "run") return null;
  return skipOptions(words, i + 1, DOCKER_VALUE_OPTIONS) + 1; // the service or container
}

/**
 * The directory the command after a wrapper's options (words[index + 1] to words[next - 1]) runs in:
 * the literal `env -C`/`--chdir` or `sudo -D`/`--chdir` value resolved from where, null when not
 * literal, undefined when the wrapper does not change it.
 */
function wrapperDirectory(words: string[], index: number, next: number, where: Where): string | null | undefined {
  const option = CHANGE_DIRECTORY_OPTIONS[basename(words[index])];
  if (!option) return undefined;
  let value: string | undefined;
  for (let k = index + 1; k < next; k++) {
    const word = words[k];
    if (word === option.short || word === option.long) value = words[++k] ?? "";
    else if (word.startsWith(`${option.long}=`)) value = word.slice(option.long.length + 1);
    else if (word.startsWith(option.short) && !word.startsWith("--")) value = word.slice(option.short.length);
  }
  return value === undefined ? undefined : literalPath(value, where);
}

/** What one simple command runs: at most one finding, or the findings of a command it runs (eval, sh -c). */
function classifySegment(words: string[], start?: Where): Finding[] {
  let where = start;
  let i = 0;
  for (;;) {
    while (i < words.length && (ASSIGNMENT.test(words[i]) || KEYWORDS.has(words[i]))) i++;
    if (i >= words.length) return [];
    const name = basename(words[i]);
    // `command -v/-V` only looks the program up.
    if (name === "command" && words.slice(i + 1).some((w) => w === "-v" || w === "-V")) return [];
    if (name === "eval") return findingsIn(words.slice(i + 1).join(" "), where);
    if ((name === "source" || name === ".") && i + 1 < words.length) {
      const sourced = basename(words[i + 1]);
      return BLOCKED.has(sourced) ? [{ program: sourced }] : [];
    }
    if (name === "find") {
      const exec = words.findIndex((w, k) => k > i && (w === "-exec" || w === "-execdir" || w === "-ok"));
      return exec > 0 ? classifySegment(words.slice(exec + 1), where) : [];
    }
    const next = unwrap(words, i);
    if (next === null) return [];
    if (next !== undefined) {
      const moved = where ? wrapperDirectory(words, i, next, where) : undefined;
      if (where && moved !== undefined) where = { ...where, dir: moved };
      i = next;
      continue;
    }
    if (BLOCKED.has(name)) return [{ program: name }];
    const found = toolFinding(words, i, where);
    if (found.length) return found;
    if (/^python[\d.]*$/.test(name)) {
      const target = skipOptions(words, i + 1, PYTHON_VALUE_OPTIONS);
      if (words.slice(i + 1, target).some((w) => w === "-c" || w === "-m")) return [];
      if (target >= words.length) return [];
      if (basename(words[target]) === "odoo-bin") return [{ program: "odoo-bin" }];
      return toolFinding(words, target, where);
    }
    if (SHELLS.has(name)) {
      const flag = words.findIndex((w, k) => k > i && SHELL_COMMAND_FLAG.test(w));
      if (flag > 0) return flag + 1 < words.length ? findingsIn(words[flag + 1], where) : [];
      const script = skipOptions(words, i + 1, new Set());
      return script < words.length ? toolFinding(words, script, where) : [];
    }
    return [];
  }
}

/**
 * Whether a blocked program is the user's in every session (a Tier C oasis command, such as the
 * interactive menu); the programs outside oasis (odoo-bin, dropdb, psql) are blocked only in Odoo
 * projects, where they would bypass the database guards.
 */
export function blockedEverywhere(program: string): boolean {
  return !PROGRAMS.has(program);
}

/**
 * The blocked program a bash command would run directly, or null. With the session context, the
 * menu's scripts are judged by the file they resolve to (see menuScript).
 */
export function blockedProgram(command: string, context?: GuardContext): string | null {
  return classifyBash(command, context).program;
}

/**
 * The tiers of a bash command: `programs` are the denied programs it runs, in order, and `program`
 * the first of them (blockedProgram), or null; `asks` lists the ask commands it runs, in order, a
 * setting file once (see GuardContext.settingFile). Neither: allowed.
 */
export function classifyBash(
  command: string, context?: GuardContext,
): { program: string | null; programs: string[]; asks: AskAction[] } {
  const findings = findingsIn(command, context ? { context, dir: context.cwd } : undefined);
  const programs: string[] = [];
  const asks: AskAction[] = [];
  const edited = new Set<string>();
  for (const found of findings) {
    if (!("ask" in found)) programs.push(found.program);
    else if (found.ask.command !== "edit") asks.push(found.ask);
    else if (!edited.has(found.ask.file)) {
      edited.add(found.ask.file);
      asks.push(found.ask);
    }
  }
  return { program: programs[0] ?? null, programs, asks };
}

/** The index of the command words[] runs, after its assignments and reserved words. */
function commandIndex(words: string[]): number {
  let i = 0;
  while (i < words.length && (ASSIGNMENT.test(words[i]) || KEYWORDS.has(words[i]))) i++;
  return i;
}

// Commands that run cd, pushd or popd in the shell itself: they change its directory too.
const BUILTIN_RUNNERS = new Set(["builtin", "command", "time"]);
// Commands that run text or a file in the shell itself: it may change the directory.
const SHELL_RUNNERS = new Set(["eval", "source", "."]);

/** Whether a command word names no literal program: an expansion, a substitution or a glob. */
function unknownCommand(word: string): boolean {
  return /(^|\s)_(\s|$)/.test(word) || /[$`*?]/.test(word) || (word.includes("[") && word !== "[" && word !== "[[");
}

/**
 * Whether the simple command at words[index] may change the shell's directory in a way the text
 * does not tell, so later commands run in an unknown directory: `cd`, `pushd` or `popd` behind
 * `builtin`, `command` (not with its own `-v`/`-V`, which only look up) or `time`, with or
 * without `--`; `eval`, `source` and `.`, whatever they run; and a command word that is not
 * literal (`$CD /x`), which may be `cd`.
 */
function untrackedChange(words: string[], index: number): boolean {
  let i = index;
  let behind = false;
  while (i < words.length && BUILTIN_RUNNERS.has(words[i])) {
    const next = skipOptions(words, i + 1, new Set());
    // Its own options end at `--`; a -v after it, or after cd, is an argument (a directory `-v`).
    const options = words.slice(i + 1, next);
    const own = options.includes("--") ? options.slice(0, options.indexOf("--")) : options;
    if (words[i] === "command" && own.some((word) => /^-[A-Za-z]*[vV]/.test(word))) return false;
    i = next;
    behind = true;
  }
  const word = words[i];
  if (word === undefined) return false;
  if (behind && (CHANGE_DIRECTORY.has(word) || word === "popd")) return true;
  return SHELL_RUNNERS.has(word) || unknownCommand(word);
}

/** Every finding of a command in the order bash would reach it: substitutions first, then the segments. */
function findingsIn(command: string, start: Where | undefined): Finding[] {
  const findings: Finding[] = [];
  const { text, data } = heredocs(command);
  const { outer, inner } = substitutions(text);
  for (const body of data) inner.push(...substitutions(body, false).inner);
  const lines = segments(outer);
  // A substitution runs where its segment runs; on a line that changes directory that is not known here.
  const moves = lines.some((words) => {
    const word = words[commandIndex(words)] ?? "";
    return CHANGE_DIRECTORY.has(word) || word === "popd" || untrackedChange(words, commandIndex(words));
  });
  const substituted = start && moves ? { ...start, unsure: true } : start;
  for (const body of inner) findings.push(...findingsIn(body, substituted));
  let where = start;
  let carried: string | undefined;
  for (const words of lines) {
    // A bare `>` ending the previous segment writes to this one's first word (`>|`).
    const target = carried;
    carried = /^\d*>>?$/.test(words[words.length - 1]) ? "" : undefined;
    const own = target === undefined ? words : words.slice(1);
    // A literal `cd`/`pushd` moves the later segments; `popd` makes the directory unknown.
    const i = commandIndex(words);
    if (where && CHANGE_DIRECTORY.has(words[i] ?? "")) {
      where = { context: where.context, dir: changedDirectory(words.slice(i + 1), where), unsure: where.unsure };
      continue;
    }
    if (where && words[i] === "popd") {
      where = { context: where.context, dir: null, unsure: where.unsure };
      continue;
    }
    findings.push(...classifySegment(words, where), ...settingWrites(own, where, target === undefined ? undefined : words[0]));
    // After a change the text does not tell (`builtin cd`, `eval`, `source`, `$CD`), the directory is unknown.
    if (where && untrackedChange(words, i)) where = { context: where.context, dir: null, unsure: where.unsure };
  }
  return findings;
}

export function blockReason(program: string, root: string): string {
  if (program === MENU) {
    return (
      "menu is the user's interactive action menu; ask the user to run `oasis --project <root> menu` in a " +
      "terminal or to open the oasis panel in Gentle Shell."
    );
  }
  if (!PROGRAMS.has(program)) {
    const entry = findEntry(program);
    if (!entry) return `${program} is not in the oasis policy table (oasis policy --json); only the user runs it.`;
    return `${program} is Tier C in the oasis policy (only the user does it): ${entry.reason}.`;
  }
  return (
    `Direct ${program} is blocked in this Odoo project: it bypasses the database prefix guards. ` +
    `Use the oasis tools (oasis_test_module, oasis_module_status) or ` +
    `\`oasis --project ${root} <command>\` (test-module, update-module, install-module, odoo-shell, ` +
    `create-database, drop-database). If the user explicitly needs raw access, ask them to run it.`
  );
}
