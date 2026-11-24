// The agent's bash gate (S3, S4): the deny tier as before, and the ask tier, which the user
// confirms in a dialog unless the project's [tooling].agent_destructive says deny or allow. The Pi
// effects are injected (dialogs, appendEntry, the profile read), so it is tested without Pi;
// pi/extensions/oasis.ts only adapts ctx and pi to these interfaces. No Pi imports.
import { type AskAction, blockedEverywhere, blockReason, classifyBash } from "./bash-guard.ts";
import { type MenuEntry, plainLine } from "./menu.ts";

/** The custom session entry type of a decision: shown to the user, never sent to the model. */
export const DECISION_ENTRY = "oasis-agent-decision";
/** How long the dialog waits for an answer; no answer refuses. */
export const ASK_TIMEOUT_MS = 2 * 60 * 1000;
/** The values of [tooling].agent_destructive; anything else (or an unreadable profile) is ask. */
export const AGENT_DESTRUCTIVE = ["ask", "deny", "allow"] as const;
export type AgentDestructive = (typeof AGENT_DESTRUCTIVE)[number];

const APPROVED = "Agent command approved";
const REFUSED = "Agent command refused";
const RETRY = "Do not retry it: ask the user whether to run it.";

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
  timeoutMs?: number;
}

export type GateResult = { block: true; reason: string } | undefined;

/** The ask command as the user reads it in the dialog and the reasons. */
function label(action: AskAction): string {
  return action.command === "drop-database" ? `drop-database ${action.database}` : action.command;
}

/** What the user types to allow it: the database name, or `yes`. */
function expected(action: AskAction): string {
  return action.command === "drop-database" && action.database !== null ? action.database : "yes";
}

/** The command without terminal control sequences, line by line. */
function shown(command: string): string {
  return command.split("\n").map(plainLine).join("\n");
}

function setting(value: string | undefined): AgentDestructive {
  return AGENT_DESTRUCTIVE.find((known) => known === value) ?? "ask";
}

/**
 * The tool_call gate for agent bash commands. The deny tier is decided exactly as before
 * (blockedProgram, blockReason); the ask commands of what is left then go through the project's
 * setting and, for ask, one dialog each, in order; every ask decision is recorded.
 */
export function agentGate(effects: GateEffects): (command: string, ctx: GateContext) => Promise<GateResult> {
  const timeout = effects.timeoutMs ?? ASK_TIMEOUT_MS;
  const seconds = Math.round(timeout / 1000);

  return async (command, ctx) => {
    // The menu's scripts and the ask tools are judged by the file they resolve to from the session's directory.
    const { program, asks } = classifyBash(command, { cwd: ctx.cwd, home: effects.home, exists: effects.exists });
    let root: string | null | undefined;
    if (program) {
      if (blockedEverywhere(program)) return { block: true, reason: blockReason(program, "") };
      root = await effects.projectRoot(ctx.cwd);
      if (root) return { block: true, reason: blockReason(program, root) };
    }
    if (asks.length === 0) return undefined;
    const text = shown(command);
    const record = (approved: boolean, note: string) =>
      effects.appendEntry({ label: approved ? APPROVED : REFUSED, command: text, note, output: "" });
    const refuse = (note: string, reason: string): GateResult => {
      record(false, note);
      return { block: true, reason };
    };
    if (root === undefined) root = await effects.projectRoot(ctx.cwd);
    const mode = root ? setting(await effects.agentDestructive(root)) : "ask";
    const first = label(asks[0]);
    if (mode === "allow") {
      record(true, "agent_destructive = allow");
      return undefined;
    }
    if (mode === "deny") {
      return refuse("agent_destructive = deny",
        `${first} is denied to agents by [tooling].agent_destructive = "deny" in this project's configuration; ` +
          "nothing ran. Ask the user to run it.");
    }
    if (asks.some((action) => action.command === "drop-database" && action.database === null)) {
      return refuse("database name not literal",
        "drop-database needs the database name written literally as its first argument, so the user can confirm " +
          "it; nothing ran. Rewrite the command with the name, or ask the user to run it.");
    }
    if (!ctx.hasUI) {
      return refuse("no dialog",
        `${first} needs the user's confirmation in a dialog, and this session has none (a subagent or a headless ` +
          "run); nothing ran. Ask the user to run it or to confirm it from an interactive session.");
    }
    const typed: string[] = [];
    for (const action of asks) {
      const answer = expected(action);
      const title = `oasis: the agent wants to run\n\n${text}\n\n` +
        `Type ${answer} to allow ${label(action)}. Esc, another answer or no answer within ${seconds} s refuses.`;
      const reply = await ctx.ui.input(title, undefined, { timeout, signal: ctx.signal });
      if (reply === undefined) {
        return refuse("no answer",
          `The user did not confirm ${label(action)} (cancelled, or no answer within ${seconds} s); nothing ran. ${RETRY}`);
      }
      if (reply.trim() !== answer) {
        return refuse("wrong answer", `The user's answer did not confirm ${label(action)}; nothing ran. ${RETRY}`);
      }
      typed.push(answer);
    }
    record(true, `typed ${typed.join(", ")}`);
    return undefined;
  };
}
