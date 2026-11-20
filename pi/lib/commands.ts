// The /oasis subcommands and their argument completion. No Pi imports.

export const SUBCOMMANDS = [
  { name: "setup", takesArguments: false, description: "Install or update the subagent overlay" },
  { name: "doctor", takesArguments: false, description: "Check the environment (read-only)" },
  { name: "migrate", takesArguments: false, description: "Plan and apply the move to a workspace file" },
  { name: "worktree", takesArguments: true, description: "Create a worktree: worktree <feature> <branch>" },
] as const;

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
    value: item.takesArguments ? `${item.name} ` : item.name,
    label: item.name,
    description: item.description,
  }));
  return items.length > 0 ? items : null;
}
