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
};
const DOCKER_VALUE_OPTIONS = new Set([
  "-f", "--file", "-p", "--project-name", "--project-directory", "--env-file", "--profile",
  "-u", "--user", "-w", "--workdir", "-e", "--env", "--index",
]);
const PYTHON_VALUE_OPTIONS = new Set(["-X", "-W", "-c", "-m"]);

function basename(word: string): string {
  return word.slice(word.lastIndexOf("/") + 1);
}

/** Pull out $(...) and `...` bodies so they are classified as commands too. */
function substitutions(command: string): { outer: string; inner: string[] } {
  const inner: string[] = [];
  let outer = "";
  for (let i = 0; i < command.length; i++) {
    if (command[i] === "$" && command[i + 1] === "(") {
      let depth = 1;
      let j = i + 2;
      for (; j < command.length && depth; j++) {
        if (command[j] === "(") depth++;
        else if (command[j] === ")") depth--;
      }
      inner.push(command.slice(i + 2, j - 1));
      outer += " _ ";
      i = j - 1;
    } else if (command[i] === "`") {
      const end = command.indexOf("`", i + 1);
      const stop = end < 0 ? command.length : end;
      inner.push(command.slice(i + 1, stop));
      outer += " _ ";
      i = stop;
    } else {
      outer += command[i];
    }
  }
  return { outer, inner };
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

/** A user-run tool when words[index] runs it: its tool script, or an entry point with that command.
 * migrate's scripts count only inside a `tools` directory, since the name is common. */
function userRunTool(words: string[], index: number): string | null {
  const word = words[index];
  const name = basename(word);
  if (WORKTREE_INIT_SCRIPTS.has(name)) return WORKTREE_INIT;
  if (MIGRATE_SCRIPTS.has(name) && /(^|\/)tools\/[^/]+$/.test(word)) return MIGRATE;
  if (!ENTRY_POINTS.has(name)) return null;
  if (words.slice(index + 1).includes(WORKTREE_INIT)) return WORKTREE_INIT;
  return entryPointCommand(words, index) === MIGRATE ? MIGRATE : null;
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
    const wrapper = WRAPPERS[name];
    if (wrapper) {
      i = skipOptions(words, i + 1, wrapper);
      if (name === "timeout" && i < words.length) i++; // the duration
      continue;
    }
    if (name === "docker") {
      i = skipOptions(words, i + 1, DOCKER_VALUE_OPTIONS);
      if (words[i] === "compose") i = skipOptions(words, i + 1, DOCKER_VALUE_OPTIONS);
      if (words[i] !== "exec" && words[i] !== "run") return null;
      i = skipOptions(words, i + 1, DOCKER_VALUE_OPTIONS) + 1; // the service or container
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
  const { outer, inner } = substitutions(command);
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
      "or the command in a terminal."
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
