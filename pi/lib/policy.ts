// The core policy table (tools/policy.py) as the guard reads it: each operation's tier, and what a
// harness does with a tier. lib/policy.generated.ts is generated from the table; no Pi imports.
import { POLICY, type PolicyEntry, type Tier } from "./policy.generated.ts";

export type { PolicyEntry, Tier } from "./policy.generated.ts";
/** A: the agent runs it alone; B: the user confirms it (the dialog); C: only the user runs it. */
export const HARNESS: Readonly<Record<Tier, "allow" | "ask" | "deny">> = { A: "allow", B: "ask", C: "deny" };

const STRICTNESS: Record<Tier, number> = { A: 0, B: 1, C: 2 };
const BY_OPERATION = new Map<string, PolicyEntry>(POLICY.map((entry) => [entry.operation, entry]));
// The oasis commands' rows by command (the operation's first word); the other words are its arguments.
const BY_COMMAND = new Map<string, PolicyEntry[]>();
for (const entry of POLICY.filter((row) => row.kind === "oasis")) {
  const command = entry.operation.split(" ")[0];
  BY_COMMAND.set(command, [...(BY_COMMAND.get(command) ?? []), entry]);
}

/** The table's entry of an operation; throws for one it does not list (the guard drifted from it). */
export function policyEntry(operation: string): PolicyEntry {
  const entry = BY_OPERATION.get(operation);
  if (!entry) throw new Error(`${operation} is not in the oasis policy table (tools/policy.py)`);
  return entry;
}

export function tierOf(operation: string): Tier {
  return policyEntry(operation).tier;
}

/** The oasis commands the table lists. */
export const COMMANDS: ReadonlySet<string> = new Set(BY_COMMAND.keys());
/** The programs outside oasis the table lists: odoo-bin, dropdb, psql. */
export const PROGRAMS: ReadonlySet<string> = new Set(
  POLICY.filter((entry) => entry.kind === "program").map((entry) => entry.operation));

function strictest(rows: PolicyEntry[]): PolicyEntry {
  return rows.reduce((found, row) => (STRICTNESS[row.tier] > STRICTNESS[found.tier] ? row : found));
}

/**
 * The operation an oasis command runs with these arguments, or null for a command the table does
 * not list: the row whose words after the command all appear in args, the most specific one (the
 * stricter on a tie, `migrate --plan --apply`). With an argument that is not literal (`literal`
 * false: it may expand to anything), or no matching row, the command's strictest row.
 */
export function operationOf(command: string, args: string[], literal: boolean): PolicyEntry | null {
  const rows = BY_COMMAND.get(command);
  if (!rows) return null;
  const words = (row: PolicyEntry) => row.operation.split(" ").slice(1);
  const matching = literal ? rows.filter((row) => words(row).every((word) => args.includes(word))) : [];
  if (matching.length === 0) return strictest(rows);
  const most = Math.max(...matching.map((row) => words(row).length));
  return strictest(matching.filter((row) => words(row).length === most));
}
