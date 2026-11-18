// Which tools the layer keeps active: the odoo19_* tools only in Odoo 19 projects.

export const ODOO19_TOOLS: readonly string[] = [
  "odoo19_test_module",
  "odoo19_find_module",
  "odoo19_model_info",
  "odoo19_module_status",
  "odoo19_check_environment",
  "odoo19_lint_module",
];

// Next active tool list: other tools and their order are kept; ours are appended once in an
// Odoo project and removed otherwise. Never mutates `active`.
export function nextActiveTools(active: readonly string[], odooProject: boolean, ours: readonly string[]): string[] {
  if (!odooProject) return active.filter((name) => !ours.includes(name));
  return [...new Set([...active, ...ours])];
}
