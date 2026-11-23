#!/usr/bin/env bash
# Sourced by the tools (common.sh sources it too); defines functions only.
# A variable a user, a project wrapper or a test may set is read as OASIS_<NAME> first and as
# the legacy ODOO19_<NAME> when that is unset or empty (tools/config.py variable() in Python).

# oasis_variable <NAME>: the value of OASIS_<NAME>, else of ODOO19_<NAME>, else nothing.
oasis_variable() {
  local name="OASIS_$1" legacy="ODOO19_$1"
  printf '%s' "${!name:-${!legacy:-}}"
}

# What a usage line names: the entry point or project wrapper that ran the tool, else the tool.
usage_name() {
  local entrypoint
  entrypoint=$(oasis_variable ENTRYPOINT)
  printf '%s' "${entrypoint:-$0}"
}

# The program a help or message tells the user to run (`oasis gc`): the invoked entry point,
# `odoo19` through its alias, else `oasis` (also through a project wrapper).
program_name() {
  local entrypoint
  entrypoint=$(oasis_variable ENTRYPOINT)
  if [[ "${entrypoint##*/}" == odoo19 ]]; then
    printf 'odoo19'
  else
    printf 'oasis'
  fi
}
