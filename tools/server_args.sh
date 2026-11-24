#!/usr/bin/env bash
# Sourced by start and restart after common.sh; defines functions only. What both read from the
# Odoo options of a server and how they check its port, so restart refuses before it stops the
# running server whatever start would refuse.

# parse_server_arguments <odoo option>...: guards every database odoo-bin would receive (optparse's
# unambiguous abbreviations of --database included) and sets
#   explicit_port       the value of -p, -p<port>, --http-port <port> or --http-port=<port> (last wins)
#   interface_given     true when --http-interface, or an unambiguous prefix of it down to --http-i,
#                       is given (with `=<address>` or as a separate word), as Odoo's optparse reads it
#   explicit_interface  its address
#   explicit_database   the last database given (-d, --database and their forms), or empty
#   explicit_gevent     true when the series' second port option is given
#   informational       true for -h, --help or --version
#   batch               true for --stop-after-init
# Nothing after `--` is read.
parse_server_arguments() {
  local arguments=("$@") index
  explicit_port='' explicit_interface='' explicit_database=''
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

# probe <first> <last> [<excluded>...]: sets found to the first port free on $interface, returns 1
# when none. Any other bind failure exits 2 with runtime_state.py's `Cannot bind port <p>: <reason>.`.
probe() {
  local status=0
  found=$(runtime_state port "$interface" "$@") || status=$?
  if (( status == 2 )); then exit 2; fi
  return "$status"
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

# conf_database: the db_name of the configured odoo.conf, or nothing when it sets none (Odoo writes
# False for none) or cannot be read (Odoo then reports the file itself). Read with odoo_addons_path.py
# read_option, the reader of every other odoo.conf option.
conf_database() {
  python3 -I -B - "$(dirname "${BASH_SOURCE[0]}")/odoo_addons_path.py" "$ODOO_CONFIG" 2>/dev/null <<'PYTHON' || true
import importlib.util, sys
spec = importlib.util.spec_from_file_location('oasis_odoo_addons_path', sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
value = (module.read_option(sys.argv[2], 'db_name') or '').strip()
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
