#!/usr/bin/env python3
"""Check the environment contract of a checkout up front, read-only (`oasis doctor`).

One `PASS|WARN|FAIL <check>[=<value>]` line per check on stdout, then `doctor_failures=<n>`;
exit 1 when n > 0, else 0 (a WARN does not count). Every FAIL line is followed by
`  fix: <command or action>`, what fixes it (v0.14.0 S1). After the configuration lines, one
`PASS <value>_from=<origin>` line per layered value says where it came from (`machine:<file>`,
`workspace:<file>`, `checkout:<file>` or `derived`; S2). A workspace_version 2 checkout also gets
`PASS series=<x.y> from=<origin>`, its series exceptions and the isolation of the workspace's
series (v0.15.0 S3, S4). Doctor never starts a service, never
connects to a database and never prints file contents: files are tested for existence or parsed
for the one fact a check needs (the env file: which of the database account's variables are
empty, never their values; module manifests: their series-style version, S11). The only external
programs it runs are `git --version`, `docker compose version` and the environment's Python (its
version); tools are found on PATH, like `command -v`, never through a tool manager.

A check that needs another one is left out when that one failed: every configuration check
when the configuration does not load, `docker_compose` without docker, `http_port` when the
odoo.conf cannot be read.
"""
import ast
import importlib.util
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys

GIT_MINIMUM = (2, 31)
PROBE_TIMEOUT_SECONDS = 20
PYTHON_PROBE = 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")'
# odoo.conf options that oasis passes on the command line for a workspace checkout.
LOCATION_OPTIONS = ('addons_path', 'data_dir')
DEFAULT_HTTP_PORT = 8069
LINKED_PORT_RANGE = 50
TOP_LEVEL_NAME = re.compile(r'''^(?:name|"name"|'name')\s*:(.*)$''')
EMPTY_VALUES = ('', '""', "''", '~', 'null')
# The variables of the database account `oasis setup` writes, empty, to the env file (S7): a FAIL when
# one is assigned an empty value. An env file that does not assign them (other names) is not judged.
ACCOUNT_VARIABLES = ('ODOO_DB_USER', 'ODOO_DB_PASSWORD')
ENV_ASSIGNMENT = re.compile(r'\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)')
# What two series of one workspace may not share (v0.15.0 S3), in report order, with the facts each
# compares: the port the compose file publishes to PostgreSQL, the compose project (its top-level
# name), the database prefixes and the env file (the database account).
ISOLATION = (('db_port', ('db_port',)), ('compose_project', ('compose_project',)),
             ('prefixes', ('dev_prefix', 'test_prefix')), ('env_file', ('env_file',)))


def sibling(name: str):
    """A packaged helper loaded from its file (python3 -I keeps the tools directory off sys.path)."""
    spec = importlib.util.spec_from_file_location(f'oasis_doctor_{name}', Path(__file__).with_name(f'{name}.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Report:
    def __init__(self):
        self.failures = 0

    def line(self, level: str, check: str, value: str = ''):
        print(f'{level} {check}' + (f'={value}' if value else ''))
        return level != 'FAIL'

    def check(self, check: str, value: str = ''):
        return self.line('PASS', check, value)

    def warn(self, check: str, value: str = ''):
        return self.line('WARN', check, value)

    def fail(self, check: str, value: str, fix: str):
        """A FAIL line, then the command or action that fixes it."""
        self.failures += 1
        self.line('FAIL', check, value)
        print(f'  fix: {fix}')
        return False


def probe(argv: list[str]) -> str | None:
    """stdout of a version probe, or None when it cannot run, times out or exits non-zero."""
    try:
        result = subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                                timeout=PROBE_TIMEOUT_SECONDS)
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout if result.returncode == 0 else None


def version_numbers(text: str) -> tuple[int, ...] | None:
    match = re.search(r'(\d+)\.(\d+)(?:\.(\d+))?', text or '')
    return tuple(int(part) for part in match.groups() if part is not None) if match else None


def check_git(report: Report):
    minimum = '.'.join(map(str, GIT_MINIMUM))
    fix = f'install git {minimum} or newer on PATH'
    if shutil.which('git') is None:
        return report.fail('git', 'missing', fix)
    found = version_numbers(probe(['git', '--version']) or '')
    if found is None:
        return report.fail('git', f'unknown minimum={minimum}', fix)
    shown = '.'.join(map(str, found))
    if found[:2] < GIT_MINIMUM:
        return report.fail('git', f'{shown} minimum={minimum}', fix)
    return report.check('git', shown)


def check_docker(report: Report):
    if shutil.which('docker') is None:
        return report.fail('docker', 'missing', 'install Docker with its compose plugin on PATH')
    report.check('docker')
    output = probe(['docker', 'compose', 'version'])
    if output is None:
        return report.fail('docker_compose', 'unavailable',
                           'install the Docker Compose plugin: docker compose version must succeed')
    found = version_numbers(output)
    return report.check('docker_compose', '.'.join(map(str, found)) if found else '')


def check_python(report: Report, values: dict, versions, program: str):
    python, expected = values['PYTHON'], values['PYTHON_VERSION']
    if not os.path.lexists(python):
        return report.fail('python', 'missing', f'{program} bootstrap --apply')
    # bootstrap refuses an existing environment with another Python: it must be moved away first.
    recreate = f'move {values["PROJECT_ENVIRONMENT"]} away, then {program} bootstrap --apply'
    output = probe([python, '-c', PYTHON_PROBE])
    found = (output or '').strip()
    if not found:
        return report.fail('python', 'unavailable', recreate)
    if found != expected or not versions.python_supported(values['ODOO_VERSION'], found):
        return report.fail('python', f'{found} expected={expected}', recreate)
    return report.check('python', found)


def declared_release(path: Path) -> str | None:
    """major.minor of the `version_info` assignment of an Odoo release.py, or None."""
    try:
        tree = ast.parse(path.read_text(encoding='utf-8'))
    except (OSError, UnicodeError, SyntaxError, ValueError):
        return None
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == 'version_info' for target in node.targets):
            value = node.value
            if isinstance(value, (ast.Tuple, ast.List)) and len(value.elts) >= 2 and all(
                    isinstance(item, ast.Constant) and type(item.value) is int for item in value.elts[:2]):
                return f'{value.elts[0].value}.{value.elts[1].value}'
    return None


def check_release(report: Report, values: dict, source_fix: str):
    """source_fix: where to point the community source at the right series (its origin's file)."""
    path = Path(values['ODOO_SOURCE']) / 'odoo' / 'release.py'
    expected = values['ODOO_VERSION']
    if not path.is_file():
        return report.fail('odoo_release', 'missing', source_fix)
    found = declared_release(path)
    if found != expected:
        return report.fail('odoo_release', f'{found or "unknown"} expected={expected}', source_fix)
    return report.check('odoo_release', found)


def check_module_series(report: Report, values: dict, config):
    """One FAIL when a module of the addons paths declares another Odoo series (S11); no line otherwise."""
    mismatch = config.series_mismatch(values)
    if mismatch is None:
        return True
    expected = values['ODOO_VERSION']
    return report.fail('module_series', f'{mismatch["series"]} module={mismatch["module"]} expected={expected}',
                       config.series_fix(mismatch, expected, values))


def series_facts(config, document: dict, workspace: Path, series: str, published_port) -> dict:
    """What ISOLATION compares for one series of the workspace (None when it cannot be read: a missing or
    unreadable compose file leaves its project and port unknown, and the isolation check skips them)."""
    tooling = config.series_tooling(document, workspace, series)

    def path(key):
        value = tooling.get(key)
        return (workspace.parent / value).resolve() if isinstance(value, str) and value and '\x00' not in value else None

    def text(key):
        value = tooling.get(key)
        return value if isinstance(value, str) else None
    compose = path('compose')
    project = port = None
    if compose is not None:
        try:
            project = compose_project(compose)
        except (OSError, UnicodeError):
            pass
        try:
            port = published_port(compose)
        except (OSError, UnicodeError):
            pass
    return {'compose': compose, 'config': path('config'), 'compose_project': project, 'db_port': port,
            'dev_prefix': text('dev_prefix'), 'test_prefix': text('test_prefix'), 'env_file': path('env_file')}


def isolation_fix(check: str, group: list[str], facts: dict, workspace: Path) -> str:
    """How to give the series of group after the first their own value of check."""
    others = group[1:]
    sections = ' and '.join(f'[series."{series}"]' for series in others)
    if check in ('db_port', 'compose_project') and len({facts[series]['compose'] for series in group}) == 1:
        return f'set compose under {sections} in {workspace} to a compose file of its own'
    composes = ' and '.join(str(facts[series]['compose']) for series in others)
    if check == 'db_port':
        confs = ' and '.join(str(facts[series]['config']) for series in others)
        return f'publish another port to 5432 in {composes} and set db_port in {confs} to it'
    if check == 'compose_project':
        return f'set another top-level name: in {composes}'
    if check == 'prefixes':
        return f'set dev_prefix and test_prefix under {sections} in {workspace} to a pair of its own'
    return f'set env_file under {sections} in {workspace} to a file of its own'


def check_series_isolation(report: Report, values: dict, config):
    """A version 2 workspace with several series: one FAIL per group of series that share what ISOLATION
    names, else `PASS series_isolation=<series>`; no line for one series or version 1."""
    if values.get('WORKSPACE_VERSION') != '2':
        return True
    workspace = Path(values['WORKSPACE_ROOT']) / config.WORKSPACE_NAME
    try:
        document = config.checked_workspace(workspace)
    except ValueError:
        return True
    names = config.declared_series(document, workspace)
    if len(names) < 2:
        return True
    published_port = sibling('setup').published_port
    facts = {series: series_facts(config, document, workspace, series, published_port) for series in names}
    passed = True
    for check, keys in ISOLATION:
        groups = []
        for key in keys:
            shared = {}
            for series in names:
                if facts[series][key] is not None:
                    shared.setdefault(facts[series][key], []).append(series)
            groups += [group for group in shared.values() if len(group) > 1 and group not in groups]
        for group in groups:
            passed = report.fail('series_isolation', f'{check} series={",".join(group)}',
                                 isolation_fix(check, group, facts, workspace)) and passed
    if passed:
        report.check('series_isolation', ','.join(names))
    return passed


def show_series(report: Report, values: dict, found: dict, config):
    """A version 2 checkout: its series and where it came from, its exceptions and the isolation."""
    if values.get('WORKSPACE_VERSION') != '2':
        return
    report.check('series', f'{values["ODOO_VERSION"]} from={found.get("ODOO_VERSION_FROM", "")}')
    if values['SERIES_EXCEPTIONS']:
        report.check('series_exceptions', ','.join(values['SERIES_EXCEPTIONS'].splitlines()))
    check_series_isolation(report, values, config)


def check_conf(report: Report, values: dict, conf_reader, program: str):
    """odoo.conf exists and parses, and holds no location options (oasis passes them)."""
    conf = values['ODOO_CONFIG']
    if not os.path.exists(conf):
        return report.fail('odoo_conf', 'missing', f'{program} setup --apply')
    try:
        present = [option for option in LOCATION_OPTIONS if conf_reader.read_option(conf, option) is not None]
    except conf_reader.ConfError as exc:
        if isinstance(exc.__cause__, OSError):
            return report.fail('odoo_conf', 'unreadable', f'make {conf} readable by you')
        return report.fail('odoo_conf', 'invalid', f'correct the syntax of {conf}')
    if present:
        return report.warn('odoo_conf', ','.join(present))
    return report.check('odoo_conf')


def compose_project(path: Path) -> str | None:
    """The top-level `name:` of a compose file (quotes removed), None without a non-empty one; raises
    OSError or UnicodeError when it cannot be read."""
    for line in path.read_text(encoding='utf-8').splitlines():
        match = TOP_LEVEL_NAME.match(line)
        if match:
            value = re.sub(r'\s+#.*$', '', match.group(1)).strip()
            if value not in EMPTY_VALUES:
                return value.strip('\'"')
    return None


def check_compose(report: Report, values: dict, program: str):
    """The compose file declares a top-level `name:`, so every checkout shares one project name."""
    path = Path(values['COMPOSE_FILE'])
    if not path.exists():
        return report.fail('compose', 'missing', f'{program} setup --apply')
    try:
        project = compose_project(path)
    except (OSError, UnicodeError):
        return report.fail('compose', 'unreadable', f'make {path} readable by you')
    if project is not None:
        return report.check('compose')
    return report.fail('compose', 'missing_top_level_name', f'add a top-level name: to {path}')


def empty_value(raw: str) -> bool:
    """Whether an env file value is empty: nothing, `""` or `''`, before an optional ` # comment`."""
    return re.sub(r'\s+#.*$', '', raw).strip() in ('', '""', "''")


def check_env_file(report: Report, values: dict, program: str):
    """The env file exists, can be read, and assigns no empty value to ACCOUNT_VARIABLES (S7). Only
    the variable names are ever printed, never a value or a line of the file."""
    path = values['ENV_FILE']
    if not os.path.exists(path):
        return report.fail('env_file', 'missing', f'{program} setup --apply')
    try:
        text = Path(path).read_bytes().decode('utf-8', errors='replace')
    except OSError:
        return report.fail('env_file', 'unreadable', f'make {path} readable by you')
    empty = {}
    for line in text.splitlines():
        match = ENV_ASSIGNMENT.fullmatch(line)
        if match and match.group(1) in ACCOUNT_VARIABLES:
            # The last assignment wins, as docker compose reads the file.
            empty[match.group(1)] = empty_value(match.group(2))
    names = [name for name in ACCOUNT_VARIABLES if empty.get(name)]
    if names:
        return report.fail('env_file', 'empty ' + ','.join(names), f'fill {" and ".join(names)} in {path}')
    return report.check('env_file')


def check_writable(report: Report, check: str, directory: Path):
    """The directory, or its nearest existing parent when it does not exist yet, is writable."""
    candidate = directory
    for candidate in (directory, *directory.parents):
        if os.path.lexists(candidate):
            if candidate.is_dir() and os.access(candidate, os.W_OK | os.X_OK):
                return report.check(check)
            break
    return report.fail(check, 'not_writable', f'make {candidate} a directory you can write')


def own_server_port(state, root: str) -> int | None:
    """The port of this checkout's live server record, or None; read-only (runtime_state.py's
    readers would remove a stale record or tighten a directory mode)."""
    directory = state.checkout_dir(root)
    for path in (state.user_root(), directory):
        try:
            info = os.lstat(path)
        except OSError:
            return None
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
            return None
    try:
        seen = state.snapshot(directory / state.RECORD)
    except OSError:
        return None
    if seen is None or seen[0] != 'file':
        return None
    try:
        record = state.parse(seen[1])
    except (ValueError, UnicodeDecodeError, RecursionError):
        return None
    return record['port'] if state.is_live(record) else None


def check_port(report: Report, values: dict, conf_reader, state):
    """The HTTP port `start` would use is free, or is this checkout's running server."""
    conf = values['ODOO_CONFIG']
    try:
        interface = conf_reader.option_value(conf, 'http_interface')
        configured = int(conf_reader.option_value(conf, 'http_port') or DEFAULT_HTTP_PORT)
    except conf_reader.ConfError:
        return report.fail('http_port', 'invalid', f'set http_port in {conf} to a port number')
    own = own_server_port(state, values['PROJECT_ROOT'])
    linked = values.get('CHECKOUT_KIND') == 'linked'
    if own is not None and (linked or own == configured):
        return report.check('http_port', f'{own} server=this_checkout')
    try:
        if linked:
            first, last = configured + 1, configured + LINKED_PORT_RANGE
            port = state.free_port(interface, first, last, set())
            if port is None:
                return report.warn('http_port', f'{first}-{last} in_use')
            return report.check('http_port', str(port))
        if not state.port_is_free(interface, configured):
            return report.warn('http_port', f'{configured} in_use')
    except state.PortError:
        return report.warn('http_port', f'{configured} cannot_bind')
    return report.check('http_port', str(configured))


def usage() -> str:
    return f'Usage: {sibling("config").usage_name()} doctor'


HELP = '''
Checks the environment contract of this checkout, read-only: the configuration (the workspace
file; a legacy profile is one FAIL naming oasis migrate), its agent_destructive setting and where
its layered values came from (machine, workspace or checkout file, or derived), git 2.31 or newer,
docker and `docker compose version`, flock, /proc, the environment's Python, the Odoo source
release, the series of the module manifests, odoo.conf, the compose file's top-level name, the env
file (exists, and the database account's variables are not empty), the logs and data directories,
and the HTTP port. With workspace_version 2: the checkout's series and where it came from, its
series exceptions, and that the workspace's series share no database port, prefixes, compose
project or env file.
Prints PASS|WARN|FAIL <check>[=<value>] per check, `  fix: <command or action>` after each FAIL,
and doctor_failures=<n>; exit 1 when n > 0.
Never starts services, connects to a database or prints file contents or values.
'''


def configuration_fix(config, root: Path, message: str, error: Exception | None = None) -> str:
    """What fixes a configuration that does not load: migrate for a legacy profile, setup for a
    missing workspace file, series section or source, else the setting the error names."""
    program = config.program_name()
    if (root / config.PROFILE_NAME).is_file():
        return f'{program} migrate --plan, then {program} migrate --apply'
    if config.workspace_file(root) is None or isinstance(error, config.MissingSeries):
        return f'{program} setup --apply'
    try:
        refusal = config.layered_configuration(root)[5]
    except ValueError:
        refusal = None
    if refusal is not None and message == ' '.join(refusal.split()):
        return f'{program} setup --apply'
    return f'correct the setting the error names, then run {program} doctor again'


def read_origins(config, root: Path) -> dict:
    """config.py --origins of root (S2), {} when it cannot be read."""
    try:
        return config.origins(root)
    except ValueError:
        return {}


def show_origins(report: Report, config, root: Path, values: dict, found: dict) -> dict:
    """One PASS line per layered value with its origin (read_origins, S2); the origins."""
    if not found:
        return {}
    places = {'machine': f'machine:{found["MACHINE_FILE"]}',
              'workspace': f'workspace:{Path(values["WORKSPACE_ROOT"]) / config.WORKSPACE_NAME}',
              'checkout': f'checkout:{root / config.CHECKOUT_NAME}', 'derived': 'derived'}
    for key in ('ODOO_SOURCE_FROM', 'ENTERPRISE_SOURCE_FROM', 'PROJECT_ENVIRONMENT_FROM', 'CHECKOUT_SLUG_FROM'):
        if found.get(key):
            report.check(key.lower(), places[found[key]])
    return found


def source_fix(values: dict, found: dict, config) -> str:
    """Where to set the community source of the series: the file it came from."""
    series = values['ODOO_VERSION']
    if found.get('ODOO_SOURCE_FROM') == 'machine':
        return (f'set community under [series."{series}"] in {found["MACHINE_FILE"]} to an Odoo {series} '
                'source')
    return (f'set [tooling].community in {Path(values["WORKSPACE_ROOT"]) / config.WORKSPACE_NAME} to an Odoo '
            f'{series} source')


def main(arguments: list[str]) -> int:
    if arguments in (['--help'], ['-h']):
        print(usage() + '\n' + HELP, end='')
        return 0
    if arguments:
        print(usage(), file=sys.stderr)
        return 2
    config = sibling('config')
    root = config.selected_root()
    if root is None:
        print(f'ERROR: {config.PROJECT_ROOT_REQUIRED}', file=sys.stderr)
        return 2
    report = Report()
    program = config.program_name()
    found = {}
    try:
        # The series guard is a check of its own here (module_series), not a configuration failure.
        values = config.load(root, series_guard=False)
    except ValueError as exc:
        values = None
        message = ' '.join(str(exc).split())
        report.fail('configuration', message, configuration_fix(config, root, message, exc))
    else:
        report.check('configuration', 'workspace')
        report.check('odoo_version', values['ODOO_VERSION'])
        found = read_origins(config, root)
        show_series(report, values, found, config)
        report.check('agent_destructive', values['AGENT_DESTRUCTIVE'])
        found = show_origins(report, config, root, values, found)
    check_git(report)
    check_docker(report)
    if shutil.which('flock') is None:
        report.warn('flock', 'missing')
    else:
        report.check('flock')
    if os.path.isdir('/proc/self'):
        report.check('proc')
    else:
        report.warn('proc', 'missing')
    if values is not None:
        conf_reader = sibling('odoo_addons_path')
        check_python(report, values, config.versions(), program)
        check_release(report, values, source_fix(values, found, config))
        check_module_series(report, values, config)
        conf_ok = check_conf(report, values, conf_reader, program)
        check_compose(report, values, program)
        check_env_file(report, values, program)
        logs = Path(values['LOGS_DIR']) if values['LOGS_DIR'] else root / 'dev' / 'logs' / 'odoo19'
        check_writable(report, 'logs_dir', logs)
        if values['DATA_DIR']:
            check_writable(report, 'data_dir', Path(values['DATA_DIR']))
        if conf_ok:
            check_port(report, values, conf_reader, sibling('runtime_state'))
    print(f'doctor_failures={report.failures}')
    return 1 if report.failures else 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
