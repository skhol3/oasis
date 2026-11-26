// Which tools the layer keeps active: the oasis_* tools only in Odoo projects.

export const OASIS_TOOLS: readonly string[] = [
  "oasis_test_module",
  "oasis_test_summary",
  "oasis_update_module",
  "oasis_find_module",
  "oasis_model_info",
  "oasis_view_info",
  "oasis_xmlid_info",
  "oasis_module_info",
  "oasis_module_status",
  "oasis_check_environment",
  "oasis_lint_module",
];

// Next active tool list: other tools and their order are kept; ours are appended once in an
// Odoo project and removed otherwise. Never mutates `active`.
export function nextActiveTools(active: readonly string[], odooProject: boolean, ours: readonly string[]): string[] {
  if (!odooProject) return active.filter((name) => !ours.includes(name));
  return [...new Set([...active, ...ours])];
}
