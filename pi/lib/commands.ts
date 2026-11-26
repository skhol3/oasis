// The /oasis subcommands: one table for completion (after /oasis and, v0.12.1, while its name is typed), usage,
// description and dispatch. No Pi imports.

export const SUBCOMMANDS = [
  {
    name: "setup", parameters: [],
    description: "Show the workspace status and the oasis setup plan (never applied); install the subagent overlay",
    summary: "`setup` shows the workspace status and the `oasis setup` plan of the checkout (it never applies it) and " +
      "installs the subagent overlay in Gentle Shell",
  },
  {
    name: "doctor", parameters: [],
    description: "Check the environment (read-only)",
    summary: "`doctor` checks the environment contract (read-only)",
  },
  {
    name: "migrate", parameters: [],
    description: "Plan and apply the move to a workspace file",
    summary: "`migrate` converts the checkouts' legacy .odoo19-agent.toml profiles into one oasis-workspace.toml after confirmation",
  },
  {
    name: "worktree", parameters: ["feature", "branch"],
    description: "Create a worktree: worktree <feature> <branch>",
    summary: "`worktree <feature> <branch>` creates a prepared linked worktree",
  },
  {
    name: "menu", parameters: [],
    description: "Open the action panel (alt+o by default)",
    summary: "`menu` opens the action panel to run the checkout's everyday commands (alt+o by default)",
  },
] as const;

export type SubcommandName = (typeof SUBCOMMANDS)[number]["name"];

function signature(item: (typeof SUBCOMMANDS)[number]): string {
  return [item.name, ...item.parameters.map((parameter) => `<${parameter}>`)].join(" ");
}

export const USAGE = `Usage: /oasis [${SUBCOMMANDS.map(signature).join(" | ")}]`;

/** The subcommand part of the /oasis description. */
export const SUBCOMMAND_SUMMARY = SUBCOMMANDS.map((item) => item.summary).join("; ");

export type Parsed =
  | { kind: "status" }
  | { kind: "usage" }
  | { kind: "run"; name: SubcommandName; args: string[] };

/** What `/oasis <argument>` asks for: the status, a subcommand with its arguments, or the usage. */
export function parseCommand(argument: string): Parsed {
  const words = argument.trim().split(/\s+/).filter(Boolean);
  if (words.length === 0) return { kind: "status" };
  const item = SUBCOMMANDS.find((candidate) => candidate.name === words[0]);
  const args = words.slice(1);
  if (!item || args.length !== item.parameters.length || args.some((word) => word.startsWith("-"))) {
    return { kind: "usage" };
  }
  return { kind: "run", name: item.name, args };
}

export interface Completion {
  value: string;
  label: string;
  description: string;
}

/** Completions for the first word after /oasis; null once a subcommand is complete. */
export function subcommandCompletions(prefix: string): Completion[] | null {
  const typed = prefix.trimStart();
  if (/\s/.test(typed)) return null;
  const items = SUBCOMMANDS.filter((item) => item.name.startsWith(typed)).map((item) => ({
    value: item.parameters.length > 0 ? `${item.name} ` : item.name,
    label: item.name,
    description: item.description,
  }));
  return items.length > 0 ? items : null;
}

/** The command names whose subcommands are suggested while the name is typed (S3, v0.12.1). */
const COMMAND_NAMES = ["oasis", "odoo19"] as const;
// From two typed letters: `/o` alone matches too many commands.
const MIN_TYPED = 2;

/** An editor suggestion and a suggestion list, shaped like pi-tui's AutocompleteItem and AutocompleteSuggestions. */
export interface SuggestionItem {
  value: string;
  label: string;
  description?: string;
}

export interface Suggestions {
  items: SuggestionItem[];
  prefix: string;
}

/** The part of pi-tui's AutocompleteProvider the wrapper uses (no Pi imports here). */
export interface AutocompleteSource {
  triggerCharacters?: string[];
  getSuggestions(lines: string[], cursorLine: number, cursorCol: number,
    options: { signal: AbortSignal; force?: boolean }): Promise<Suggestions | null>;
  applyCompletion(lines: string[], cursorLine: number, cursorCol: number, item: SuggestionItem, prefix: string):
    { lines: string[]; cursorLine: number; cursorCol: number };
  shouldTriggerFileCompletion?(lines: string[], cursorLine: number, cursorCol: number): boolean;
}

/**
 * `/oasis <subcommand>` (and `/odoo19 <subcommand>`) suggestions while the command name is typed:
 * a slash, at least two letters of the name and no space yet. The prefix is the typed command as
 * Pi's slash-command completion uses it, so its applyCompletion inserts `/<value> `.
 */
export function commandNameCompletions(textBeforeCursor: string): Suggestions | null {
  const typed = textBeforeCursor.trimStart();
  if (!typed.startsWith("/")) return null;
  const name = typed.slice(1);
  if (name.length < MIN_TYPED || /\s/.test(name)) return null;
  const items = COMMAND_NAMES.filter((command) => command.startsWith(name)).flatMap((command) =>
    SUBCOMMANDS.map((item) => ({
      value: `${command} ${item.name}`, label: `${command} ${item.name}`, description: item.description,
    })));
  return items.length > 0 ? { prefix: typed, items } : null;
}

/**
 * The existing suggestions with the subcommands of the typed command name added right after the
 * command's own item (last when it is not listed), without repeating one already there; any other
 * text, or suggestions for another prefix, are returned unchanged.
 */
export function withSubcommandSuggestions(textBeforeCursor: string, base: Suggestions | null): Suggestions | null {
  const extra = commandNameCompletions(textBeforeCursor);
  if (!extra || (base && base.prefix !== extra.prefix)) return base;
  const items = [...(base?.items ?? [])];
  const known = new Set(items.map((item) => item.value));
  for (const command of COMMAND_NAMES) {
    const added = extra.items.filter((item) => item.value.startsWith(`${command} `) && !known.has(item.value));
    if (added.length === 0) continue;
    const at = items.findIndex((item) => item.value === command);
    items.splice(at === -1 ? items.length : at + 1, 0, ...added);
  }
  return { prefix: extra.prefix, items };
}

/**
 * The editor's autocomplete provider wrapped for S3 (ctx.ui.addAutocompleteProvider): the current
 * provider answers first, then the /oasis and /odoo19 subcommands are added while their name is
 * typed. Forced completion, completion itself, file completion and trigger characters delegate
 * unchanged.
 */
export function subcommandAutocomplete(current: AutocompleteSource): AutocompleteSource {
  const provider: AutocompleteSource = {
    async getSuggestions(lines, cursorLine, cursorCol, options) {
      const base = await current.getSuggestions(lines, cursorLine, cursorCol, options);
      if (options.force || options.signal.aborted) return base;
      return withSubcommandSuggestions((lines[cursorLine] ?? "").slice(0, cursorCol), base);
    },
    applyCompletion: (lines, cursorLine, cursorCol, item, prefix) =>
      current.applyCompletion(lines, cursorLine, cursorCol, item, prefix),
  };
  if (current.triggerCharacters) provider.triggerCharacters = current.triggerCharacters;
  if (current.shouldTriggerFileCompletion) {
    provider.shouldTriggerFileCompletion = (lines, cursorLine, cursorCol) =>
      current.shouldTriggerFileCompletion?.(lines, cursorLine, cursorCol) ?? true;
  }
  return provider;
}

/** What a session_start context offers to register the S3 provider (ctx.mode and ctx.ui). */
export interface AutocompleteHost {
  mode: string;
  ui: { addAutocompleteProvider(factory: (current: AutocompleteSource) => AutocompleteSource): void };
}

/**
 * Registers subcommandAutocomplete for a session, only in the interactive TUI: `ctx.mode === "tui"`
 * is the check Pi documents for editor features (RPC, JSON and print sessions have no editor to
 * complete in). Returns whether it registered.
 */
export function registerSubcommandAutocomplete(ctx: AutocompleteHost): boolean {
  if (ctx.mode !== "tui") return false;
  ctx.ui.addAutocompleteProvider((current) => subcommandAutocomplete(current));
  return true;
}
