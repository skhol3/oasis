// Classify bash commands that bypass the oasis guards. No Pi imports.
// Only programs in command position count, so searching or printing their
// names stays allowed. This is a guard rail for agents, not a sandbox.

const BLOCKED = new Set(["odoo-bin", "dropdb", "psql"]);
// User-run only: it links environment files that agents may not create or read.
export const WORKTREE_INIT = "worktree-init";
const WORKTREE_INIT_SCRIPTS = new Set([WORKTREE_INIT, "worktree_init.py"]);
// User-run only: it rewrites the project's configuration files (profiles, odoo.conf, lock.sha256).
export const MIGRATE = "migrate";
const MIGRATE_SCRIPTS = new Set([MIGRATE, "migrate.py"]);
// The entry point and its alias: worktree-init and migrate are blocked through either.
const ENTRY_POINTS = new Set(["oasis", "odoo19"]);
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
  sudo: new Set(["-u", "-g", "-h", "-p", "-C", "-D", "-U", "--user", "--group"]),
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
const DOCKER_VALUE_OPTIONS = new Set([
  "-f", "--file", "-p", "--project-name", "--project-directory", "--env-file", "--profile",
  "-u", "--user", "-w", "--workdir", "-e", "--env", "--index",
]);
const PYTHON_VALUE_OPTIONS = new Set(["-X", "-W", "-c", "-m"]);

function basename(word: string): string {
  return word.slice(word.lastIndexOf("/") + 1);
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

/** The entry point's command: the first word after its options (`--project <dir>` takes a value). */
function entryPointCommand(words: string[], index: number): string | undefined {
  let i = index + 1;
  while (i < words.length && words[i].startsWith("-")) i += words[i] === "--project" ? 2 : 1;
  return words[i];
}

/** Whether the arguments only ask for help: one help flag, redirections aside. */
function onlyHelp(args: string[]): boolean {
  const rest = args.filter((word) => !REDIRECTION.test(word));
  return rest.length === 1 && HELP_FLAGS.has(rest[0]);
}

/**
 * Whether the arguments only ask migrate for its plan: `--plan` once, optionally `--workspace` with
 * a literal absolute path, redirections to a file descriptor aside. The tool refuses `--plan` with
 * `--apply`, so this form cannot apply whatever the words expand to.
 */
function onlyPlan(args: string[]): boolean {
  const rest = args.filter((word) => !REDIRECTION.test(word));
  let plan = false;
  for (let i = 0; i < rest.length; i++) {
    const word = rest[i];
    if (word === "--plan" && !plan) plan = true;
    else if (word === "--workspace" && LITERAL_PATH.test(rest[i + 1] ?? "")) i++;
    else if (!(word.startsWith("--workspace=") && LITERAL_PATH.test(word.slice("--workspace=".length)))) return false;
  }
  return plan;
}

/** A user-run tool when words[index] runs it: its tool script, or an entry point with that command.
 * migrate's scripts count only inside a `tools` directory, since the name is common. Asking only
 * for its help (`--help` or `-h` as the single argument) runs nothing and is not blocked, and
 * neither is migrate's explicit plan (see onlyPlan). */
function userRunTool(words: string[], index: number): string | null {
  const word = words[index];
  const name = basename(word);
  const args = words.slice(index + 1);
  let tool: string | null = null;
  let toolArgs = args;
  if (WORKTREE_INIT_SCRIPTS.has(name)) tool = WORKTREE_INIT;
  else if (MIGRATE_SCRIPTS.has(name) && /(^|\/)tools\/[^/]+$/.test(word)) tool = MIGRATE;
  else if (ENTRY_POINTS.has(name)) {
    if (args.includes(WORKTREE_INIT)) tool = WORKTREE_INIT;
    else if (entryPointCommand(words, index) === MIGRATE) tool = MIGRATE;
    // The entry point's own `--project <dir>` and the command name are not the tool's arguments.
    const project = args.indexOf("--project");
    toolArgs = args.filter((arg, k) => arg !== tool && (project < 0 || (k !== project && k !== project + 1)));
  }
  if (!tool || onlyHelp(toolArgs) || (tool === MIGRATE && onlyPlan(toolArgs))) return null;
  return tool;
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

function classifySegment(words: string[]): string | null {
  let i = 0;
  for (;;) {
    while (i < words.length && (ASSIGNMENT.test(words[i]) || KEYWORDS.has(words[i]))) i++;
    if (i >= words.length) return null;
    const name = basename(words[i]);
    // `command -v/-V` only looks the program up.
    if (name === "command" && words.slice(i + 1).some((w) => w === "-v" || w === "-V")) return null;
    if (name === "eval") return blockedProgram(words.slice(i + 1).join(" "));
    if ((name === "source" || name === ".") && i + 1 < words.length) {
      const sourced = basename(words[i + 1]);
      return BLOCKED.has(sourced) ? sourced : null;
    }
    if (name === "find") {
      const exec = words.findIndex((w, k) => k > i && (w === "-exec" || w === "-execdir" || w === "-ok"));
      return exec > 0 ? classifySegment(words.slice(exec + 1)) : null;
    }
    const next = unwrap(words, i);
    if (next === null) return null;
    if (next !== undefined) {
      i = next;
      continue;
    }
    if (BLOCKED.has(name)) return name;
    const userRun = userRunTool(words, i);
    if (userRun) return userRun;
    if (/^python[\d.]*$/.test(name)) {
      const target = skipOptions(words, i + 1, PYTHON_VALUE_OPTIONS);
      if (words.slice(i + 1, target).some((w) => w === "-c" || w === "-m")) return null;
      if (target >= words.length) return null;
      if (basename(words[target]) === "odoo-bin") return "odoo-bin";
      return userRunTool(words, target);
    }
    if (SHELLS.has(name)) {
      const flag = words.findIndex((w, k) => k > i && SHELL_COMMAND_FLAG.test(w));
      if (flag > 0) return flag + 1 < words.length ? blockedProgram(words[flag + 1]) : null;
      const script = skipOptions(words, i + 1, new Set());
      return script < words.length ? userRunTool(words, script) : null;
    }
    return null;
  }
}

/** The blocked program a bash command would run directly, or null. */
export function blockedProgram(command: string): string | null {
  const { text, data } = heredocs(command);
  const { outer, inner } = substitutions(text);
  for (const body of data) inner.push(...substitutions(body, false).inner);
  for (const body of inner) {
    const found = blockedProgram(body);
    if (found) return found;
  }
  for (const words of segments(outer)) {
    const found = classifySegment(words);
    if (found) return found;
  }
  return null;
}

export function blockReason(program: string, root: string): string {
  if (program === MIGRATE) {
    return (
      "migrate rewrites the project's configuration files; ask the user to run /oasis migrate in Gentle Shell " +
      "or the command in a terminal. To read the plan without changing anything, run it with only --plan."
    );
  }
  if (program === WORKTREE_INIT) {
    return (
      "worktree-init creates links to environment files; ask the user to run /oasis worktree <feature> " +
      "<branch> in Gentle Shell or the command in a terminal."
    );
  }
  return (
    `Direct ${program} is blocked in this Odoo 19 project: it bypasses the database prefix guards. ` +
    `Use the oasis tools (oasis_test_module, oasis_module_status) or ` +
    `\`oasis --project ${root} <command>\` (test-module, update-module, install-module, odoo-shell, ` +
    `create-database, drop-database). If the user explicitly needs raw access, ask them to run it.`
  );
}
