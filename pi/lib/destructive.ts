// The agent's bash gate (S3, S4): the deny tier as before, and the ask tier, which the user
// confirms in a dialog unless the project's [tooling].agent_destructive says deny or allow. The
// files that hold that setting are in the ask tier too, for bash writes and the agent's edit and
// write tools (agentFileGate). The Pi effects are injected (dialogs, appendEntry, the profile
// read), so it is tested without Pi; pi/extensions/oasis.ts only adapts ctx and pi to these
// interfaces. No Pi imports.
import { posix } from "node:path";
import { type AskAction, blockedEverywhere, blockReason, classifyBash } from "./bash-guard.ts";
import { type MenuEntry, plainLine } from "./menu.ts";
import { PROFILE_NAME, WORKSPACE_NAME } from "./project.ts";

/** The custom session entry type of a decision: shown to the user, never sent to the model. */
export const DECISION_ENTRY = "oasis-agent-decision";
/** How long the dialog waits for an answer; no answer refuses. */
export const ASK_TIMEOUT_MS = 2 * 60 * 1000;
/** The values of [tooling].agent_destructive; anything else (or an unreadable profile) is ask. */
export const AGENT_DESTRUCTIVE = ["ask", "deny", "allow"] as const;
export type AgentDestructive = (typeof AGENT_DESTRUCTIVE)[number];

const APPROVED = "Agent command approved";
const REFUSED = "Agent command refused";
// The files that hold [tooling].agent_destructive: a workspace file or a legacy profile in the
// session's directory or above it, where tools/config.py finds them (an oasis-checkout.toml
// refuses the key).
const SETTING_NAMES = new Set([WORKSPACE_NAME, PROFILE_NAME]);

export interface GateUi {
  /** ctx.ui.input: undefined when cancelled, timed out or aborted. */
  input(
    title: string, placeholder: string | undefined, options: { timeout: number; signal?: AbortSignal },
  ): Promise<string | undefined>;
}

export interface GateContext {
  cwd: string;
  /** ctx.hasUI: false in subagents and headless runs, which cannot show a dialog. */
  hasUI: boolean;
  /** The agent's abort signal: aborting the turn closes the dialog (a refusal). */
  signal?: AbortSignal;
  ui: GateUi;
}

export interface GateEffects {
  /** The session's Odoo checkout root, or null outside a project. */
  projectRoot(cwd: string): Promise<string | null>;
  home: string;
  exists(path: string): boolean;
  /** AGENT_DESTRUCTIVE of tools/config.py for root; undefined when the profile cannot be read. */
  agentDestructive(root: string): Promise<string | undefined>;
  /** Records a decision as a custom session entry (DECISION_ENTRY). */
  appendEntry(entry: MenuEntry): void;
  /** realpathSync: the real path of an existing path; throws when it does not exist. Default: none. */
  realpath?(path: string): string;
  timeoutMs?: number;
}

export type GateResult = { block: true; reason: string } | undefined;

/** The ask command as the user reads it in the dialog and the reasons. */
function label(action: AskAction): string {
  if (action.command === "edit") return `editing ${action.file}`;
  return action.command === "drop-database" ? `drop-database ${action.database}` : action.command;
}

/** What the user types to allow it: the database name, or `yes`. */
function expected(action: AskAction): string {
  return action.command === "drop-database" && action.database !== null ? action.database : "yes";
}

/** How the reasons end: what did not happen, and what the user does instead. */
function outcome(action: AskAction): { nothing: string; user: string } {
  return action.command === "edit"
    ? { nothing: "nothing changed", user: "make the change" }
    : { nothing: "nothing ran", user: "run it" };
}

/** The command without terminal control sequences, line by line. */
function shown(command: string): string {
  return command.split("\n").map(plainLine).join("\n");
}

function setting(value: string | undefined): AgentDestructive {
  return AGENT_DESTRUCTIVE.find((known) => known === value) ?? "ask";
}

/**
 * The setting file a write reaches from a session in cwd (GuardContext.settingFile): a path named
 * oasis-workspace.toml or .odoo19-agent.toml in cwd or above it, as written or as its real path
 * (a link, or a linked directory, reaches the file it names; above the real cwd too). A path the
 * text does not tell counts by its name.
 */
function settingFiles(effects: GateEffects, cwd: string): (path: string | null, word: string) => string | null {
  const real = (path: string): string => {
    if (!effects.realpath) return path;
    try {
      return effects.realpath(path);
    } catch {
      try {
        return posix.join(effects.realpath(posix.dirname(path)), posix.basename(path));
      } catch {
        return path;
      }
    }
  };
  const governing = new Set<string>();
  for (const start of [posix.normalize(cwd), real(cwd)]) {
    for (let dir = start; ; dir = posix.dirname(dir)) {
      governing.add(dir);
      if (dir === posix.dirname(dir)) break;
    }
  }
  return (path, word) => {
    if (path === null) return SETTING_NAMES.has(posix.basename(word)) ? word : null;
    for (const candidate of [path, real(path)]) {
      if (SETTING_NAMES.has(posix.basename(candidate)) && governing.has(posix.dirname(candidate))) return candidate;
    }
    return null;
  };
}

/** Where the agent's edit or write tool writes: Pi strips a leading `@`, expands `~` and resolves from cwd. */
function toolPath(path: string, cwd: string, home: string): string {
  let target = path.startsWith("@") ? path.slice(1) : path;
  if (target === "~" || target.startsWith("~/")) target = home + target.slice(1);
  return posix.resolve(cwd, target);
}

/**
 * The ask tier: the project's setting decides the ask actions of one tool call and, for ask, one
 * dialog each, in order; every decision is recorded. `intro` says what the agent wants (`run` a
 * bash command, `call` a tool) and `text` shows it. `root` is the session's project when known.
 */
function asker(effects: GateEffects) {
  const timeout = effects.timeoutMs ?? ASK_TIMEOUT_MS;
  const seconds = Math.round(timeout / 1000);
  return async (
    asks: AskAction[], intro: string, text: string, ctx: GateContext, known?: string | null,
  ): Promise<GateResult> => {
    const record = (approved: boolean, note: string) =>
      effects.appendEntry({ label: approved ? APPROVED : REFUSED, command: text, note, output: "" });
    const refuse = (note: string, reason: string): GateResult => {
      record(false, note);
      return { block: true, reason };
    };
    const root = known === undefined ? await effects.projectRoot(ctx.cwd) : known;
    const mode = root ? setting(await effects.agentDestructive(root)) : "ask";
    const first = label(asks[0]);
    const { nothing, user } = outcome(asks[0]);
    // allow never covers an edit of the setting files: the agent may not change its own permission
    // without the user, so those always reach the dialog (or are refused without a UI).
    if (mode === "allow" && !asks.some((action) => action.command === "edit")) {
      record(true, "agent_destructive = allow");
      return undefined;
    }
    if (mode === "deny") {
      return refuse("agent_destructive = deny",
        `${first} is denied to agents by [tooling].agent_destructive = "deny" in this project's configuration; ` +
          `${nothing}. Ask the user to ${user}.`);
    }
    if (asks.some((action) => action.command === "drop-database" && action.database === null)) {
      return refuse("database name not literal",
        "drop-database needs the database name written literally as its first argument, so the user can confirm " +
          "it; nothing ran. Rewrite the command with the name, or ask the user to run it.");
    }
    if (!ctx.hasUI) {
      return refuse("no dialog",
        `${first} needs the user's confirmation in a dialog, and this session has none (a subagent or a headless ` +
          `run); ${nothing}. Ask the user to ${user} or to confirm it from an interactive session.`);
    }
    const typed: string[] = [];
    for (const action of asks) {
      const answer = expected(action);
      const why = action.command === "edit" ? " (it holds [tooling].agent_destructive)" : "";
      const title = `oasis: the agent wants to ${intro}\n\n${text}\n\n` +
        `Type ${answer} to allow ${label(action)}${why}. Esc, another answer or no answer within ${seconds} s refuses.`;
      const reply = await ctx.ui.input(title, undefined, { timeout, signal: ctx.signal });
      const done = outcome(action);
      const retry = `Do not retry it: ask the user whether to ${done.user}.`;
      if (reply === undefined) {
        return refuse("no answer",
          `The user did not confirm ${label(action)} (cancelled, or no answer within ${seconds} s); ${done.nothing}. ${retry}`);
      }
      if (reply.trim() !== answer) {
        return refuse("wrong answer", `The user's answer did not confirm ${label(action)}; ${done.nothing}. ${retry}`);
      }
      typed.push(answer);
    }
    record(true, `typed ${typed.join(", ")}`);
    return undefined;
  };
}

/**
 * The tool_call gate for agent bash commands. The deny tier is decided as before (blockReason):
 * in an Odoo project the first denied program blocks with its reason; outside one, a user-run
 * program anywhere on the line does (direct odoo-bin, dropdb and psql run there). The ask commands
 * of what is left, bash writes to the setting files included, then go through the ask tier.
 */
export function agentGate(effects: GateEffects): (command: string, ctx: GateContext) => Promise<GateResult> {
  const ask = asker(effects);
  return async (command, ctx) => {
    // The menu's scripts and the ask tools are judged by the file they resolve to from the session's directory.
    const { programs, asks } = classifyBash(command, {
      cwd: ctx.cwd, home: effects.home, exists: effects.exists, settingFile: settingFiles(effects, ctx.cwd),
    });
    let root: string | null | undefined;
    if (programs.length > 0) {
      if (blockedEverywhere(programs[0])) return { block: true, reason: blockReason(programs[0], "") };
      root = await effects.projectRoot(ctx.cwd);
      if (root) return { block: true, reason: blockReason(programs[0], root) };
      const userRun = programs.find(blockedEverywhere);
      if (userRun) return { block: true, reason: blockReason(userRun, "") };
    }
    if (asks.length === 0) return undefined;
    return ask(asks, "run", shown(command), ctx, root);
  };
}

/**
 * The tool_call gate for the agent's edit and write tools: a path that reaches a setting file (see
 * settingFiles) goes through the ask tier, as `<tool> <path>`; any other path is allowed.
 */
export function agentFileGate(effects: GateEffects): (tool: string, path: string, ctx: GateContext) => Promise<GateResult> {
  const ask = asker(effects);
  return async (tool, path, ctx) => {
    const target = toolPath(path, ctx.cwd, effects.home);
    const file = settingFiles(effects, ctx.cwd)(target, path);
    if (file === null) return undefined;
    return ask([{ command: "edit", file }], "call", shown(`${tool} ${path}`), ctx);
  };
}
