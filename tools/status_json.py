#!/usr/bin/env python3
"""`oasis status --json` (v0.16.0 S3): what is ready, what is missing and the next command, as one JSON object
(docs/servers-and-ports.md#status-as-json), also when a step cannot be read (its detail is `unknown (<reason>)`,
exit 0). It only reads: the configuration (tools/config.py), the environment's pyvenv.cfg, the locks
(tools/locks.py current/state), `docker compose ps` of the database service, this checkout's databases when the
service runs (the query list-databases runs, inside the service), and the server record (tools/runtime_state.py).
It never starts the service: `oasis status` without --json is unchanged.

The checks, in order, each {"ready": bool, "detail": ...}: workspace, environment, locks, database_service,
databases, server; `next` is the command of the first one that is not ready (null when all are), shell-quoted:
  workspace         setup --plan --json (no workspace file), doctor (a configuration that does not load)
  environment/locks bootstrap --apply (doctor for a lock changed by hand or locks that cannot be read)
  database_service  start-database, which starts it (stopped or starting) and names no env file (an agent harness
                    may refuse a command that does; list-databases would start it too, but the policy says it only
                    reads), doctor when it is unhealthy or its state cannot be read
  databases         init-dev-database --plan --json with [development] and a module, else create-database --plan
                    --json: creating a database is the user's decision, its name included (v0.20.0 S5, S6: the plan
                    asks it); doctor when they cannot be read
  server            start
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shlex
import subprocess
import sys

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
import config  # noqa: E402
import locks  # noqa: E402
import runtime_state  # noqa: E402
import trash  # noqa: E402

CHECKS = ('workspace', 'environment', 'locks', 'database_service', 'databases', 'server')
PSQL = ('set -eu\nexport PGPASSWORD="$ODOO_DB_PASSWORD"\n'
        'exec psql -U "$ODOO_DB_USER" -d "$POSTGRES_DB" "$@"\n')
# The database service states whose next command starts it (start-database waits until it is healthy).
STARTS = ('stopped', 'starting')


def compose(values: dict, *arguments: str) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(['docker', 'compose', '--env-file', values['ENV_FILE'], '-f', values['COMPOSE_FILE'],
                               *arguments], capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return None


def service_state(values: dict) -> str:
    """running (and healthy, or without a health check), starting, unhealthy, stopped, or unknown (<reason>), from
    `docker compose ps --format json <service>` (one JSON object per line, or one array of them)."""
    result = compose(values, 'ps', '--format', 'json', values['DB_SERVICE'])
    if result is None or result.returncode != 0:
        return 'unknown (docker compose ps failed)'
    text = result.stdout.strip()
    try:
        rows = json.loads(text) if text.startswith('[') else [json.loads(line) for line in text.splitlines() if line]
    except ValueError:
        return 'unknown (docker compose ps printed no JSON)'
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        return 'unknown (docker compose ps printed no JSON)'
    health = [row.get('Health') for row in rows if row.get('State') == 'running']
    if any(value in (None, '', 'healthy') for value in health):
        return 'running'
    if 'starting' in health:
        return 'starting'
    return 'unhealthy' if health else 'stopped'


def databases(values: dict, root: Path) -> list[str] | str:
    """This checkout's managed databases (the names list-databases lists), or why they cannot be read."""
    dev, test = values['DEV_PREFIX'], values['TEST_PREFIX']
    like = ' OR '.join(f"datname LIKE '{prefix.replace('_', chr(92) + '_')}%' ESCAPE '{chr(92)}'"
                       for prefix in (dev, test))
    result = compose(values, 'exec', '-T', values['DB_SERVICE'], 'sh', '-c', PSQL, 'sh', '-Atqc',
                     f'SELECT datname FROM pg_database WHERE {like} ORDER BY datname')
    if result is None or result.returncode != 0:
        return 'the database query failed'
    try:
        slug, slugs = values.get('CHECKOUT_SLUG', ''), trash.gc.checkout_slugs(root)
    except (OSError, ValueError) as exc:
        return str(exc)
    return [name for name in (line.strip() for line in result.stdout.splitlines())
            if name and trash.owned(name, dev, test, slug, slugs)]


def first_module(values: dict) -> str | None:
    for addon_root in values['ADDON_ROOTS'].splitlines():
        try:
            found = sorted(path.parent.name for path in Path(addon_root).glob('*/__manifest__.py'))
        except OSError:
            continue
        if found:
            return found[0]
    return None


def report(root: Path) -> dict:
    program = [config.program_name(), '--project', str(root)]

    def command(*words: str) -> str:
        return shlex.join([*program, *words])
    checks = {name: {'ready': False, 'detail': 'needs the workspace'} for name in CHECKS}

    def done(next_command):
        ready = [name for name in CHECKS if checks[name]['ready']]
        return {'project': str(root), 'ready': ready, 'missing': [name for name in CHECKS if name not in ready],
                'checks': checks, 'next': next_command}
    try:
        workspace = config.workspace_file(root)
    except OSError as exc:
        checks['workspace']['detail'] = f'unknown ({exc})'
        return done(command('doctor'))
    if workspace is None:
        checks['workspace']['detail'] = f'no {config.WORKSPACE_NAME} at or above {root}'
        return done(command('setup', '--plan', '--json'))
    try:
        values = config.load(root)
    except config.InvalidConfig as exc:
        checks['workspace']['detail'] = str(exc)
        return done(command('doctor'))
    except OSError as exc:
        checks['workspace']['detail'] = f'unknown ({exc})'
        return done(command('doctor'))
    checks['workspace'] = {'ready': True, 'detail': str(workspace)}
    environment = Path(values['PROJECT_ENVIRONMENT'])
    checks['environment'] = {'ready': (environment / 'pyvenv.cfg').is_file() and os.access(values['PYTHON'], os.X_OK),
                             'detail': str(environment)}
    requirements = Path(values['REQUIREMENTS_DIR'])
    try:
        current = locks.current(requirements, Path(values['PROJECT_ROOT']))
        state = 'current' if current else locks.state(requirements, Path(values['PROJECT_ROOT']))
    except (OSError, ValueError) as exc:
        current, state = False, f'unknown ({exc})'
    checks['locks'] = {'ready': current, 'detail': state}
    service = service_state(values)
    checks['database_service'] = {'ready': service == 'running', 'detail': service}
    if service == 'running':
        found = databases(values, root)
        checks['databases'] = ({'ready': False, 'detail': f'unknown ({found})'} if isinstance(found, str)
                               else {'ready': any(name.startswith(values['DEV_PREFIX']) for name in found),
                                     'detail': found})
    else:
        checks['databases'] = {'ready': False, 'detail': f'unknown while the database service is {service}'}
    try:
        record = runtime_state.live_record(str(root))
        checks['server'] = ({'ready': True, 'detail': f'running pid {record["pid"]} port {record["port"]}'} if record
                            else {'ready': False, 'detail': 'stopped'})
    except (OSError, ValueError, runtime_state.StateError) as exc:
        checks['server'] = {'ready': False, 'detail': f'unknown ({exc})'}
    if not checks['environment']['ready'] or not current:
        return done(command('doctor') if state == 'edited' or state.startswith('unknown')
                    else command('bootstrap', '--apply'))
    if not checks['database_service']['ready']:
        return done(command('start-database') if service in STARTS else command('doctor'))
    if not checks['databases']['ready']:
        if isinstance(checks['databases']['detail'], str):
            return done(command('doctor'))
        # v0.20.0 S5, S6: the plan asks the user the name (and the kind, the module, the demo data); none is chosen here.
        try:
            development = isinstance(config.read_toml(workspace).get('development'), dict)
        except config.InvalidConfig:
            development = False
        if development and first_module(values) is not None:
            return done(command('init-dev-database', '--plan', '--json'))
        return done(command('create-database', '--plan', '--json'))
    return done(None if checks['server']['ready'] else command('start'))


def main(arguments: list[str]) -> int:
    root = config.selected_root()
    if arguments != ['--json'] or root is None:
        print(f'Usage: {config.usage_name()} status [--json]', file=sys.stderr)
        return 2
    print(json.dumps(report(root)))
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
