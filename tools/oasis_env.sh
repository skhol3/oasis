#!/usr/bin/env bash
# Sourced by the tools (common.sh sources it too); defines functions only.
# A variable a user, a project wrapper or a test may set is read as OASIS_<NAME> only (tools/config.py
# variable() in Python).

# oasis_variable <NAME>: the value of OASIS_<NAME>, else nothing.
oasis_variable() {
  local name="OASIS_$1"
  printf '%s' "${!name:-}"
}

# What a usage line names: the entry point or project wrapper that ran the tool, else the tool.
usage_name() {
  local entrypoint
  entrypoint=$(oasis_variable ENTRYPOINT)
  printf '%s' "${entrypoint:-$0}"
}

# The program a help or message tells the user to run (`oasis gc`): `oasis`, also through a
# project wrapper or an entry point under another file name.
program_name() {
  printf 'oasis'
}
