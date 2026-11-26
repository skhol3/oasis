#!/usr/bin/env bash
# This file is sourced by existing project-local helpers; do not exec a subprocess.
export OASIS_PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
tools=${OASIS_TOOLS_DIR:-$HOME/.agents/skills/oasis/tools}
if [[ ! -f "$tools/common.sh" ]]; then
  printf 'oasis tools are not installed: %s\n' "$tools/common.sh" >&2
  return 2
fi
source "$tools/common.sh"
