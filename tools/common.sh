#!/usr/bin/env bash
set -Eeuo pipefail

# Only project wrappers set the explicit root. Never infer it from installed tools.
if [[ -z ${ODOO19_PROJECT_ROOT:-} || ! -d ${ODOO19_PROJECT_ROOT:-} ]]; then
  printf 'ODOO19_PROJECT_ROOT must name an existing project directory.\n' >&2
  return 2
fi
_config_output=$(python3 -B "$(dirname "${BASH_SOURCE[0]}")/config.py" "$ODOO19_PROJECT_ROOT") || return $?
eval "$_config_output"
unset _config_output

compose() {
  docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
}

require_source() {
  if ! python3 -B "$(dirname "${BASH_SOURCE[0]}")/config.py" --release "$ODOO_SOURCE/odoo/release.py"; then
    printf 'Odoo source must declare release 19.0.\n' >&2
    return 2
  fi
}

require_python_version() {
  local python_version
  if [[ ! -e "$PYTHON" ]]; then
    printf 'Missing required local path: %s\n' "$PYTHON" >&2
    return 1
  fi
  python_version=$("$PYTHON" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")') || return $?
  if [[ "$python_version" != 3.12 ]]; then
    printf 'Python 3.12 is required; found %s.\n' "$python_version" >&2
    return 2
  fi
}

require_runtime() {
  local path odoo_version
  for path in "$PYTHON" "$ODOO_BIN" "$ODOO_CONFIG" "$COMPOSE_FILE" "$ENV_FILE"; do
    if [[ ! -e "$path" ]]; then
      printf 'Missing required local path: %s\n' "$path" >&2
      return 1
    fi
  done
  require_source
  require_python_version
  odoo_version=$("$PYTHON" "$ODOO_BIN" --version 2>/dev/null) || return $?
  if [[ ! "$odoo_version" =~ (^|[^0-9])19\.0([^0-9]|$) ]]; then
    printf 'Odoo runtime 19.0 is required.\n' >&2
    return 2
  fi
}

require_module() {
  local module=${1:-} root
  if [[ -z "$module" || ! "$module" =~ ^[A-Za-z0-9_]+$ ]]; then
    printf 'Module must use only letters, numbers, and underscores.\n' >&2
    return 2
  fi
  while IFS= read -r root; do
    if [[ -f "$root/$module/__manifest__.py" ]]; then return 0; fi
  done <<< "$ADDON_ROOTS"
  printf 'Module not found in this repository: %s\n' "$module" >&2
  return 2
}

require_database_name() {
  local database=${1:-}
  if [[ -z "$database" || ! "$database" =~ ^[A-Za-z0-9_]+$ ]]; then
    printf 'Database name must use only letters, numbers, and underscores.\n' >&2
    return 2
  fi
}

require_managed_database_name() {
  local database=${1:-}
  require_database_name "$database"
  if [[ "$database" != "$DEV_PREFIX"* && "$database" != "$TEST_PREFIX"* ||
        "$database" == "$DEV_PREFIX" || "$database" == "$TEST_PREFIX" ]]; then
    printf 'Managed databases must use %s<name> or %s<name>: %s\n' "$DEV_PREFIX" "$TEST_PREFIX" "$database" >&2
    return 2
  fi
}

wait_for_database() {
  compose up -d --wait --wait-timeout 60 "$DB_SERVICE"
}

run_odoo() {
  "$PYTHON" "$ODOO_BIN" -c "$ODOO_CONFIG" "$@"
}

lock_fingerprint_arg() {
  local fingerprint="$REQUIREMENTS_DIR/lock.sha256"
  if [[ "$REQUIREMENTS_DIR" == "$PROJECT_ROOT/"* ]]; then
    fingerprint=${fingerprint#"$PROJECT_ROOT/"}
  fi
  printf '%s\n' "$fingerprint"
}

run_audit() {
  local root
  local args=(--project-root "$PROJECT_ROOT" --requirements-dir "$REQUIREMENTS_DIR")
  while IFS= read -r root; do args+=(--addon-root "$root"); done <<< "$ADDON_ROOTS"
  exec "$PYTHON" "$(dirname "${BASH_SOURCE[0]}")/audit_dependencies.py" "${args[@]}" "$@"
}

database_psql() {
  compose exec -T "$DB_SERVICE" sh -c '
    set -eu
    export PGPASSWORD="$ODOO_DB_PASSWORD"
    exec psql -U "$ODOO_DB_USER" -d "$POSTGRES_DB" "$@"
  ' sh "$@"
}

database_query() {
  local database=$1
  shift
  require_database_name "$database"
  compose exec -T "$DB_SERVICE" sh -c '
    set -eu
    export PGPASSWORD="$ODOO_DB_PASSWORD"
    database=$1
    shift
    exec psql -U "$ODOO_DB_USER" -d "$database" "$@"
  ' sh "$database" "$@"
}

database_exists() {
  local database=$1
  require_database_name "$database"
  wait_for_database >/dev/null
  [[ "$(database_psql -Atqc "SELECT 1 FROM pg_database WHERE datname = '$database'")" == 1 ]]
}

list_managed_databases() {
  local dev_like=${DEV_PREFIX//_/\\_} test_like=${TEST_PREFIX//_/\\_}
  wait_for_database >/dev/null
  database_psql -Atqc "SELECT datname FROM pg_database WHERE datname LIKE '$dev_like%' ESCAPE '\\' OR datname LIKE '$test_like%' ESCAPE '\\' ORDER BY datname"
}

managed_database_session_count() {
  local database=$1
  require_managed_database_name "$database"
  wait_for_database >/dev/null
  database_psql -Atqc "SELECT count(*) FROM pg_stat_activity WHERE datname = '$database' AND pid <> pg_backend_pid()"
}

terminate_managed_database_sessions() {
  local database=$1
  require_managed_database_name "$database"
  wait_for_database >/dev/null
  database_psql -Atqc "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '$database' AND pid <> pg_backend_pid()" >/dev/null
}

ensure_database() {
  local database=$1
  require_database_name "$database"
  wait_for_database
  compose exec -T "$DB_SERVICE" sh -c '
    set -eu
    export PGPASSWORD="$ODOO_DB_PASSWORD"
    if ! psql -U "$ODOO_DB_USER" -d "$POSTGRES_DB" -Atqc "SELECT 1 FROM pg_database WHERE datname = '\''$1'\''" | grep -qx 1; then
      createdb -U "$ODOO_DB_USER" "$1"
    fi
  ' sh "$database"
}

reset_test_database() {
  local database=$1
  require_managed_database_name "$database"
  if [[ "$database" != "$TEST_PREFIX"* ]]; then
    printf 'Refusing to reset database outside the %s namespace: %s\n' "$TEST_PREFIX" "$database" >&2
    return 2
  fi
  wait_for_database >/dev/null
  if database_exists "$database"; then
    local session_count
    session_count=$(managed_database_session_count "$database")
    if (( session_count > 0 )); then
      printf 'Refusing to reset database with %s active session(s): %s\n' "$session_count" "$database" >&2
      printf 'Close those sessions or explicitly drop the database with --terminate.\n' >&2
      return 3
    fi
  fi
  compose exec -T "$DB_SERVICE" sh -c '
    set -eu
    export PGPASSWORD="$ODOO_DB_PASSWORD"
    dropdb --if-exists -U "$ODOO_DB_USER" "$1"
    createdb -U "$ODOO_DB_USER" "$1"
  ' sh "$database"
}
