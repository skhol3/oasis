#!/usr/bin/env bash
# The environment checks (v0.16.0 S5): `doctor --environment [--quick|--full]` runs this file with bash;
# bootstrap --apply ends with `doctor --environment --full`. Its helpers sit next to it: $(dirname "$0") is the
# tools directory.
set -Eeuo pipefail
source "$(dirname "$0")/common.sh"
mode=${1:---quick}
if (( $# > 1 )) || [[ "$mode" != "--quick" && "$mode" != "--full" ]]; then
  printf 'Usage: %s [--quick|--full]\n' "$(usage_name)" >&2
  exit 2
fi
# The environment's Python must be the declared one ($PYTHON_VERSION: the series' default for
# [tooling].environment, else the selected named environment's python). A mismatch stops here,
# with the same first line as require_runtime and how to fix it.
if [[ -x "$PYTHON" ]] \
    && found_python=$("$PYTHON" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null) \
    && [[ "$found_python" != "$PYTHON_VERSION" ]]; then
  printf 'Python %s is required; found %s.\n' "$PYTHON_VERSION" "$found_python" >&2
  printf 'Move %s away and run %s bootstrap --apply to recreate it with Python %s.\n' \
    "$PROJECT_ENVIRONMENT" "$(program_name)" "$PYTHON_VERSION" >&2
  exit 2
fi
require_runtime
requirements_dir="$REQUIREMENTS_DIR"
required_files=(
  "$requirements_dir/runtime.in"
  "$requirements_dir/runtime.txt"
  "$requirements_dir/dev.in"
  "$requirements_dir/dev.txt"
  "$requirements_dir/lock.sha256"
)
failures=0
pass() { printf 'PASS %s\n' "$1"; }
fail() { printf 'FAIL %s\n' "$1" >&2; failures=$((failures + 1)); }
for path in "${required_files[@]}"; do
  if [[ -f "$path" ]]; then pass "file:${path#$PROJECT_ROOT/}"
  else fail "missing_file:${path#$PROJECT_ROOT/}"
  fi
done
python_version=$("$PYTHON" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
if [[ "$python_version" == "$PYTHON_VERSION" ]]; then pass "python_version=$python_version"
else fail "python_version=$python_version expected=$PYTHON_VERSION"
fi
venv_prefix=$("$PYTHON" -c 'import sys; print(sys.prefix)')
if [[ "$venv_prefix/bin/python" -ef "$PYTHON" ]]; then pass "virtualenv=$venv_prefix"
else fail "virtualenv_prefix_mismatch=$venv_prefix"
fi
if command -v uv >/dev/null 2>&1; then pass "uv=$(uv --version | awk '{print $2}')"
else fail "uv=missing"
fi
odoo_version=$("$PYTHON" "$ODOO_BIN" --version 2>/dev/null || true)
if [[ "$odoo_version" == *"$ODOO_VERSION"* ]]; then pass "odoo_version=$ODOO_VERSION"
else fail "odoo_version=${odoo_version:-unavailable} expected=$ODOO_VERSION"
fi
# An overrides.txt next to the inputs (v0.15.0 S7) must be recorded in lock.sha256 too, which
# `sha256sum --check` alone cannot require (tools/locks.py recorded).
if dependency_locks_current && { [[ ! -f "$requirements_dir/overrides.txt" ]] \
    || python3 -I -B "$(dirname "$0")/locks.py" recorded "$requirements_dir"; }; then
  pass "dependency_locks=current"
else fail "dependency_locks=stale_or_modified"
fi
if compose config -q >/dev/null 2>&1; then pass "compose_config=valid"
else fail "compose_config=invalid"
fi
# An account variable Odoo would get from the env file, written with compose interpolation or a double-quoted
# escape, which oasis does not read (tools/db_account.py unsupported): a FAIL naming the file and the variable,
# never its value; the connection is then not tried with another credential.
account_helper="$(dirname "$0")/db_account.py"
unsupported=$(python3 -I -B "$account_helper" unsupported "$ODOO_CONFIG" "$ENV_FILE" 2>/dev/null) || true
if [[ -n "$unsupported" ]]; then
  printf '%s\n' "$unsupported" >&2
  failures=$((failures + 1))
fi
if [[ "$mode" == "--full" ]]; then
  if uv pip check --python "$PYTHON"; then pass "package_compatibility=valid"
  else fail "package_compatibility=invalid"
  fi
  # A drift (exit 3, tools/check_environment.py DRIFT_EXIT) of an adopted environment, one oasis did not create
  # (tools/environment_origin.py), is a WARN naming the command that would sync it, never a failure (v0.17.0 S1):
  # oasis does not change it. An environment oasis created, a lock it cannot read (exit 2) or a crash of the
  # comparison (a traceback, exit 1) stays a FAIL.
  locked=0
  "$PYTHON" "$(dirname "$0")/check_environment.py" "$requirements_dir/dev.txt" || locked=$?
  if (( locked == 0 )); then pass "locked_environment=exact"
  elif (( locked == 3 )) && ! python3 -I -B "$(dirname "$0")/environment_origin.py" created "$PROJECT_ENVIRONMENT"; then
    printf 'WARN locked_environment=drifted\n'
    printf '  fix: %s (syncs the adopted environment %s to the locks: it changes the packages installed there)\n' \
      "$(confirm_command bootstrap --apply)" "$PROJECT_ENVIRONMENT"
  else fail "locked_environment=drifted"  # tools/bootstrap reads this line (doctor_drift_line)
  fi
  if "$(dirname "$0")/audit-dependencies"; then pass "dependency_audit=clean"
  else fail "dependency_audit=failed"
  fi
  running=false
  if compose ps --status running --services | grep -qx "$DB_SERVICE"; then
    running=true
    pass "postgres_service=running"
  else
    fail "postgres_service=not_running"
    # The oasis command that starts it, which names no env file (v0.16.0 S6).
    printf '  fix: %s\n' "$(confirm_command setup-postgres)" >&2
  fi
  if "$running" && [[ -z "$unsupported" ]]; then
    # Odoo's own account over the connection odoo.conf names, with the environment's Python and
    # psycopg2 (tools/db_account.py probe): one word, never a value or the server's message. A word
    # the probe does not print (an error of the environment's Python) is reported as unchecked.
    connection=$("$PYTHON" -I -B "$account_helper" probe "$ODOO_CONFIG" "$ENV_FILE" 2>/dev/null || true)
    case "$connection" in
      ready|authentication_failed|not_running|no_driver|failed) ;;
      *) connection=unchecked ;;
    esac
    if [[ "$connection" == ready ]]; then pass "postgres_connection=ready"
    else
      fail "postgres_connection=$connection"
      if [[ "$connection" == authentication_failed ]]; then
        printf '  fix: %s\n' "$(python3 -I -B "$account_helper" fix "$ODOO_CONFIG" "$ENV_FILE" "$COMPOSE_FILE" \
          "$(program_name)" "$PROJECT_ROOT")" >&2
      fi
    fi
  fi
else
  printf 'SKIP locked_environment=use_--full\n'
  printf 'SKIP dependency_audit=use_--full\n'
  printf 'SKIP postgres_connection=use_--full\n'
fi
printf 'environment_mode=%s\n' "${mode#--}"
printf 'environment_failures=%s\n' "$failures"  # tools/bootstrap reads it (doctor_summary_pattern)
exit "$((failures > 0))"
