// Which tools the layer keeps active: the oasis_* tools only in Odoo projects.

export const OASIS_TOOLS: readonly string[] = [
  "oasis_test_module",
  "oasis_find_module",
  "oasis_model_info",
  "oasis_module_status",
  "oasis_check_environment",
  "oasis_lint_module",
];

/** The pre-0.4.0 name of an oasis_* tool, registered as its inactive alias. */
export function aliasOf(name: string): string {
  return name.replace(/^oasis_/, "odoo19_");
}

// Registered inactive with the same implementation, so overlays and allowlists that still name
// them keep working; the layer never activates or removes them (they are not in OASIS_TOOLS).
export const TOOL_ALIASES: readonly string[] = OASIS_TOOLS.map(aliasOf);

// Next active tool list: other tools and their order are kept; ours are appended once in an
// Odoo project and removed otherwise. Never mutates `active`.
export function nextActiveTools(active: readonly string[], odooProject: boolean, ours: readonly string[]): string[] {
  if (!odooProject) return active.filter((name) => !ours.includes(name));
  return [...new Set([...active, ...ours])];
}
