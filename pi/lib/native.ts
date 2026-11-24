// The native odoo-bin line of the start / restart form (S4): the command that prints it
// (`oasis --project <root> start --print-command [options]`, the same for restart), its output read
// as one shell-quoted line, the abbreviated form the panel shows and a per-argv cache fetched in the
// background. No Pi imports: the panel injects the command runner; the filled command comes from
// menu.ts fillTemplate (passed in, so this module does not import menu.ts).
import type { CoreResult } from "./tools.ts";

const SERVER_COMMANDS = ["start", "restart"];
/** start's own mode, not an Odoo option: the detached server runs the same odoo-bin argv. */
const DETACH = "--detach";
const PRINT_COMMAND = "--print-command";
// A value longer than this is shown as its first HEAD and last TAIL characters around "…".
const MAX_VALUE = 40;
const HEAD = 20;
const TAIL = 19;
// What the abbreviated line leaves unquoted: shlex.join's safe characters, `~` and the ellipsis.
const DISPLAY_SAFE = /^[A-Za-z0-9_@%+=:,./~…-]+$/;

/** Where the native line of one argv is: being read, read, or not available (with a short reason). */
export type NativeState = { state: "loading" } | { state: "ready"; line: string } | { state: "failed"; reason: string };

/** The native lines the form shows: get() starts reading an argv once; onChange() hears every result. */
export interface NativeSource {
  get(argv: string[]): NativeState;
  onChange(listener: () => void): () => void;
}

/**
 * The command that prints the native line of a start or restart action (its catalog `command`)
 * from its filled argv (menu.ts fillTemplate): --print-command right after the command word and
 * without --detach; null for other actions.
 */
export function printCommandArgv(command: string | null, argv: string[]): string[] | null {
  if (!command || !SERVER_COMMANDS.includes(command)) return null;
  const at = argv.indexOf(command);
  if (at === -1) return null;
  const options = argv.slice(at + 1).filter((word) => word !== DETACH);
  return [...argv.slice(0, at + 1), PRINT_COMMAND, ...options];
}

/** The words of a POSIX shell line (single and double quotes, backslashes); null when a quote is open. */
export function shellSplit(line: string): string[] | null {
  const words: string[] = [];
  let word = "";
  let inWord = false;
  let index = 0;
  while (index < line.length) {
    const char = line[index];
    if (char === "'") {
      const end = line.indexOf("'", index + 1);
      if (end === -1) return null;
      word += line.slice(index + 1, end);
      inWord = true;
      index = end + 1;
    } else if (char === '"') {
      inWord = true;
      index += 1;
      for (;;) {
        if (index >= line.length) return null;
        const next = line[index];
        if (next === '"') {
          index += 1;
          break;
        }
        if (next === "\\" && index + 1 < line.length && "\"\\$`".includes(line[index + 1])) {
          word += line[index + 1];
          index += 2;
          continue;
        }
        word += next;
        index += 1;
      }
    } else if (char === "\\") {
      if (index + 1 >= line.length) return null;
      word += line[index + 1];
      inWord = true;
      index += 2;
    } else if (char === " " || char === "\t") {
      if (inWord) words.push(word);
      word = "";
      inWord = false;
      index += 1;
    } else {
      word += char;
      inWord = true;
      index += 1;
    }
  }
  if (inWord) words.push(word);
  return words;
}

/** The native line of a --print-command run: exit 0 and exactly one shell-quoted line on stdout. */
export function parseNativeLine(result: CoreResult): NativeState {
  if (result.code !== 0) return { state: "failed", reason: `exit ${result.code}` };
  const lines = result.stdout.split("\n").map((line) => line.trim()).filter(Boolean);
  if (lines.length !== 1 || !shellSplit(lines[0])?.length) return { state: "failed", reason: "unexpected output" };
  return { state: "ready", line: lines[0] };
}

function escapeRegExp(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function shorten(value: string): string {
  return value.length <= MAX_VALUE ? value : `${value.slice(0, HEAD)}…${value.slice(-TAIL)}`;
}

/**
 * The native line as the form shows it: the home directory as `~` (at the start of a word or a
 * value after `=`, `,` or `:`), and every value longer than 40 characters (the part after
 * `--option=`, else the whole word) cut to its first 20 and last 19 characters around `…`. Words
 * are quoted again only when they need it; the full line goes to the result entry.
 */
export function abbreviateCommand(line: string, home: string | undefined): string {
  const words = shellSplit(line) ?? [line];
  const root = home && home !== "/" ? home.replace(/\/+$/, "") : "";
  const homePattern = root ? new RegExp(`(^|[=,:])${escapeRegExp(root)}(?=/|$|[,:])`, "g") : null;
  return words.map((word) => {
    const local = homePattern ? word.replace(homePattern, "$1~") : word;
    const option = /^(--?[A-Za-z][\w-]*=)(.*)$/.exec(local);
    const shown = option ? `${option[1]}${shorten(option[2])}` : shorten(local);
    if (shown !== "" && DISPLAY_SAFE.test(shown)) return shown;
    return `'${shown.replaceAll("'", "'\"'\"'")}'`;
  }).join(" ");
}

/**
 * Native lines read with `exec` once per argv, in the background: get() answers at once (loading
 * until the command ends), settled() waits for the line (null when it is not available), and
 * every result calls the onChange listeners so the form can draw it.
 */
export function nativeCommands(exec: (argv: string[]) => Promise<CoreResult>): NativeSource & {
  settled(argv: string[]): Promise<string | null>;
} {
  const states = new Map<string, NativeState>();
  const pending = new Map<string, Promise<NativeState>>();
  const listeners = new Set<() => void>();
  function start(argv: string[]): Promise<NativeState> {
    const key = JSON.stringify(argv);
    const known = pending.get(key);
    if (known) return known;
    states.set(key, { state: "loading" });
    let running: Promise<CoreResult>;
    try {
      running = exec(argv);
    } catch (error) {
      running = Promise.reject(error);
    }
    const read = running.then(parseNativeLine, (): NativeState => ({ state: "failed", reason: "could not run" }))
      .then((state) => {
        states.set(key, state);
        for (const listener of listeners) listener();
        return state;
      });
    pending.set(key, read);
    return read;
  }
  return {
    get(argv) {
      void start(argv);
      return states.get(JSON.stringify(argv)) ?? { state: "loading" };
    },
    async settled(argv) {
      const state = await start(argv);
      return state.state === "ready" ? state.line : null;
    },
    onChange(listener) {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
  };
}
