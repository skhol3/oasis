#!/usr/bin/env bash
set -Eeuo pipefail

source "$(dirname "${BASH_SOURCE[0]}")/oasis_env.sh"
# Only the entry point and project wrappers set the explicit root (OASIS_PROJECT_ROOT, or the
# legacy ODOO19_PROJECT_ROOT). Never infer it from installed tools.
_project_root=$(oasis_variable PROJECT_ROOT)
if [[ -z "$_project_root" || ! -d "$_project_root" ]]; then
  printf 'OASIS_PROJECT_ROOT must name an existing project directory.\n' >&2
  return 2
fi
_config_output=$(python3 -B "$(dirname "${BASH_SOURCE[0]}")/config.py" "$_project_root") || return $?
unset _project_root
# config.py sets ENTERPRISE_SOURCE only when it is configured: never inherit the caller's.
unset ENTERPRISE_SOURCE
eval "$_config_output"
unset _config_output
# The Odoo series' demo-off options (tools/odoo_versions.py) as words; config.py shell-quoted them.
eval "ODOO_DEMO_OFF_ARGUMENTS=($ODOO_DEMO_OFF_ARGS)"
# Child helpers (test_temp.py -> compact_log_directory) need the checkout to apply the
# linked-worktree log rule and the [tooling].logs directory; test_temp.py (also through gc.py)
# removes filestores under DATA_DIR when [tooling].data_dir is set.
export CHECKOUT_KIND CHECKOUT_SLUG CHECKOUT_MAIN_ROOT LOGS_DIR DATA_DIR

# The single derivation of a checkout's managed database name: the checkout slug goes right
# after the managed prefix (acme_dev_shop_feature_coffee); the main checkout keeps <prefix><rest>.
checkout_database_name() {
  local prefix=$1 rest=$2
  if [[ -n "${CHECKOUT_SLUG:-}" ]]; then
    printf '%s%s_%s\n' "$prefix" "$CHECKOUT_SLUG" "$rest"
  else
    printf '%s%s\n' "$prefix" "$rest"
  fi
}

# A configured test_database belongs to the main checkout's namespace; config.py already
# checked that the slugged name still fits in 56 bytes.
if [[ -n "$TEST_DATABASE" ]]; then
  TEST_DATABASE=$(checkout_database_name "$TEST_PREFIX" "${TEST_DATABASE#"$TEST_PREFIX"}")
fi

# PostgreSQL identifiers hold at most 63 bytes; count bytes, not characters.
database_name_bytes() {
  local LC_ALL=C
  printf '%s\n' "${#1}"
}

compose() {
  docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
}

require_source() {
  if ! python3 -B "$(dirname "${BASH_SOURCE[0]}")/config.py" --release "$ODOO_SOURCE/odoo/release.py" "$ODOO_VERSION"; then
    printf 'Odoo source must declare release %s.\n' "$ODOO_VERSION" >&2
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
  # 3.12 for a profile; a workspace's named environment declares its own (config.py).
  if [[ "$python_version" != "$PYTHON_VERSION" ]]; then
    printf 'Python %s is required; found %s.\n' "$PYTHON_VERSION" "$python_version" >&2
    return 2
  fi
}

require_runtime() {
  local path odoo_version series
  for path in "$PYTHON" "$ODOO_BIN" "$ODOO_CONFIG" "$COMPOSE_FILE" "$ENV_FILE"; do
    if [[ ! -e "$path" ]]; then
      printf 'Missing required local path: %s\n' "$path" >&2
      return 1
    fi
  done
  require_source
  require_python_version
  odoo_version=$("$PYTHON" "$ODOO_BIN" --version 2>/dev/null) || return $?
  # The configured series as a whole number in what odoo-bin --version prints.
  series="(^|[^0-9])${ODOO_VERSION//./\\.}([^0-9]|\$)"
  if [[ ! "$odoo_version" =~ $series ]]; then
    printf 'Odoo runtime %s is required; %s reports: %s.\n' "$ODOO_VERSION" "$ODOO_BIN" "${odoo_version%%$'\n'*}" >&2
    printf 'Point [tooling].community at an Odoo %s source, then check it with %s doctor.\n' \
      "$ODOO_VERSION" "$(program_name)" >&2
    return 2
  fi
}

# The single source of the configuration options of every Odoo command line, set right before
# Odoo starts: "$PYTHON" "$ODOO_BIN" [shell] "${ODOO_CONFIG_ARGUMENTS[@]}" ...
# -c <odoo.conf>, then --addons-path and --data-dir when they apply; the decision is
# odoo_addons_path.config_arguments, which dev_users_runtime.py imports for its in-process
# Odoo configuration. An odoo.conf without addons_path gets one composed from the Enterprise
# source, the checkout's addon roots and the Community addons (every kind of checkout). With
# one, a linked worktree that shares the main checkout's odoo.conf gets that addons_path with
# the main checkout's root replaced by its own root; the main checkout and a project outside
# git keep -c alone. [tooling].data_dir adds --data-dir=<DATA_DIR>. When git failed in a linked
# worktree whose profile sets checkout_slug, config.py reports no main checkout: an odoo.conf
# inside the worktree is used as it is, a shared one with an addons_path is refused.
odoo_config_arguments() {
  local output root roots=()
  while IFS= read -r root; do roots+=("$root"); done <<< "$ADDON_ROOTS"
  output=$(python3 -I -B "$(dirname "${BASH_SOURCE[0]}")/odoo_addons_path.py" --arguments \
    "$ODOO_CONFIG" "${CHECKOUT_KIND:-}" "${CHECKOUT_MAIN_ROOT:-}" "$PROJECT_ROOT" "$ODOO_SOURCE" \
    "${ENTERPRISE_SOURCE:-}" "${DATA_DIR:-}" "${roots[@]}") || return $?
  # odoo_addons_path.py shell-quoted every word.
  eval "ODOO_CONFIG_ARGUMENTS=($output)"
}

# One option of the configured odoo.conf (http_port, gevent_port or http_interface), or nothing.
odoo_conf_option() {
  python3 -I -B "$(dirname "${BASH_SOURCE[0]}")/odoo_addons_path.py" --option "$1" "$ODOO_CONFIG"
}

# This checkout's server record and port probes, outside the repository (tools/runtime_state.py).
runtime_state() {
  python3 -I -B "$(dirname "${BASH_SOURCE[0]}")/runtime_state.py" "$@"
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

# A managed name of this checkout's namespace (prefix, slug, 63 bytes), trash names included:
# the trash commands and the session helpers use it; every other command calls
# require_managed_database_name, which also refuses trash names.
require_namespace_database_name() {
  local database=${1:-}
  require_database_name "$database"
  if [[ "$database" != "$DEV_PREFIX"* && "$database" != "$TEST_PREFIX"* ||
        "$database" == "$DEV_PREFIX" || "$database" == "$TEST_PREFIX" ]]; then
    printf 'Managed databases must use %s<name> or %s<name>: %s\n' "$DEV_PREFIX" "$TEST_PREFIX" "$database" >&2
    return 2
  fi
  if [[ -n "${CHECKOUT_SLUG:-}" ]]; then
    local dev_namespace="$DEV_PREFIX${CHECKOUT_SLUG}_" test_namespace="$TEST_PREFIX${CHECKOUT_SLUG}_"
    if [[ "$database" != "$dev_namespace"* && "$database" != "$test_namespace"* ||
          "$database" == "$dev_namespace" || "$database" == "$test_namespace" ]]; then
      printf 'Databases of checkout %s must use %s<name> or %s<name>: %s\n' \
        "$CHECKOUT_SLUG" "$dev_namespace" "$test_namespace" "$database" >&2
      return 2
    fi
  fi
  if (( $(database_name_bytes "$database") > 63 )); then
    printf 'Database names must be at most 63 bytes: %s\n' "$database" >&2
    return 2
  fi
}

# Trash names (drop-database, tools/trash.py) end in _trash_<YYYYMMDD>_<HHMMSS>: reserved for the
# trash, so no normal command creates, uses or drops one; `trash restore` and `gc --trash` take them.
is_trash_database_name() {
  [[ "${1:-}" =~ _trash_[0-9]{8}_[0-9]{6}$ ]]
}

require_managed_database_name() {
  local database=${1:-}
  require_namespace_database_name "$database"
  if is_trash_database_name "$database"; then
    printf 'Database names ending in _trash_<YYYYMMDD>_<HHMMSS> are reserved for the trash: %s\n' "$database" >&2
    return 2
  fi
}

require_trash_database_name() {
  local database=${1:-}
  require_namespace_database_name "$database"
  if ! is_trash_database_name "$database"; then
    printf 'Not a trash database of this checkout: %s\n' "$database" >&2
    return 2
  fi
}

# Names ending in the disposable run suffix (_r<6 hex>, optionally _update) belong to the
# disposable runs of test-module and verify-module. The commands that create or reuse a
# database for normal work (create-database, install-module, update-module, odoo-shell,
# start -d, init-dev-database, and test-module/verify-module with an explicit or configured
# database) call this guard instead of require_managed_database_name and refuse them;
# drop-database, module-status and gc accept them. The phases of a disposable verify-module
# run (its children) use the run's names: accepted while the parent process holds their live
# run lock in this checkout.
require_working_database_name() {
  local database=${1:-}
  require_managed_database_name "$database"
  if [[ "$database" =~ _r[0123456789abcdef]{6}(_update)?$ ]] &&
      ! runtime_state run-owned "$PROJECT_ROOT" "$database" "$PPID"; then
    printf 'Database names ending in _r<6 hex> are reserved for disposable runs: %s\n' "$database" >&2
    return 2
  fi
}

# A database that gets an _update sibling must leave room for it within 63 bytes.
require_update_sibling_room() {
  local database=$1
  if (( $(database_name_bytes "$database") > 56 )); then
    printf 'Test databases with an _update sibling must be at most 56 bytes: %s\n' "$database" >&2
    return 2
  fi
}

# update-module and odoo-shell operate on existing databases only; they never create one.
require_existing_database() {
  local database=$1
  # Outside the condition, so an unavailable service fails instead of looking missing.
  wait_for_database >/dev/null
  if ! database_exists "$database"; then
    printf 'Database %s does not exist; create it with install-module or create-database.\n' "$database" >&2
    return 2
  fi
}

# Checkouts that share a compose file share its database service: two simultaneous `compose up`
# calls race (Docker's container name conflict), so `up` runs under an exclusive flock of
# that compose file's lock in the user's runtime root (tools/runtime_state.py compose-lock),
# waiting at most 120 s. Once the first caller finished, the next `up` finds the service
# running. The lock descriptor is closed before returning, so Odoo never inherits it.
# OASIS_COMPOSE_LOCK_TIMEOUT (seconds; the legacy ODOO19_COMPOSE_LOCK_TIMEOUT when unset)
# exists for the tests only.
wait_for_database() {
  local lock lock_fd timeout=120 status=0
  if ! command -v flock >/dev/null 2>&1; then
    printf 'WARNING: flock not found; starting the database service without the cross-checkout lock.\n' >&2
    compose up -d --wait --wait-timeout 60 "$DB_SERVICE"
    return
  fi
  local configured
  configured=$(oasis_variable COMPOSE_LOCK_TIMEOUT)
  if [[ "$configured" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
    timeout=$configured
  fi
  lock=$(runtime_state compose-lock "$COMPOSE_FILE") || return $?
  exec {lock_fd}>>"$lock" || return 1
  flock -w "$timeout" "$lock_fd" || status=$?
  if (( status != 0 )); then
    exec {lock_fd}>&-
    if (( status == 1 )); then
      printf 'Timed out waiting for another checkout to start the database service.\n' >&2
    fi
    return 1
  fi
  compose up -d --wait --wait-timeout 60 "$DB_SERVICE" || status=$?
  exec {lock_fd}>&-
  return "$status"
}

run_odoo() {
  odoo_config_arguments || return $?
  "$PYTHON" "$ODOO_BIN" "${ODOO_CONFIG_ARGUMENTS[@]}" "$@"
}

lock_fingerprint_arg() {
  local fingerprint="$REQUIREMENTS_DIR/lock.sha256"
  if [[ "$REQUIREMENTS_DIR" == "$PROJECT_ROOT/"* ]]; then
    fingerprint=${fingerprint#"$PROJECT_ROOT/"}
  fi
  printf '%s\n' "$fingerprint"
}

# Whether lock.sha256 matches the dependency inputs and locks. Its entries are relative to its
# own directory (as oasis migrate writes them, or `sha256sum ... > lock.sha256` run there); a
# legacy lock lists them relative to the project root, so that is checked next.
dependency_locks_current() {
  [[ -f "$REQUIREMENTS_DIR/lock.sha256" ]] || return 1
  if (cd "$REQUIREMENTS_DIR" && sha256sum --check --strict lock.sha256 >/dev/null 2>&1); then
    return 0
  fi
  (cd "$PROJECT_ROOT" && sha256sum --check --strict "$(lock_fingerprint_arg)" >/dev/null 2>&1)
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

# Whether the database exists. A probe that fails ends the command: callers use this as a
# condition, where a failure would otherwise look like a missing database.
database_exists() {
  local database=$1 found
  require_database_name "$database"
  wait_for_database >/dev/null
  if ! found=$(database_psql -Atqc "SELECT 1 FROM pg_database WHERE datname = '$database'"); then
    printf 'Cannot check whether database %s exists.\n' "$database" >&2
    exit 1
  fi
  [[ "$found" == 1 ]]
}

# The state of a module in an existing database: ir_module_module.state, `uninitialized` when
# Odoo never initialized the database, `not_found` when it has no such module. A query that
# fails returns its status: callers run this in a command substitution, where errexit is off.
module_state() {
  local module=$1 database=$2 initialized row
  initialized=$(database_query "$database" -Atqc "SELECT to_regclass('public.ir_module_module') IS NOT NULL") || return $?
  if [[ "$initialized" != t ]]; then
    printf 'uninitialized\n'
    return 0
  fi
  row=$(database_query "$database" -AtF $'\t' -qc "SELECT state, COALESCE(latest_version, '') FROM ir_module_module WHERE name = '$module'") || return $?
  if [[ -z "$row" ]]; then
    printf 'not_found\n'
    return 0
  fi
  printf '%s\n' "${row%%$'\t'*}"
}

list_managed_databases() {
  local dev_like=${DEV_PREFIX//_/\\_} test_like=${TEST_PREFIX//_/\\_}
  wait_for_database >/dev/null
  database_psql -Atqc "SELECT datname FROM pg_database WHERE datname LIKE '$dev_like%' ESCAPE '\\' OR datname LIKE '$test_like%' ESCAPE '\\' ORDER BY datname"
}

managed_database_session_count() {
  local database=$1
  require_namespace_database_name "$database"
  wait_for_database >/dev/null
  database_psql -Atqc "SELECT count(*) FROM pg_stat_activity WHERE datname = '$database' AND pid <> pg_backend_pid()"
}

terminate_managed_database_sessions() {
  local database=$1
  require_namespace_database_name "$database"
  wait_for_database >/dev/null
  database_psql -Atqc "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '$database' AND pid <> pg_backend_pid()" >/dev/null
}

# The size of an existing database in bytes (pg_database_size).
database_size() {
  local database=$1
  require_namespace_database_name "$database"
  database_psql -Atqc "SELECT pg_database_size('$database')"
}

# The comment of a trash database: `oasis-trash original=<name>` names the database it was.
trash_database_comment() {
  local database=$1
  require_trash_database_name "$database"
  database_psql -Atqc "SELECT coalesce(shobj_description(oid, 'pg_database'), '') FROM pg_database WHERE datname = '$database'"
}

# The trash databases under both managed prefixes: <name>\t<size in bytes>\t<comment> per line.
# tools/trash.py keeps the entries of this checkout whose comment matches their name.
list_trash_databases() {
  local dev_like=${DEV_PREFIX//_/\\_} test_like=${TEST_PREFIX//_/\\_}
  wait_for_database >/dev/null
  database_psql -AtF $'\t' -qc "SELECT datname, pg_database_size(oid), coalesce(shobj_description(oid, 'pg_database'), '') FROM pg_database WHERE (datname LIKE '$dev_like%' ESCAPE '\\' OR datname LIKE '$test_like%' ESCAPE '\\') AND datname ~ '_trash_[0-9]{8}_[0-9]{6}\$' ORDER BY datname"
}

# Renames a database and sets its comment in one statement list (one transaction): to the
# trash with `oasis-trash original=<name>`, or back from it with no comment. PostgreSQL refuses
# to rename a database with open sessions or onto an existing name.
rename_managed_database() {
  local from=$1 to=$2 comment
  if is_trash_database_name "$to"; then
    require_managed_database_name "$from"
    require_trash_database_name "$to"
    comment="'oasis-trash original=$from'"
  else
    require_trash_database_name "$from"
    require_managed_database_name "$to"
    comment=NULL
  fi
  wait_for_database >/dev/null
  database_psql -v ON_ERROR_STOP=1 -qc "ALTER DATABASE \"$from\" RENAME TO \"$to\"; COMMENT ON DATABASE \"$to\" IS $comment" >/dev/null
}

# Closes a trash database's sessions and drops it (gc --apply --trash); prints nothing.
drop_trash_database() {
  local database=$1
  require_trash_database_name "$database"
  terminate_managed_database_sessions "$database"
  compose exec -T "$DB_SERVICE" sh -c '
    set -eu
    export PGPASSWORD="$ODOO_DB_PASSWORD"
    exec dropdb --if-exists -U "$ODOO_DB_USER" "$1"
  ' sh "$database"
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

# Disposable test databases (test-module and verify-module without an explicit or configured
# database): <test_prefix>[<slug>_]<module>_r<6 hex>, at most 56 bytes, new for every run and
# dropped at its end (tools/test_temp.py); `gc` drops the ones an interrupted run left behind.
new_disposable_database_name() {
  runtime_state run-name "$(checkout_database_name "$TEST_PREFIX" '')" "$1"
}

require_disposable_database_name() {
  local database=${1:-}
  require_managed_database_name "$database"
  if [[ "$database" != "$TEST_PREFIX"* || ! "$database" =~ _r[0-9a-f]{6}(_update)?$ ]]; then
    printf 'Not a disposable test database: %s\n' "$database" >&2
    return 2
  fi
}

# A disposable database is always new: an existing database of that name is never reused.
require_free_disposable_database() {
  local database=$1
  require_disposable_database_name "$database"
  # Outside the condition, so an unavailable service fails instead of looking free.
  wait_for_database >/dev/null
  if database_exists "$database"; then
    printf 'Disposable test database already exists: %s; it was left as it is.\n' "$database" >&2
    printf 'Run the command again for a new name; %s gc --apply drops what interrupted runs left.\n' \
      "$(program_name)" >&2
    return 2
  fi
}

create_disposable_database() {
  local database=$1
  require_disposable_database_name "$database"
  compose exec -T "$DB_SERVICE" sh -c '
    set -eu
    export PGPASSWORD="$ODOO_DB_PASSWORD"
    exec createdb -U "$ODOO_DB_USER" "$1"
  ' sh "$database"
}

# Closes the database's sessions and drops it (a missing database is fine); prints nothing.
drop_disposable_database() {
  local database=$1
  require_disposable_database_name "$database"
  terminate_managed_database_sessions "$database"
  compose exec -T "$DB_SERVICE" sh -c '
    set -eu
    export PGPASSWORD="$ODOO_DB_PASSWORD"
    exec dropdb --if-exists -U "$ODOO_DB_USER" "$1"
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
