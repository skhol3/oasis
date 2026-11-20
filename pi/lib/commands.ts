// The /oasis subcommands: one table for completion, usage, description and dispatch. No Pi imports.

export const SUBCOMMANDS = [
  {
    name: "setup", parameters: [],
    description: "Install or update the subagent overlay",
    summary: "`setup` installs the subagent overlay",
  },
  {
    name: "doctor", parameters: [],
    description: "Check the environment (read-only)",
    summary: "`doctor` checks the environment contract (read-only)",
  },
  {
    name: "migrate", parameters: [],
    description: "Plan and apply the move to a workspace file",
    summary: "`migrate` converts the checkouts' profiles into one oasis-workspace.toml after confirmation",
  },
  {
    name: "worktree", parameters: ["feature", "branch"],
    description: "Create a worktree: worktree <feature> <branch>",
    summary: "`worktree <feature> <branch>` creates a prepared linked worktree",
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
