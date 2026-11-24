#!/usr/bin/env python3
"""Check the environment contract of a checkout up front, read-only (`oasis doctor`).

One `PASS|WARN|FAIL <check>[=<value>]` line per check on stdout, then `doctor_failures=<n>`;
exit 1 when n > 0, else 0 (a WARN does not count). Doctor never starts a service, never
connects to a database and never prints file contents: files are tested for existence, parsed
for the one fact a check needs, or not opened at all (env_file). The only external programs it
runs are `git --version`, `docker compose version` and the environment's Python (its version);
tools are found on PATH, like `command -v`, never through a tool manager.

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
        if level == 'FAIL':
            self.failures += 1
        return level != 'FAIL'

    def check(self, check: str, value: str = ''):
        return self.line('PASS', check, value)

    def warn(self, check: str, value: str = ''):
        return self.line('WARN', check, value)

    def fail(self, check: str, value: str = ''):
        return self.line('FAIL', check, value)


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
    if shutil.which('git') is None:
        return report.fail('git', 'missing')
    found = version_numbers(probe(['git', '--version']) or '')
    minimum = '.'.join(map(str, GIT_MINIMUM))
    if found is None:
        return report.fail('git', f'unknown minimum={minimum}')
    shown = '.'.join(map(str, found))
    if found[:2] < GIT_MINIMUM:
        return report.fail('git', f'{shown} minimum={minimum}')
    return report.check('git', shown)


def check_docker(report: Report):
    if shutil.which('docker') is None:
        return report.fail('docker', 'missing')
    report.check('docker')
    output = probe(['docker', 'compose', 'version'])
    if output is None:
        return report.fail('docker_compose', 'unavailable')
    found = version_numbers(output)
    return report.check('docker_compose', '.'.join(map(str, found)) if found else '')


def check_python(report: Report, values: dict, versions):
    python, expected = values['PYTHON'], values['PYTHON_VERSION']
    if not os.path.lexists(python):
        return report.fail('python', 'missing')
    output = probe([python, '-c', PYTHON_PROBE])
    found = (output or '').strip()
    if not found:
        return report.fail('python', 'unavailable')
    if found != expected or not versions.python_supported(values['ODOO_VERSION'], found):
        return report.fail('python', f'{found} expected={expected}')
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


def check_release(report: Report, values: dict):
    path = Path(values['ODOO_SOURCE']) / 'odoo' / 'release.py'
    expected = values['ODOO_VERSION']
    if not path.is_file():
        return report.fail('odoo_release', 'missing')
    found = declared_release(path)
    if found != expected:
        return report.fail('odoo_release', f'{found or "unknown"} expected={expected}')
    return report.check('odoo_release', found)


def check_conf(report: Report, values: dict, conf_reader, workspace: bool):
    """odoo.conf exists and parses; a workspace checkout's conf should not hold location options."""
    conf = values['ODOO_CONFIG']
    if not os.path.exists(conf):
        return report.fail('odoo_conf', 'missing')
    try:
        present = [option for option in LOCATION_OPTIONS if conf_reader.read_option(conf, option) is not None]
    except conf_reader.ConfError as exc:
        return report.fail('odoo_conf', 'unreadable' if isinstance(exc.__cause__, OSError) else 'invalid')
    if workspace and present:
        return report.warn('odoo_conf', ','.join(present))
    return report.check('odoo_conf')


def check_compose(report: Report, values: dict):
    """The compose file declares a top-level `name:`, so every checkout shares one project name."""
    path = Path(values['COMPOSE_FILE'])
    if not path.exists():
        return report.fail('compose', 'missing')
    try:
        lines = path.read_text(encoding='utf-8').splitlines()
    except (OSError, UnicodeError):
        return report.fail('compose', 'unreadable')
    for line in lines:
        match = TOP_LEVEL_NAME.match(line)
        if match and re.sub(r'\s+#.*$', '', match.group(1)).strip() not in EMPTY_VALUES:
            return report.check('compose')
    return report.fail('compose', 'missing_top_level_name')


def check_writable(report: Report, check: str, directory: Path):
    """The directory, or its nearest existing parent when it does not exist yet, is writable."""
    for candidate in (directory, *directory.parents):
        if os.path.lexists(candidate):
            if candidate.is_dir() and os.access(candidate, os.W_OK | os.X_OK):
                return report.check(check)
            break
    return report.fail(check, 'not_writable')


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
        return report.fail('http_port', 'invalid')
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
Checks the environment contract of this checkout, read-only: the configuration (legacy profile
or workspace) and its agent_destructive setting, git 2.31 or newer, docker and `docker compose version`, flock, /proc, the
environment's Python, the Odoo source release, odoo.conf, the compose file's top-level name,
the env file (existence only), the logs and data directories, and the HTTP port.
Prints PASS|WARN|FAIL <check>[=<value>] per check and doctor_failures=<n>; exit 1 when n > 0.
Never starts services, connects to a database or prints file contents.
'''


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
    try:
        values = config.load(root)
    except ValueError as exc:
        values = None
        report.fail('configuration', ' '.join(str(exc).split()))
    else:
        workspace = bool(values['WORKSPACE_ROOT'])
        report.check('configuration', 'workspace' if workspace else 'legacy')
        report.check('odoo_version', values['ODOO_VERSION'])
        report.check('agent_destructive', values['AGENT_DESTRUCTIVE'])
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
        check_python(report, values, config.versions())
        check_release(report, values)
        conf_ok = check_conf(report, values, conf_reader, workspace)
        check_compose(report, values)
        if os.path.exists(values['ENV_FILE']):
            report.check('env_file')
        else:
            report.fail('env_file', 'missing')
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
