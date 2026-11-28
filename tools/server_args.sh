#!/usr/bin/env bash
# Sourced by start and restart after common.sh; defines functions (and the empty freed_ports) only.
# What both read from the Odoo options of a server, how they check and choose its ports and how
# they print its command line, so restart refuses before it stops the running server whatever start
# would refuse, and restart --print-command prints what start would exec.

# parse_server_arguments <odoo option>...: guards every database odoo-bin would receive (optparse's
# unambiguous abbreviations of --database included) and sets
#   explicit_port       the value of -p, -p<port>, --http-port <port> or --http-port=<port> (last wins)
#   interface_given     true when --http-interface, or an unambiguous prefix of it down to --http-i,
#                       is given (with `=<address>` or as a separate word), as Odoo's optparse reads it
#   explicit_interface  its address
#   explicit_database   the last database given (-d, --database and their forms), or empty
#   explicit_config     the last configuration file given (-c <file>, -c<file>, --config <file>, --config=<file> and
#                       the unambiguous prefixes of --config down to --c), or empty: Odoo reads that one instead of
#                       the odoo.conf start passes first (optparse keeps the last value)
#   explicit_gevent     true when the series' second port option is given
#   informational       true for -h, --help or --version
#   batch               true for --stop-after-init
# Nothing after `--` is read.
parse_server_arguments() {
  local arguments=("$@") index
  explicit_port='' explicit_interface='' explicit_database='' explicit_config=''
  interface_given=false explicit_gevent=false informational=false batch=false
  for (( index = 0; index < ${#arguments[@]}; index++ )); do
    case ${arguments[index]} in
      --) break ;;
      -d|--datab|--databa|--databas|--database)
        require_working_database_name "${arguments[index + 1]:-}"
        explicit_database=${arguments[index + 1]}
        (( index += 1 )) ;;
      -d*)
        require_working_database_name "${arguments[index]#-d}"
        explicit_database=${arguments[index]#-d} ;;
      --datab=*|--databa=*|--databas=*|--database=*)
        require_working_database_name "${arguments[index]#*=}"
        explicit_database=${arguments[index]#*=} ;;
      -c|--c|--co|--con|--conf|--confi|--config)
        explicit_config=${arguments[index + 1]:-}
        (( index += 1 )) ;;
      -c*) explicit_config=${arguments[index]#-c} ;;
      --c=*|--co=*|--con=*|--conf=*|--confi=*|--config=*) explicit_config=${arguments[index]#*=} ;;
      -p|--http-port)
        explicit_port=${arguments[index + 1]:-}
        (( index += 1 )) ;;
      -p*) explicit_port=${arguments[index]#-p} ;;
      --http-port=*) explicit_port=${arguments[index]#*=} ;;
      --http-i|--http-in|--http-int|--http-inte|--http-inter|--http-interf|--http-interfa|--http-interfac|\
      --http-interface)
        interface_given=true
        explicit_interface=${arguments[index + 1]:-}
        (( index += 1 )) ;;
      --http-i=*|--http-in=*|--http-int=*|--http-inte=*|--http-inter=*|--http-interf=*|--http-interfa=*|\
      --http-interfac=*|--http-interface=*)
        interface_given=true
        explicit_interface=${arguments[index]#*=} ;;
      "$ODOO_SECOND_PORT_OPTION") explicit_gevent=true; (( index += 1 )) ;;
      "$ODOO_SECOND_PORT_OPTION"=*) explicit_gevent=true ;;
      -h|--help|--version) informational=true ;;
      --stop-after-init) batch=true ;;
    esac
  done
}

# The address Odoo binds: an explicit --http-interface wins over the conf's http_interface.
server_interface() {
  if "$interface_given"; then
    printf '%s\n' "$explicit_interface"
  else
    odoo_conf_option http_interface
  fi
}

# valid_port <value>: whether it is a port number (1-65535).
valid_port() {
  [[ "$1" =~ ^[0-9]{1,5}$ ]] && (( 10#$1 >= 1 && 10#$1 <= 65535 ))
}

# The ports of the running server that restart --print-command counts as free, because restart
# stops that server before start probes them; empty for every other command.
freed_ports=()

# probe <first> <last> [<excluded>...]: sets found to the first port free on $interface, returns 1
# when none. Any other bind failure exits 2 with runtime_state.py's `Cannot bind port <p>: <reason>.`.
# A port of freed_ports in the range, not excluded, counts as free.
probe() {
  local status=0 candidate excluded
  found=$(runtime_state port "$interface" "$@") || status=$?
  if (( status == 2 )); then exit 2; fi
  for candidate in "${freed_ports[@]}"; do
    if (( candidate < $1 || candidate > $2 )); then continue; fi
    for excluded in "${@:3}"; do
      if (( candidate == excluded )); then continue 2; fi
    done
    if (( status != 0 || candidate < found )); then
      found=$candidate status=0
    fi
  done
  return "$status"
}

# choose_server_ports: start's port rules for a server (not a batch run); $interface must be set.
# Sets port (the HTTP port) and port_arguments (what start adds: --http-port=<port> unless one is
# given, and a linked worktree's free second port unless one is given); refuses with exit 2.
choose_server_ports() {
  local conf_port second_option second_port
  port_arguments=()
  if [[ -n "$explicit_port" ]]; then
    if ! valid_port "$explicit_port"; then
      printf 'Invalid HTTP port: %s\n' "$explicit_port" >&2
      exit 2
    fi
    port=$(( 10#$explicit_port ))
    if ! probe "$port" "$port"; then
      busy "$port" 'pass another --http-port'
      exit 2
    fi
  else
    conf_port=$(odoo_conf_option http_port)
    conf_port=${conf_port:-8069}
    if [[ "${CHECKOUT_KIND:-}" == linked ]]; then
      if ! probe $(( conf_port + 1 )) $(( conf_port + 50 )); then
        printf 'No free HTTP port from %s to %s; pass --http-port or stop another server.\n' \
          $(( conf_port + 1 )) $(( conf_port + 50 )) >&2
        exit 2
      fi
      port=$found
    else
      port=$conf_port
      if ! probe "$port" "$port"; then
        busy "$port" 'pass --http-port'
        exit 2
      fi
    fi
    port_arguments+=("--http-port=$port")
  fi
  if [[ "${CHECKOUT_KIND:-}" == linked ]] && ! "$explicit_gevent"; then
    # The series' odoo.conf option of the second port (gevent_port, longpolling_port), named in
    # the refusal by its first word; 8072 is the default of both.
    second_option=$(python3 -I -B "$(dirname "${BASH_SOURCE[0]}")/odoo_versions.py" "$ODOO_VERSION" second_port_conf_option)
    second_port=$(odoo_conf_option "$second_option")
    second_port=${second_port:-8072}
    if ! probe $(( second_port + 1 )) $(( second_port + 50 )) "$port"; then
      printf 'No free %s port from %s to %s; pass %s or stop another server.\n' "${second_option%_port}" \
        $(( second_port + 1 )) $(( second_port + 50 )) "$ODOO_SECOND_PORT_OPTION" >&2
      exit 2
    fi
    port_arguments+=("$ODOO_SECOND_PORT_OPTION=$found")
  fi
}

# running_second_port <pid>: the second (gevent or longpolling) port on the command line of a running
# server ($ODOO_SECOND_PORT_OPTION=<port> or as a separate word, the last one), or nothing, silently,
# when that command line cannot be read (the server ended after its record was read).
running_second_port() {
  local words=() index value=''
  # stderr is redirected first, so a failing input redirection prints nothing.
  mapfile -d '' words 2>/dev/null < "/proc/$1/cmdline" || return 0
  for (( index = 0; index < ${#words[@]}; index++ )); do
    case ${words[index]} in
      --) break ;;
      "$ODOO_SECOND_PORT_OPTION") value=${words[index + 1]:-}; (( index += 1 )) ;;
      "$ODOO_SECOND_PORT_OPTION"=*) value=${words[index]#*=} ;;
    esac
  done
  if valid_port "$value"; then printf '%s\n' $(( 10#$value )); fi
}

# print_server_command <word>...: the command line as one POSIX shell-quoted line (Python's
# shlex.join) on stdout, for start --print-command and restart --print-command. The values of the
# password options (-w, --db_password, --smtp-password and their unambiguous abbreviations from
# --db_pa and --smtp-pa, as Odoo's optparse reads them) are printed as ***; nothing after `--`.
print_server_command() {
  python3 -I -B - "$@" <<'PYTHON'
import shlex, sys
SECRETS = (('--db_pa', '--db_password'), ('--smtp-pa', '--smtp-password'))

def secret(option):
    return option == '-w' or any(len(option) >= len(shortest) and full.startswith(option)
                                 for shortest, full in SECRETS)

words, shown, index = sys.argv[1:], [], 0
while index < len(words):
    word = words[index]
    if word == '--':
        shown.extend(words[index:])
        break
    name, equals, _ = word.partition('=')
    if secret(word) and index + 1 < len(words):
        shown.extend([word, '***'])
        index += 1
    elif equals and name.startswith('--') and secret(name):
        shown.append(f'{name}=***')
    elif word.startswith('-w') and len(word) > 2:
        shown.append('-w***')
    else:
        shown.append(word)
    index += 1
print(shlex.join(shown))
PYTHON
}

# busy <port> <what to pass>: why the port is busy and what to do. A live record of another
# checkout on that port names its checkout (runtime_state others); otherwise it is another process.
busy() {
  local port=$1 pass=$2 line
  while IFS= read -r line; do
    if [[ "$line" =~ ^(.*)\ \(port\ ([0-9]+),\ pid\ ([0-9]+)\)$ && "${BASH_REMATCH[2]}" == "$port" ]]; then
      printf 'Port %s is in use by checkout %s (pid %s); %s or run %s stop in that checkout.\n' \
        "$port" "${BASH_REMATCH[1]}" "${BASH_REMATCH[3]}" "$pass" "$(program_name)" >&2
      return
    fi
  done < <(runtime_state others "$PROJECT_ROOT" 2>/dev/null || true)
  printf 'Port %s is in use by another process; %s or stop that process.\n' "$port" "$pass" >&2
}

# configuration_reads_environment: the series' answer in tools/odoo_versions.py (true or false, with the Odoo
# source lines): whether -d reads PGDATABASE (after the command line, before the configuration file) and whether -c
# expands variables and ~. A table that cannot be read prints one WARNING and answers "unknown".
configuration_reads_environment() {
  local answer
  answer=$(python3 -I -B "$(dirname "${BASH_SOURCE[0]}")/odoo_versions.py" "$ODOO_VERSION" \
    configuration_reads_environment 2>/dev/null) || answer=
  case "$answer" in
    true | false) printf '%s\n' "$answer" ;;
    *)
      printf 'WARNING: cannot read configuration_reads_environment of Odoo %s from tools/odoo_versions.py; checking PGDATABASE too.\n' \
        "${ODOO_VERSION:-?}" >&2
      printf 'unknown\n' ;;
  esac
}

# odoo_reads_pgdatabase: fails closed, only an explicit false skips PGDATABASE (the check covers more, never less).
odoo_reads_pgdatabase() {
  [[ "$(configuration_reads_environment)" != false ]]
}

# odoo_expands_config_path: only an explicit true expands the -c path; unknown keeps it as given.
odoo_expands_config_path() {
  [[ "$(configuration_reads_environment)" == true ]]
}

# conf_database [<file>]: the db_name of that configuration file (the configured odoo.conf by default), or nothing
# when it sets none (Odoo writes False for none) or cannot be read (Odoo then reports the file itself). Read with
# odoo_addons_path.py read_option, the reader of every other odoo.conf option. A path given with -c is expanded as
# the series' Odoo expands it.
conf_database() {
  local expand=''
  if [[ -n "${1:-}" ]] && odoo_expands_config_path; then expand=expand; fi
  python3 -I -B - "$(dirname "${BASH_SOURCE[0]}")/odoo_addons_path.py" "${1:-$ODOO_CONFIG}" "$expand" 2>/dev/null <<'PYTHON' || true
import importlib.util, os.path, sys
spec = importlib.util.spec_from_file_location('oasis_odoo_addons_path', sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
conf = sys.argv[2]
if sys.argv[3]:
    conf = os.path.expanduser(os.path.expandvars(conf.strip()))
value = (module.read_option(conf, 'db_name') or '').strip()
if value and value != 'False':
    print(value)
PYTHON
}

# warn_without_database: a server started without -d serves odoo.conf's db_name; say so on stderr.
warn_without_database() {
  local named
  if [[ -n "$explicit_database" ]]; then return; fi
  named=$(conf_database)
  if [[ -n "$named" ]]; then
    printf "WARNING: no database given (-d); Odoo will use odoo.conf's db_name (%s).\n" "$named" >&2
  fi
}

# database_list <names>: a comma-separated list of databases, one per line, each stripped, empty items left out (as
# Odoo splits db_name and PGDATABASE).
database_list() {
  local name names=()
  IFS=',' read -ra names <<< "$1"
  for name in "${names[@]}"; do
    name=${name#"${name%%[![:space:]]*}"}
    name=${name%"${name##*[![:space:]]}"}
    if [[ -n "$name" ]]; then printf '%s\n' "$name"; fi
  done
}

# server_databases: the databases odoo-bin would open, one per line, from the first source Odoo reads: the one given
# with -d (or a form of it); else, on a series whose -d reads it, PGDATABASE when it is set (oasis never sets it, so it
# is the user's own; set but empty, it is an empty list that hides the file's db_name); else the db_name of the
# configuration file Odoo reads (a later -c/--config among the options, else odoo.conf). Lists are comma-separated.
# None from any source is Odoo's database selector.
server_databases() {
  if [[ -n "$explicit_database" ]]; then
    printf '%s\n' "$explicit_database"
    return
  fi
  if odoo_reads_pgdatabase && [[ -v PGDATABASE ]]; then
    database_list "$PGDATABASE"
    return
  fi
  database_list "$(conf_database "$explicit_config")"
}

# require_existing_server_databases: odoo-bin creates every database it is given that does not exist (odoo/cli/server.py
# of every supported series), so each one server_databases names must exist (common.sh require_existing_database:
# exit 2 naming create-database --plan, the one command that creates a database, v0.20.0 S12). Called right before
# Odoo would start, never for --print-command or Odoo's informational options; without a database nothing is checked.
require_existing_server_databases() {
  local database databases=()
  mapfile -t databases < <(server_databases)
  for database in "${databases[@]}"; do
    require_existing_database "$database" </dev/null
  done
}
