"""`oasis doctor`: the read-only environment contract check, run through the global entry point.

The fake harness of test_lifecycle provides the project, Odoo source and environment Python;
PATH holds only fixture programs (fake docker, git and flock, a python3 and dirname), so the
host's tools never decide a result. Doctor must never start a service, connect to a database
or print file contents: the fake docker records every call, and only `docker compose version`
may appear.
"""
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import unittest

import test_lifecycle as lifecycle

ROOT = lifecycle.STAGE
CLI = ROOT / 'oasis'
RUNTIME_STATE = ROOT / 'tools' / 'runtime_state.py'
MARKER = 'doctor-must-not-print-this'
DOCKER = '''#!/bin/sh
printf 'docker %s\\n' "$*" >> "$FAKE_LOG"
if [ "$*" = "compose version" ]; then echo "Docker Compose version v2.29.1"; fi
exit 0
'''
# Never a repository: checkout identity is `none`, like the lifecycle fixture.
GIT = '''#!/bin/sh
if [ "$1" = "--version" ]; then echo "git version ${FAKE_GIT_VERSION:-2.47.1}"; exit 0; fi
echo 'fatal: not a git repository' >&2
exit 128
'''
COMPOSE = f'name: {MARKER}\nservices:\n  db:\n    image: postgres:16\n'
WORKSPACE = '''workspace_version = 1
odoo_version = '19.0'

[tooling]
community = 'source/odoo'
config = 'projects/a project/dev/odoo.conf'
env_file = 'projects/a project/dev/.env'
compose = 'projects/a project/dev/compose.yml'
requirements = 'projects/a project/dev/requirements'
addons_paths = ['.']
db_service = 'db'
dev_prefix = 'cc_dev_'
test_prefix = 'cc_test_'
logs = 'logs'
data_dir = 'data'

[environments.default]
path = 'environments/example'
python = '3.12'
'''


def executable(path, text):
    path.write_text(text)
    path.chmod(0o755)


class DoctorTests(unittest.TestCase):
    setUp_fixture = lifecycle.LifecycleTests.setUp

    def setUp(self):
        self.setUp_fixture()
        self.port = lifecycle.free_port()
        self.conf = self.root / 'dev/odoo.conf'
        self.conf.write_text(lifecycle.conf_text(f'http_port = {self.port}\nadmin_passwd = {MARKER}\n'))
        (self.root / 'dev/compose.yml').write_text(COMPOSE)
        (self.root / 'dev/.env').write_text(f'ODOO_DB_PASSWORD={MARKER}\n')
        executable(self.bindir / 'docker', DOCKER)
        executable(self.bindir / 'git', GIT)
        executable(self.bindir / 'flock', '#!/bin/sh\nexit 0\n')
        executable(self.bindir / 'python3', f'#!/bin/sh\nexec {sys.executable!r} "$@"\n')
        (self.bindir / 'dirname').symlink_to(shutil.which('dirname'))
        self.env['PATH'] = str(self.bindir)

    def doctor(self, *args):
        return subprocess.run([sys.executable, '-B', str(CLI), '--project', str(self.root), 'doctor', *args],
                              text=True, capture_output=True, cwd=self.root, env=self.env)

    def tree(self):
        """Every path of the fixture with its readable content, the call log excluded."""
        base = self.root.parents[1]
        return {str(path.relative_to(base)): (path.read_bytes() if path.is_file() and os.access(path, os.R_OK)
                                              else path.stat().st_mode)
                for path in sorted(base.rglob('*')) if path != self.commands}

    def expected(self, *changed, omit=(), mode='legacy', extra=()):
        """The all-pass report with some lines replaced (by check name), omitted or added."""
        lines = [f'PASS configuration={mode}', 'PASS odoo_version=19.0', 'PASS git=2.47.1', 'PASS docker',
                 'PASS docker_compose=2.29.1', 'PASS flock', 'PASS proc', 'PASS python=3.12',
                 'PASS odoo_release=19.0', 'PASS odoo_conf', 'PASS compose', 'PASS env_file', 'PASS logs_dir',
                 *extra, f'PASS http_port={self.port}']
        replacements = {re.split(r'[ =]', line, maxsplit=2)[1]: line for line in changed}
        report = []
        for line in lines:
            name = re.split(r'[ =]', line, maxsplit=2)[1]
            if name in omit:
                continue
            report.append(replacements.get(name, line))
        failures = sum(line.startswith('FAIL ') for line in report)
        return '\n'.join(report) + f'\ndoctor_failures={failures}\n'

    def assert_report(self, expected, docker_calls=1):
        """doctor prints exactly expected (exit 1 with a FAIL line, else 0) and changes nothing."""
        before = self.tree()
        result = self.doctor()
        failing = any(line.startswith('FAIL ') for line in expected.splitlines())
        self.assertEqual((result.returncode, result.stdout, result.stderr), (int(failing), expected, ''))
        self.assertNotIn(MARKER, result.stdout + result.stderr)
        # Read-only: no file changed, no server record or state directory created, and the only
        # external call with effects that could matter is `docker compose version`.
        self.assertEqual(self.tree(), before)
        calls = self.commands.read_text().splitlines() if self.commands.exists() else []
        self.assertEqual(calls, ['docker compose version'] * docker_calls)
        return result

    def workspace_mode(self):
        """The same fixture as a workspace checkout: no profile, the workspace two levels up."""
        (self.root / '.odoo19-agent.toml').unlink()
        workspace = self.root.parents[1]
        (workspace / 'oasis-workspace.toml').write_text(WORKSPACE)
        (workspace / 'oasis-workspace.toml').chmod(0o644)
        workspace.chmod(0o755)
        self.conf.write_text(f'[options]\nhttp_port = {self.port}\nadmin_passwd = {MARKER}\n')

    # -- all checks pass ------------------------------------------------------------------------

    def test_legacy_profile_passes_every_check(self):
        self.assert_report('PASS configuration=legacy\nPASS odoo_version=19.0\nPASS git=2.47.1\n'
                           'PASS docker\nPASS docker_compose=2.29.1\nPASS flock\nPASS proc\n'
                           'PASS python=3.12\nPASS odoo_release=19.0\nPASS odoo_conf\nPASS compose\n'
                           f'PASS env_file\nPASS logs_dir\nPASS http_port={self.port}\ndoctor_failures=0\n')
        self.assertEqual(os.listdir(self.runtime.name), [])

    def test_workspace_checkout_passes_every_check(self):
        self.workspace_mode()
        self.assert_report('PASS configuration=workspace\nPASS odoo_version=19.0\nPASS git=2.47.1\n'
                           'PASS docker\nPASS docker_compose=2.29.1\nPASS flock\nPASS proc\n'
                           'PASS python=3.12\nPASS odoo_release=19.0\nPASS odoo_conf\nPASS compose\n'
                           'PASS env_file\nPASS logs_dir\nPASS data_dir\n'
                           f'PASS http_port={self.port}\ndoctor_failures=0\n')
        self.assertEqual(os.listdir(self.runtime.name), [])

    def test_help_and_unknown_arguments(self):
        result = self.doctor('--help')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertTrue(result.stdout.startswith(f'Usage: {CLI} doctor\n'), result.stdout)
        result = self.doctor('--bogus')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (2, '', f'Usage: {CLI} doctor\n'))
        self.assertFalse(self.commands.exists())

    # -- failures and warnings ------------------------------------------------------------------

    def test_configuration_error_fails_and_skips_the_checks_that_need_it(self):
        profile = self.root / '.odoo19-agent.toml'
        profile.write_text(profile.read_text().replace("dev_prefix = 'cc_dev_'", "dev_prefix = 'unsafe'"))
        self.assert_report('FAIL configuration=Unsafe tooling database prefixes.\nPASS git=2.47.1\n'
                           'PASS docker\nPASS docker_compose=2.29.1\nPASS flock\nPASS proc\n'
                           'doctor_failures=1\n')

    def test_git_older_than_2_31_fails(self):
        self.env['FAKE_GIT_VERSION'] = '2.30.2'
        self.assert_report(self.expected('FAIL git=2.30.2 minimum=2.31'))

    def test_missing_git_fails(self):
        (self.bindir / 'git').unlink()
        self.assert_report(self.expected('FAIL git=missing'))

    def test_missing_docker_fails_without_the_compose_probe(self):
        (self.bindir / 'docker').unlink()
        self.assert_report(self.expected('FAIL docker=missing', omit=('docker_compose',)), docker_calls=0)

    def test_failing_docker_compose_fails(self):
        executable(self.bindir / 'docker', DOCKER.replace('exit 0', 'exit 1').replace(
            'echo "Docker Compose version v2.29.1"', 'echo "docker: unknown command: compose" >&2'))
        self.assert_report(self.expected('FAIL docker_compose=unavailable'))

    def test_missing_flock_warns(self):
        (self.bindir / 'flock').unlink()
        self.assert_report(self.expected('WARN flock=missing'))

    def test_python_mismatch_fails(self):
        self.python.write_text(self.python.read_text().replace('echo 3.12', 'echo 3.11'))
        self.assert_report(self.expected('FAIL python=3.11 expected=3.12'))

    def test_missing_environment_python_fails(self):
        self.python.unlink()
        self.assert_report(self.expected('FAIL python=missing'))

    def test_wrong_odoo_release_fails(self):
        (self.source / 'odoo/release.py').write_text('version_info = (18, 0, 0, "final", 0)\n')
        self.assert_report(self.expected('FAIL odoo_release=18.0 expected=19.0'))

    @unittest.skipIf(os.getuid() == 0, 'root reads any file')
    def test_unreadable_odoo_conf_fails_and_skips_the_port(self):
        self.conf.chmod(0)
        self.addCleanup(self.conf.chmod, 0o644)
        self.assert_report(self.expected('FAIL odoo_conf=unreadable', omit=('http_port',)))

    def test_missing_odoo_conf_fails(self):
        self.conf.unlink()
        self.assert_report(self.expected('FAIL odoo_conf=missing', omit=('http_port',)))

    def test_workspace_conf_holding_location_options_warns(self):
        self.workspace_mode()
        self.conf.write_text(lifecycle.conf_text(f'http_port = {self.port}\n'))
        self.assert_report(self.expected('WARN odoo_conf=addons_path', mode='workspace', extra=('PASS data_dir',)))
        self.commands.unlink()
        self.conf.write_text(lifecycle.conf_text(f'http_port = {self.port}\ndata_dir = /srv/oasis-fixture\n'))
        self.assert_report(self.expected('WARN odoo_conf=addons_path,data_dir', mode='workspace',
                                         extra=('PASS data_dir',)))

    def test_legacy_conf_holding_addons_path_passes(self):
        self.assertIn('addons_path', self.conf.read_text())
        self.assert_report(self.expected())

    def test_compose_without_top_level_name_fails(self):
        # An indented name belongs to another mapping.
        (self.root / 'dev/compose.yml').write_text(f'x-meta:\n  name: {MARKER}\nservices: {{}}\n')
        self.assert_report(self.expected('FAIL compose=missing_top_level_name'))

    def test_missing_compose_file_fails(self):
        (self.root / 'dev/compose.yml').unlink()
        self.assert_report(self.expected('FAIL compose=missing'))

    def test_missing_env_file_fails(self):
        (self.root / 'dev/.env').unlink()
        self.assert_report(self.expected('FAIL env_file=missing'))

    def test_non_numeric_http_port_fails_without_a_traceback(self):
        for value in ('abc', '70000'):
            with self.subTest(value=value):
                self.conf.write_text(lifecycle.conf_text(f'http_port = {value}\n'))
                result = self.doctor()
                self.assertEqual(result.returncode, 1)
                self.assertNotIn('Traceback', result.stderr)
                self.assertIn('FAIL http_port=invalid\n', result.stdout)
                self.assertTrue(result.stdout.endswith('doctor_failures=1\n'))

    def test_busy_http_port_warns(self):
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', self.port))
            listener.listen()
            self.assert_report(self.expected(f'WARN http_port={self.port} in_use'))

    def test_busy_port_of_this_checkouts_server_passes(self):
        # A live record of this checkout (the test process, within the start grace period).
        recorded = subprocess.run([sys.executable, '-I', '-B', str(RUNTIME_STATE), 'record', str(self.root),
                                   str(os.getpid()), str(self.port), str(self.source / 'odoo-bin')],
                                  env=self.env, capture_output=True, text=True)
        self.assertEqual((recorded.returncode, recorded.stderr), (0, ''))
        state = sorted(Path(self.runtime.name).rglob('*'))
        records = {path: path.read_bytes() for path in state if path.is_file()}
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', self.port))
            listener.listen()
            self.assert_report(self.expected(f'PASS http_port={self.port} server=this_checkout'))
        self.assertEqual(sorted(Path(self.runtime.name).rglob('*')), state)
        self.assertEqual({path: path.read_bytes() for path in state if path.is_file()}, records)


class DoctorSurfaceTests(unittest.TestCase):
    def test_gentle_shell_command_runs_doctor(self):
        source = (ROOT / 'pi/extensions/odoo19.ts').read_text()
        self.assertIn('const USAGE = "Usage: /oasis [setup | doctor | worktree <feature> <branch>]";', source)
        self.assertIn('run(root, ["doctor"]', source)
        self.assertNotIn('oasis_doctor', source)

    def test_readme_explains_doctor_and_check_environment(self):
        readme = (ROOT / 'README.md').read_text()
        self.assertIn('## Checking the environment\n', readme)
        section = readme.split('## Checking the environment\n', 1)[1].split('\n## ', 1)[0]
        self.assertIn('oasis --project /absolute/project doctor', section)
        self.assertIn('check-environment', section)
        self.assertIn('doctor_failures=', section)


if __name__ == '__main__':
    unittest.main()
