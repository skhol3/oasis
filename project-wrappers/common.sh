#!/usr/bin/env bash
# This file is sourced by existing project-local helpers; do not exec a subprocess.
export ODOO19_PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
tools=${ODOO19_TOOLS_DIR:-$HOME/.agents/skills/odoo19/tools}
if [[ ! -f "$tools/common.sh" ]]; then
  printf 'Odoo 19 tools are not installed: %s\n' "$tools/common.sh" >&2
  return 2
fi
source "$tools/common.sh"
