// The agent's bash gate (S3, S4): the deny tier as before, and the ask tier, which the user
// confirms in a dialog unless the project's [tooling].agent_destructive says deny or allow. The
// files that hold that setting are in the ask tier too, for bash writes and the agent's edit and
// write tools (agentFileGate). The Pi effects are injected (dialogs, appendEntry, the configuration
// read), so it is tested without Pi; pi/extensions/oasis.ts only adapts ctx and pi to these
// interfaces. No Pi imports.
import { posix } from "node:path";
import { type AskAction, blockedEverywhere, blockReason, classifyBash } from "./bash-guard.ts";
import { type MenuEntry, plainLine } from "./menu.ts";
import { findWorkspaceFile, machineFile, PROFILE_NAME, WORKSPACE_NAME } from "./project.ts";

/** The custom session entry type of a decision: shown to the user, never sent to the model. */
export const DECISION_ENTRY = "oasis-agent-decision";
/** How long the dialog waits for an answer; no answer refuses. */
export const ASK_TIMEOUT_MS = 2 * 60 * 1000;
/** The values of [tooling].agent_destructive; anything else (or an unreadable configuration) is ask. */
export const AGENT_DESTRUCTIVE = ["ask", "deny", "allow"] as const;
export type AgentDestructive = (typeof AGENT_DESTRUCTIVE)[number];

const APPROVED = "Agent command approved";
const REFUSED = "Agent command refused";
// The files that hold [tooling].agent_destructive: a workspace file in the session's directory or
// above it, where tools/config.py finds it (an oasis-checkout.toml refuses the key), and a legacy
// profile there, which config.py no longer reads but oasis migrate converts into the workspace file.
// Also the workspace file a linked worktree reads through git (findWorkspaceFile), and the machine
// file, which holds the Odoo source paths (see settingFiles).
const SETTING_NAMES = new Set([WORKSPACE_NAME, PROFILE_NAME]);
// How a write to the machine file is spelled when the text does not tell its directory.
const MACHINE_TAIL = "oasis/config.toml";
const NOTE = " (it holds [tooling].agent_destructive)";
const MACHINE_NOTE = " (the machine file: it holds the Odoo source paths)";

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
  /** AGENT_DESTRUCTIVE of tools/config.py for root; undefined when the configuration cannot be read. */
  agentDestructive(root: string): Promise<string | undefined>;
  /** Records a decision as a custom session entry (DECISION_ENTRY). */
  appendEntry(entry: MenuEntry): void;
  /** realpathSync: the real path of an existing path; throws when it does not exist. Default: none. */
  realpath?(path: string): string;
  /** The workspace file a session in cwd reads (project.ts findWorkspaceFile, the default). */
  workspaceFile?(cwd: string): string | null;
  /** The environment the machine file is found from (XDG_CONFIG_HOME). Default: process.env. */
  environment?: Record<string, string | undefined>;
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

// How strict a mode is: the stricter of two decides.
const STRICTNESS: Record<AgentDestructive, number> = { allow: 0, ask: 1, deny: 2 };
// A tool script whose root variable is set elsewhere on the line reads a root the text does not tell.
const ROOT_VARIABLE = /\b(?:OASIS|ODOO19)_PROJECT_ROOT\b/;

/**
 * The mode of one tool call's ask actions: the stricter of the session project's setting and the
 * setting of every project they target (AskAction project). A target that is not literal, not an
 * Odoo project or whose configuration cannot be read counts as ask. `from` is the target project
 * whose setting decided, null when the session's did.
 */
async function strictestMode(
  effects: GateEffects, asks: AskAction[], root: string | null, text: string,
): Promise<{ mode: AgentDestructive; from: string | null }> {
  const read = new Map<string, AgentDestructive>();
  const modeOf = async (project: string): Promise<AgentDestructive> => {
    const known = read.get(project);
    if (known) return known;
    const mode = setting(await effects.agentDestructive(project));
    read.set(project, mode);
    return mode;
  };
  let mode: AgentDestructive = root ? await modeOf(root) : "ask";
  let from: string | null = null;
  const unknownRoot = ROOT_VARIABLE.test(text);
  for (const action of asks) {
    if (action.command === "edit") continue;
    let target = action.project;
    if (target === undefined) {
      if (!unknownRoot) continue;
      target = null;
    }
    const project = target === null ? null : await effects.projectRoot(target);
    if (project !== null && project === root) continue;
    const candidate = project === null ? "ask" : await modeOf(project);
    if (STRICTNESS[candidate] > STRICTNESS[mode]) {
      mode = candidate;
      from = project;
    }
  }
  return { mode, from };
}

/** A path's real path through effects.realpath (its directory's when it does not exist), else itself. */
function realOf(effects: GateEffects): (path: string) => string {
  return (path) => {
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
}

/** The machine files a write may reach: where tools/config.py reads it, and ~/.config's in any case. */
function machineFiles(effects: GateEffects): Set<string> {
  const real = realOf(effects);
  const files = [machineFile(effects.environment ?? process.env, effects.home), machineFile({}, effects.home)];
  return new Set(files.flatMap((file) => [posix.normalize(file), real(file)]));
}

/**
 * The setting file a write reaches from a session in cwd (GuardContext.settingFile): a path named
 * oasis-workspace.toml or .odoo19-agent.toml in cwd or above it, the workspace file the session's
 * checkout reads when it is elsewhere (a linked worktree outside the workspace directory reads its
 * main checkout's, found through git), or the machine file (machineFiles); as written or as its real
 * path (a link, or a linked directory, reaches the file it names; above the real cwd too). A path
 * the text does not tell counts by its name (`.../oasis/config.toml` for the machine file).
 */
function settingFiles(effects: GateEffects, cwd: string): (path: string | null, word: string) => string | null {
  const real = realOf(effects);
  const exact = machineFiles(effects);
  const governed = (effects.workspaceFile ?? findWorkspaceFile)(cwd);
  if (governed) for (const file of [posix.normalize(governed), real(governed)]) exact.add(file);
  const governing = new Set<string>();
  for (const start of [posix.normalize(cwd), real(cwd)]) {
    for (let dir = start; ; dir = posix.dirname(dir)) {
      governing.add(dir);
      if (dir === posix.dirname(dir)) break;
    }
  }
  return (path, word) => {
    if (path === null) {
      return SETTING_NAMES.has(posix.basename(word)) || word === MACHINE_TAIL || word.endsWith(`/${MACHINE_TAIL}`)
        ? word : null;
    }
    for (const candidate of [path, real(path)]) {
      if (exact.has(candidate)) return candidate;
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
 * The ask tier: the strictest setting of the session's project and of the projects the actions
 * target (strictestMode) decides the ask actions of one tool call and, for ask, one dialog each,
 * in order; every decision is recorded. `intro` says what the agent wants (`run` a bash command,
 * `call` a tool) and `text` shows it. `known` is the session's project when known.
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
    const { mode, from } = await strictestMode(effects, asks, root, text);
    const first = label(asks[0]);
    const { nothing, user } = outcome(asks[0]);
    // allow never covers an edit of the setting files: the agent may not change its own permission
    // without the user, so those always reach the dialog (or are refused without a UI).
    if (mode === "allow" && !asks.some((action) => action.command === "edit")) {
      record(true, "agent_destructive = allow");
      return undefined;
    }
    if (mode === "deny") {
      const where = from === null ? "this project's configuration" : `the configuration of ${from}`;
      return refuse("agent_destructive = deny",
        `${first} is denied to agents by [tooling].agent_destructive = "deny" in ${where}; ` +
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
    const machine = machineFiles(effects);
    for (const action of asks) {
      const answer = expected(action);
      const why = action.command !== "edit" ? ""
        : machine.has(action.file) || (!action.file.startsWith("/") && action.file.endsWith(MACHINE_TAIL)) ? MACHINE_NOTE
          : NOTE;
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

/** What tools/config.py read for a root, as the extension's projectConfig returns it. */
export type ProfileRead = (root: string) => Promise<{ config?: Record<string, string>; error?: string }>;

/**
 * GateEffects.agentDestructive over a config.py read: AGENT_DESTRUCTIVE when the configuration
 * loads; undefined (so ask) when it reports an error, lacks the key or the read throws.
 */
export function settingReader(read: ProfileRead): (root: string) => Promise<string | undefined> {
  return async (root) => {
    try {
      return (await read(root)).config?.AGENT_DESTRUCTIVE;
    } catch {
      return undefined;
    }
  };
}

/** Pi's tool_call event, as far as the gates read it. */
export interface ToolCallEvent {
  toolName: string;
  input: unknown;
}

/** Pi's ExtensionContext, as far as the gates read it: ui.input is called as a method of ui. */
export interface ToolCallContext {
  cwd: string;
  hasUI: boolean;
  signal?: AbortSignal;
  ui: GateUi;
}

/**
 * The extension's tool_call handler: an agent bash command goes to agentGate, an edit or write tool
 * call to agentFileGate with its path, with the session's cwd, hasUI, abort signal and input dialog;
 * any other tool, or an input without a string command or path, is left alone.
 */
export function toolCallRouter(effects: GateEffects): (event: ToolCallEvent, ctx: ToolCallContext) => Promise<GateResult> {
  const gate = agentGate(effects);
  const fileGate = agentFileGate(effects);
  return async (event, ctx) => {
    const context: GateContext = {
      cwd: ctx.cwd,
      hasUI: ctx.hasUI,
      signal: ctx.signal,
      ui: { input: (title, placeholder, options) => ctx.ui.input(title, placeholder, options) },
    };
    const input = (event.input ?? {}) as { command?: unknown; path?: unknown };
    if (event.toolName === "edit" || event.toolName === "write") {
      return typeof input.path === "string" ? fileGate(event.toolName, input.path, context) : undefined;
    }
    if (event.toolName !== "bash") return undefined;
    return typeof input.command === "string" ? gate(input.command, context) : undefined;
  };
}
