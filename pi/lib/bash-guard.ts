// Classify bash commands that bypass the odoo19 guards. No Pi imports.
// Only programs in command position count, so searching or printing their
// names stays allowed. This is a guard rail for agents, not a sandbox.

const BLOCKED = new Set(["odoo-bin", "dropdb", "psql"]);
const SHELLS = new Set(["bash", "sh", "zsh", "dash"]);
const ASSIGNMENT = /^[A-Za-z_][A-Za-z0-9_]*=/;
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

function classifySegment(words: string[]): string | null {
  let i = 0;
  for (;;) {
    while (i < words.length && ASSIGNMENT.test(words[i])) i++;
    if (i >= words.length) return null;
    const name = basename(words[i]);
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
    if (/^python[\d.]*$/.test(name)) {
      const target = skipOptions(words, i + 1, PYTHON_VALUE_OPTIONS);
      if (words.slice(i + 1, target).some((w) => w === "-c" || w === "-m")) return null;
      return target < words.length && basename(words[target]) === "odoo-bin" ? "odoo-bin" : null;
    }
    if (SHELLS.has(name)) {
      const flag = words.indexOf("-c", i + 1);
      return flag > 0 && flag + 1 < words.length ? blockedProgram(words[flag + 1]) : null;
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
  return (
    `Direct ${program} is blocked in this Odoo 19 project: it bypasses the database prefix guards. ` +
    `Use the odoo19 tools (odoo19_test_module, odoo19_module_status) or ` +
    `\`odoo19 --project ${root} <command>\` (test-module, update-module, install-module, odoo-shell, ` +
    `create-database, drop-database). If the user explicitly needs raw access, ask them to run it.`
  );
}
