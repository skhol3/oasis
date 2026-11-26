"""`oasis doctor`: the read-only environment contract check, run through the global entry point.

The fake harness of test_lifecycle provides the project, Odoo source and environment Python;
PATH holds only fixture programs (fake docker, git and flock, a python3 and dirname), so the
host's tools never decide a result. Doctor must never start a service, connect to a database
or print file contents: the fake docker records every call, and only `docker compose version`
may appear. Every FAIL line is followed by `  fix: <command or action>` (v0.14.0 S1), and the value
origins follow the configuration lines (S2).
"""
import oasis_test_env  # noqa: F401  first: XDG_CONFIG_HOME is scratch (tests/oasis_test_env.py)
import os
from pathlib import Path
import re
import shlex
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
        # No location options: oasis passes them to Odoo for a workspace checkout.
        self.conf.write_text(f'[options]\nhttp_port = {self.port}\nadmin_passwd = {MARKER}\n')
        (self.root / 'dev/compose.yml').write_text(COMPOSE)
        (self.root / 'dev/.env').write_text(f'ODOO_DB_PASSWORD={MARKER}\n')
        executable(self.bindir / 'docker', DOCKER)
        executable(self.bindir / 'git', GIT)
        executable(self.bindir / 'flock', '#!/bin/sh\nexit 0\n')
        executable(self.bindir / 'python3', f'#!/bin/sh\nexec {sys.executable!r} "$@"\n')
        # The connection probe (tools/db_account.py, v0.16.0 S2) answers FAKE_CONNECTION, by default a
        # service that does not answer; it runs no docker.
        self.python.write_text(self.python.read_text().replace(
            '#!/bin/sh\n', '#!/bin/sh\ncase "$3" in */db_account.py) echo "${FAKE_CONNECTION:-not_running}"; '
            'exit 0 ;; esac\n', 1))
        (self.bindir / 'dirname').symlink_to(shutil.which('dirname'))
        self.env['PATH'] = str(self.bindir)
        self.workspace = self.root / 'oasis-workspace.toml'

    def origins(self):
        return (f'PASS odoo_source_from=workspace:{self.workspace}\n'
                f'PASS project_environment_from=workspace:{self.workspace}\n')

    def doctor(self, *args):
        return subprocess.run([sys.executable, '-B', str(CLI), '--project', str(self.root), 'doctor', *args],
                              text=True, capture_output=True, cwd=self.root, env=self.env)

    def tree(self):
        """Every path of the fixture with its readable content, the call log excluded."""
        base = self.root.parents[1]
        return {str(path.relative_to(base)): (path.read_bytes() if path.is_file() and os.access(path, os.R_OK)
                                              else path.stat().st_mode)
                for path in sorted(base.rglob('*')) if path != self.commands}

    def expected(self, *changed, omit=(), mode='workspace', extra=(), after=None):
        """The all-pass report with some lines replaced (by check name), omitted or added (extra before
        http_port; after: {check: line} after that check)."""
        lines = [f'PASS configuration={mode}', 'PASS odoo_version=19.0', 'PASS agent_destructive=ask',
                 *self.origins().splitlines(), 'PASS git=2.47.1', 'PASS docker',
                 'PASS docker_compose=2.29.1', 'PASS flock', 'PASS proc', 'PASS python=3.12',
                 'PASS odoo_release=19.0', 'PASS odoo_conf', 'PASS compose', 'PASS env_file', 'PASS logs_dir',
                 *extra, f'PASS http_port={self.port}', 'WARN postgres_connection=not_running']
        replacements = {re.split(r'[ =]', line, maxsplit=2)[1]: line for line in changed}
        # The connection check needs the checks it reads: python, odoo_conf and env_file.
        if any(line.startswith('FAIL ') and name in ('python', 'odoo_conf', 'env_file')
               for name, line in replacements.items()):
            omit = (*omit, 'postgres_connection')
        report = []
        for line in lines:
            name = re.split(r'[ =]', line, maxsplit=2)[1]
            if name in omit:
                continue
            report.append(replacements.get(name, line))
            if after and name in after:
                report.append(after[name])
        failures = sum(line.startswith('FAIL ') for line in report)
        return '\n'.join(report) + f'\ndoctor_failures={failures}\n'

    def assert_report(self, expected, docker_calls=1):
        """doctor prints exactly expected (exit 1 with a FAIL line, else 0) and changes nothing."""
        before = self.tree()
        result = self.doctor()
        failing = any(line.startswith('FAIL ') for line in expected.splitlines())
        self.assertEqual((result.returncode, result.stdout, result.stderr), (int(failing), expected, ''))
        # S1: every FAIL line is followed by the command or action that fixes it.
        lines = result.stdout.splitlines()
        for number, line in enumerate(lines):
            if line.startswith('FAIL '):
                self.assertTrue(lines[number + 1].startswith('  fix: '), (line, lines[number + 1]))
        self.assertNotIn(MARKER, result.stdout + result.stderr)
        # Read-only: no file changed, no server record or state directory created, and the only
        # external call with effects that could matter is `docker compose version`.
        self.assertEqual(self.tree(), before)
        calls = self.commands.read_text().splitlines() if self.commands.exists() else []
        self.assertEqual(calls, ['docker compose version'] * docker_calls)
        return result

    def workspace_mode(self):
        """The same fixture with its workspace file two levels up instead of in the checkout."""
        (self.root / 'oasis-workspace.toml').unlink()
        workspace = self.root.parents[1]
        (workspace / 'oasis-workspace.toml').write_text(WORKSPACE)
        (workspace / 'oasis-workspace.toml').chmod(0o644)
        workspace.chmod(0o755)
        self.workspace = workspace / 'oasis-workspace.toml'
        self.conf.write_text(f'[options]\nhttp_port = {self.port}\nadmin_passwd = {MARKER}\n')

    # -- all checks pass ------------------------------------------------------------------------

    def test_workspace_file_in_the_checkout_passes_every_check(self):
        self.assert_report('PASS configuration=workspace\nPASS odoo_version=19.0\nPASS agent_destructive=ask\n'
                           f'PASS odoo_source_from=workspace:{self.root}/oasis-workspace.toml\n'
                           f'PASS project_environment_from=workspace:{self.root}/oasis-workspace.toml\n'
                           'PASS git=2.47.1\n'
                           'PASS docker\nPASS docker_compose=2.29.1\nPASS flock\nPASS proc\n'
                           'PASS python=3.12\nPASS odoo_release=19.0\nPASS odoo_conf\nPASS compose\n'
                           f'PASS env_file\nPASS logs_dir\nPASS http_port={self.port}\n'
                           'WARN postgres_connection=not_running\ndoctor_failures=0\n')
        self.assertEqual(os.listdir(self.runtime.name), [])

    def test_workspace_checkout_passes_every_check(self):
        self.workspace_mode()
        self.assert_report('PASS configuration=workspace\nPASS odoo_version=19.0\nPASS agent_destructive=ask\n'
                           f'PASS odoo_source_from=workspace:{self.root.parents[1]}/oasis-workspace.toml\n'
                           f'PASS project_environment_from=workspace:{self.root.parents[1]}/oasis-workspace.toml\n'
                           'PASS git=2.47.1\n'
                           'PASS docker\nPASS docker_compose=2.29.1\nPASS flock\nPASS proc\n'
                           'PASS python=3.12\nPASS odoo_release=19.0\nPASS odoo_conf\nPASS compose\n'
                           'PASS env_file\nPASS logs_dir\nPASS data_dir\n'
                           f'PASS http_port={self.port}\nWARN postgres_connection=not_running\n'
                           'doctor_failures=0\n')
        self.assertEqual(os.listdir(self.runtime.name), [])

    def test_agent_destructive_setting_is_shown(self):
        profile = self.root / 'oasis-workspace.toml'
        for value in ('deny', 'allow'):
            with self.subTest(value=value):
                self.commands.unlink(missing_ok=True)
                profile.write_text(profile.read_text().replace('agent_destructive = ', '# was: ')
                                   + f"agent_destructive = '{value}'\n")
                self.assert_report(self.expected(f'PASS agent_destructive={value}'))

    def test_help_and_unknown_arguments(self):
        result = self.doctor('--help')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertTrue(result.stdout.startswith(f'Usage: {CLI} doctor\n'), result.stdout)
        result = self.doctor('--bogus')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (2, '', f'Usage: {CLI} doctor\n'))
        self.assertFalse(self.commands.exists())

    # -- failures and warnings ------------------------------------------------------------------

    def test_legacy_profile_is_one_fail_naming_the_fix(self):
        profile = self.root / '.odoo19-agent.toml'
        profile.write_text('[tooling]\n')
        # An invalid profile: migrate cannot plan it, so only its runnable --plan is named (it says why);
        # tests/test_migrate.py covers the fix that names the exact --apply --confirm <workspace file>.
        plan = shlex.join(['oasis', '--project', str(self.root), 'migrate', '--plan'])
        self.assert_report(f'FAIL configuration={profile} is the old profile format, no longer read: run {plan} '
                           'to see its conversion to oasis-workspace.toml or what stops it.\n'
                           f'  fix: {plan}\n'
                           'PASS git=2.47.1\nPASS docker\nPASS docker_compose=2.29.1\nPASS flock\nPASS proc\n'
                           'doctor_failures=1\n')

    def test_configuration_error_fails_and_skips_the_checks_that_need_it(self):
        profile = self.root / 'oasis-workspace.toml'
        profile.write_text(profile.read_text().replace("dev_prefix = 'cc_dev_'", "dev_prefix = 'unsafe'"))
        self.assert_report('FAIL configuration=Unsafe tooling database prefixes.\n'
                           '  fix: correct the setting the error names, then run oasis doctor again\n'
                           'PASS git=2.47.1\n'
                           'PASS docker\nPASS docker_compose=2.29.1\nPASS flock\nPASS proc\n'
                           'doctor_failures=1\n')

    def test_git_older_than_2_31_fails(self):
        self.env['FAKE_GIT_VERSION'] = '2.30.2'
        self.assert_report(self.expected('FAIL git=2.30.2 minimum=2.31\n  fix: install git 2.31 or newer on PATH'))

    def test_missing_git_fails(self):
        (self.bindir / 'git').unlink()
        self.assert_report(self.expected('FAIL git=missing\n  fix: install git 2.31 or newer on PATH'))

    def test_missing_docker_fails_without_the_compose_probe(self):
        (self.bindir / 'docker').unlink()
        self.assert_report(self.expected('FAIL docker=missing\n  fix: install Docker with its compose plugin on PATH', omit=('docker_compose',)), docker_calls=0)

    def test_failing_docker_compose_fails(self):
        executable(self.bindir / 'docker', DOCKER.replace('exit 0', 'exit 1').replace(
            'echo "Docker Compose version v2.29.1"', 'echo "docker: unknown command: compose" >&2'))
        self.assert_report(self.expected('FAIL docker_compose=unavailable\n'
                                         '  fix: install the Docker Compose plugin: docker compose version must succeed'))

    def test_missing_flock_warns(self):
        (self.bindir / 'flock').unlink()
        self.assert_report(self.expected('WARN flock=missing'))

    def test_python_mismatch_fails(self):
        self.python.write_text(self.python.read_text().replace('echo 3.12', 'echo 3.11'))
        self.assert_report(self.expected('FAIL python=3.11 expected=3.12\n'
                                         f'  fix: move {self.python.parent.parent} away, then oasis bootstrap --apply'))

    def test_missing_environment_python_fails(self):
        self.python.unlink()
        self.assert_report(self.expected('FAIL python=missing\n  fix: oasis bootstrap --apply'))

    def test_wrong_odoo_release_fails(self):
        (self.source / 'odoo/release.py').write_text('version_info = (18, 0, 0, "final", 0)\n')
        self.assert_report(self.expected('FAIL odoo_release=18.0 expected=19.0\n'
                                         f'  fix: set [tooling].community in {self.workspace} to an Odoo 19.0 source'))

    @unittest.skipIf(os.getuid() == 0, 'root reads any file')
    def test_unreadable_odoo_conf_fails_and_skips_the_port(self):
        self.conf.chmod(0)
        self.addCleanup(self.conf.chmod, 0o644)
        self.assert_report(self.expected(f'FAIL odoo_conf=unreadable\n  fix: make {self.conf} readable by you', omit=('http_port',)))

    def test_missing_odoo_conf_fails(self):
        self.conf.unlink()
        self.assert_report(self.expected('FAIL odoo_conf=missing\n  fix: oasis setup --apply', omit=('http_port',)))

    def test_workspace_conf_holding_location_options_warns(self):
        self.workspace_mode()
        self.conf.write_text(lifecycle.conf_text(f'http_port = {self.port}\n'))
        self.assert_report(self.expected('WARN odoo_conf=addons_path', mode='workspace', extra=('PASS data_dir',)))
        self.commands.unlink()
        self.conf.write_text(lifecycle.conf_text(f'http_port = {self.port}\ndata_dir = /srv/oasis-fixture\n'))
        self.assert_report(self.expected('WARN odoo_conf=addons_path,data_dir', mode='workspace',
                                         extra=('PASS data_dir',)))

    def test_compose_without_top_level_name_fails(self):
        # An indented name belongs to another mapping.
        (self.root / 'dev/compose.yml').write_text(f'x-meta:\n  name: {MARKER}\nservices: {{}}\n')
        self.assert_report(self.expected('FAIL compose=missing_top_level_name\n'
                                         f'  fix: add a top-level name: to {self.root / "dev/compose.yml"}'))

    def test_missing_compose_file_fails(self):
        (self.root / 'dev/compose.yml').unlink()
        self.assert_report(self.expected('FAIL compose=missing\n  fix: oasis setup --apply'))

    def test_missing_env_file_fails(self):
        (self.root / 'dev/.env').unlink()
        self.assert_report(self.expected('FAIL env_file=missing\n  fix: oasis setup --apply'))

    # -- the fix line of each FAIL, exactly (docs/checking-environment.md, the fix table) ------

    def configuration_report(self, message, fix):
        return (f'FAIL configuration={message}\n  fix: {fix}\n'
                'PASS git=2.47.1\nPASS docker\nPASS docker_compose=2.29.1\nPASS flock\nPASS proc\n'
                'doctor_failures=1\n')

    def test_no_workspace_file_is_fixed_by_setup(self):
        self.workspace.unlink()
        message = f'Missing tooling configuration: no oasis-workspace.toml at or above {self.root}.'
        # The entry point lets doctor run in an unconfigured checkout, so its FAIL names setup.
        result = self.doctor()
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (1, self.configuration_report(message, 'oasis setup --apply'), ''))
        self.commands.unlink()
        # The doctor tool itself, run with the selected root as the entry point would pass it.
        env = dict(self.env, OASIS_PROJECT_ROOT=str(self.root), OASIS_ENTRYPOINT=str(CLI))
        result = subprocess.run(['/bin/bash', str(ROOT / 'tools/doctor')], text=True, capture_output=True,
                                cwd=self.root, env=env)
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (1, self.configuration_report(message, 'oasis setup --apply'), ''))
        self.assertEqual(self.commands.read_text(), 'docker compose version\n')

    def test_no_odoo_source_is_fixed_by_setup(self):
        # No [tooling].community and no machine file (XDG_CONFIG_HOME is empty scratch).
        self.workspace.write_text(self.workspace.read_text().replace("community = '../../source/odoo'\n", ''))
        machine = Path(self.env['XDG_CONFIG_HOME']) / 'oasis/config.toml'
        self.assertFalse(machine.exists())
        self.assert_report(self.configuration_report(
            f'No Odoo source for 19.0: create the machine file {machine} with community under '
            f'[series."19.0"], or set [tooling].community in {self.workspace}.', 'oasis setup --apply'))
        # The same refusal from a machine file without the series: setup adds it.
        self.commands.unlink(missing_ok=True)
        machine = self.machine_file('# no series yet\n')
        self.assert_report(self.configuration_report(
            f'No Odoo source for 19.0: set community under [series."19.0"] in the machine file {machine}, '
            f'or [tooling].community in {self.workspace}.', 'oasis setup --apply'))

    @unittest.skipIf(os.getuid() == 0, 'root reads any file')
    def test_unreadable_compose_file_fails(self):
        compose = self.root / 'dev/compose.yml'
        compose.chmod(0)
        self.addCleanup(compose.chmod, 0o644)
        self.assert_report(self.expected(f'FAIL compose=unreadable\n  fix: make {compose} readable by you'))

    def test_unavailable_environment_python_fails(self):
        self.python.write_text('#!/bin/sh\nexit 1\n')
        self.assert_report(self.expected('FAIL python=unavailable\n'
                                         f'  fix: move {self.python.parent.parent} away, then oasis bootstrap --apply'))

    def test_missing_odoo_release_fails(self):
        (self.source / 'odoo/release.py').unlink()
        self.assert_report(self.expected('FAIL odoo_release=missing\n'
                                         f'  fix: set [tooling].community in {self.workspace} to an Odoo 19.0 source'))

    def test_unwritable_logs_and_data_directories_fail_naming_the_path_to_fix(self):
        # The default logs directory dev/logs/odoo19 does not exist; its nearest existing parent is
        # a file, so that file is named.
        blocker = self.root / 'dev/logs'
        blocker.write_text('')
        self.assert_report(self.expected(f'FAIL logs_dir=not_writable\n  fix: make {blocker} a directory you can write'))
        blocker.unlink()
        self.commands.unlink(missing_ok=True)
        self.workspace_mode()
        data = self.root.parents[1] / 'data'
        data.write_text('')
        self.assert_report(self.expected(extra=(f'FAIL data_dir=not_writable\n'
                                                f'  fix: make {data} a directory you can write',)))

    def test_non_numeric_http_port_fails_without_a_traceback(self):
        for value in ('abc', '70000'):
            with self.subTest(value=value):
                self.conf.write_text(lifecycle.conf_text(f'http_port = {value}\n'))
                result = self.doctor()
                self.assertEqual(result.returncode, 1)
                self.assertNotIn('Traceback', result.stderr)
                self.assertIn(f'FAIL http_port=invalid\n  fix: set http_port in {self.conf} to a port number\n',
                              result.stdout)
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


    # -- value origins (S2) ---------------------------------------------------------------------

    def machine_file(self, text):
        home = Path(self.runtime.name).parent / f'{Path(self.runtime.name).name}-config'
        (home / 'oasis').mkdir(parents=True, mode=0o700)
        self.addCleanup(shutil.rmtree, home, ignore_errors=True)
        machine = home / 'oasis' / 'config.toml'
        machine.write_text(text)
        machine.chmod(0o600)
        self.env['XDG_CONFIG_HOME'] = str(home)
        return machine

    def test_sources_from_the_machine_file_are_shown_with_its_path(self):
        enterprise = self.source.parent / 'enterprise'
        enterprise.mkdir()
        machine = self.machine_file(f"[series.\"19.0\"]\ncommunity = '{self.source}'\nenterprise = '{enterprise}'\n")
        self.workspace.write_text(self.workspace.read_text().replace("community = '../../source/odoo'\n", ''))
        origins = (f'PASS odoo_source_from=machine:{machine}\nPASS enterprise_source_from=machine:{machine}\n'
                   f'PASS project_environment_from=workspace:{self.workspace}')
        self.assert_report(self.expected(omit=('odoo_source_from', 'project_environment_from'),
                                         after={'agent_destructive': origins}))
        # A wrong release then names the machine file as the place to fix.
        self.commands.unlink()
        (self.source / 'odoo/release.py').write_text('version_info = (18, 0, 0, "final", 0)\n')
        result = self.doctor()
        self.assertIn('FAIL odoo_release=18.0 expected=19.0\n'
                      f'  fix: set community under [series."19.0"] in {machine} to an Odoo 19.0 source\n',
                      result.stdout)

    def test_values_from_the_checkout_file_are_shown_with_its_path(self):
        self.workspace_mode()
        checkout = self.root / 'oasis-checkout.toml'
        checkout.write_text("[tooling]\nenvironment = 'default'\ncheckout_slug = 'feat'\n")
        report = self.expected(
            f'PASS project_environment_from=checkout:{checkout}', extra=('PASS data_dir',),
            after={'project_environment_from': f'PASS checkout_slug_from=checkout:{checkout}'})
        self.assert_report(report)

    # -- the environment file (S7) --------------------------------------------------------------

    def test_empty_database_account_values_fail_naming_only_the_variables(self):
        env_file = self.root / 'dev/.env'
        for text, empty in (
                ('ODOO_DB_USER=\nODOO_DB_PASSWORD=""\n', 'ODOO_DB_USER,ODOO_DB_PASSWORD'),
                (f"# account\nODOO_DB_USER={MARKER}\nODOO_DB_PASSWORD= # fill in\n", 'ODOO_DB_PASSWORD'),
                (f"ODOO_DB_USER=\t# fill in\nODOO_DB_PASSWORD={MARKER}\n", 'ODOO_DB_USER'),
                (f"export ODOO_DB_USER=''\nODOO_DB_PASSWORD={MARKER}\n", 'ODOO_DB_USER')):
            with self.subTest(text=text):
                self.commands.unlink(missing_ok=True)
                env_file.write_text(text)
                # setup --apply generates what is empty (v0.16.0 S2), keeping every other byte.
                self.assert_report(self.expected(f'FAIL env_file=empty {empty}\n  fix: oasis setup --apply'))
        # Filled in (the last assignment wins): passes.
        self.commands.unlink(missing_ok=True)
        env_file.write_text(f'ODOO_DB_PASSWORD=\nODOO_DB_PASSWORD={MARKER}\nODOO_DB_USER={MARKER}\n')
        self.assert_report(self.expected())
        # `~` and `null` are values in an env file, as setup reads them too: passes.
        for text in ('ODOO_DB_USER=~\nODOO_DB_PASSWORD=null\n', 'ODOO_DB_USER=null # mine\nODOO_DB_PASSWORD=~\n'):
            with self.subTest(text=text):
                self.commands.unlink(missing_ok=True)
                env_file.write_text(text)
                self.assert_report(self.expected())
        # Neither declared (another account's naming): respected, a WARN that says how to opt in.
        for text in (f'POSTGRES_PASSWORD={MARKER}\nOTHER=\n', ''):
            with self.subTest(text=text):
                self.commands.unlink(missing_ok=True)
                env_file.write_text(text)
                self.assert_report(self.expected(self.unassigned()))

    def unassigned(self):
        env_file = self.root / 'dev/.env'
        return ('WARN env_file=unassigned ODOO_DB_USER,ODOO_DB_PASSWORD\n'
                f'  fix: setup leaves {env_file} unchanged (an existing file is respected); to use the account oasis '
                'generates, add the empty lines ODOO_DB_USER= and ODOO_DB_PASSWORD= to it, then run oasis setup '
                '--apply')

    def test_an_env_file_value_oasis_cannot_read_fails_naming_only_the_variables(self):
        env_file = self.root / 'dev/.env'
        fix = (f'literally in single quotes: oasis does not read compose interpolation ($) or double-quoted escapes '
               '(\\), so Odoo would get another credential')
        for text, names in ((f'ODOO_DB_USER=oasis_cc\nODOO_DB_PASSWORD=${{SECRET}}{MARKER}\n', 'ODOO_DB_PASSWORD'),
                            (f'ODOO_DB_USER="${{USER}}"\nODOO_DB_PASSWORD="{MARKER}\\n" # mine\n',
                             'ODOO_DB_USER,ODOO_DB_PASSWORD')):
            with self.subTest(text=text):
                self.commands.unlink(missing_ok=True)
                env_file.write_text(text)
                self.assert_report(self.expected(f'FAIL env_file=unsupported_value {names}\n  fix: write '
                                                 f'{" and ".join(names.split(","))} in {env_file} {fix}'))
        # Literal values, single quotes included, pass; so does a value odoo.conf replaces (Odoo never reads it).
        for text, conf in ((f"ODOO_DB_USER=oasis_cc\nODOO_DB_PASSWORD='{MARKER} $x \\n'\n", ''),
                           (f'ODOO_DB_USER=${{USER}}\nODOO_DB_PASSWORD={MARKER}\n', 'db_user = mine\n')):
            with self.subTest(text=text):
                self.commands.unlink(missing_ok=True)
                env_file.write_text(text)
                self.conf.write_text(f'[options]\nhttp_port = {self.port}\n{conf}')
                self.assert_report(self.expected())
        self.commands.unlink(missing_ok=True)
        env_file.write_text(f'ODOO_DB_USER=oasis_cc\nODOO_DB_PASSWORD=${{SECRET}}{MARKER}\n')
        self.conf.write_text(f'[options]\nhttp_port = {self.port}\ndb_password = {MARKER}\n')
        result = self.doctor()
        self.assertIn('PASS env_file\n', result.stdout)

    # -- a database account in odoo.conf (v0.16.0 S2: "Los respeta y ofrece migrar") ---------------

    def test_an_odoo_conf_password_warns_naming_the_setup_move(self):
        env_file = self.root / 'dev/.env'
        moves = (f'WARN odoo_conf_password\n  fix: oasis setup --apply moves it to {env_file} and removes {{options}} '
                 f'from {self.conf} ({{lines}} only)')
        for options, text, warning in (
                # The env file holds the same value (the fixture's).
                (f'db_password = {MARKER}\n', None, moves.format(options='db_password', lines='that line')),
                # The env file declares no account: respected, so nothing moves.
                (f'db_user = mine\ndb_password = {MARKER}\n', '# nothing yet\n',
                 f'WARN odoo_conf_password\n  fix: remove db_user and db_password from {self.conf} once the account '
                 f'of {env_file} is the one PostgreSQL accepts (oasis doctor checks it); oasis setup --apply removes '
                 'them itself when both files hold the same values'),
                (f'db_user = mine\ndb_password = {MARKER}\n', 'ODOO_DB_USER=\nODOO_DB_PASSWORD=\n', None),
                # Another account: setup keeps both files.
                ('db_password = other\n', None,
                 f'WARN odoo_conf_password\n  fix: remove db_password from {self.conf} once the account of {env_file} '
                 f'is the one PostgreSQL accepts (oasis doctor checks it); oasis setup --apply removes it itself when '
                 'both files hold the same values')):
            with self.subTest(options=options, text=text):
                self.commands.unlink(missing_ok=True)
                env_file.write_text(text if text is not None else f'ODOO_DB_PASSWORD={MARKER}\n')
                self.conf.write_text(f'[options]\nhttp_port = {self.port}\n{options}')
                if warning is None:
                    # Empty account values fail first; their fix (setup --apply) moves the password too.
                    report = self.expected('FAIL env_file=empty ODOO_DB_USER,ODOO_DB_PASSWORD\n  fix: oasis setup --apply',
                                           after={'odoo_conf': moves.format(options='db_user and db_password',
                                                                            lines='those lines')})
                elif text == '# nothing yet\n':
                    report = self.expected(self.unassigned(), after={'odoo_conf': warning})
                else:
                    report = self.expected(after={'odoo_conf': warning})
                self.assert_report(report)
        # A db_user alone, or values Odoo reads as unset, hold no password: no line.
        for options in ('db_user = mine\n', 'db_password = False\n', 'db_password =\n'):
            with self.subTest(options=options):
                self.commands.unlink(missing_ok=True)
                env_file.write_text(f'ODOO_DB_PASSWORD={MARKER}\n')
                self.conf.write_text(f'[options]\nhttp_port = {self.port}\n{options}')
                self.assert_report(self.expected())

    # -- the connection with Odoo's account (v0.16.0 S2) -----------------------------------------

    def test_the_connection_with_odoos_account_is_reported_and_a_refused_one_names_its_fix(self):
        # odoo.conf names the endpoint the compose service publishes.
        (self.root / 'dev/compose.yml').write_text("name: cc-shop\nservices:\n  db:\n    image: postgres:17\n"
                                                   "    ports:\n      - '127.0.0.1:6001:5432'\n")
        self.conf.write_text(f'[options]\nhttp_port = {self.port}\ndb_host = 127.0.0.1\ndb_port = 6001\n')
        for outcome, line in (('ready', 'PASS postgres_connection'),
                              ('not_running', 'WARN postgres_connection=not_running'),
                              ('no_driver', 'WARN postgres_connection=unchecked'),
                              ('Traceback', 'WARN postgres_connection=unchecked')):
            with self.subTest(outcome=outcome):
                self.commands.unlink(missing_ok=True)
                self.env['FAKE_CONNECTION'] = outcome
                self.assert_report(self.expected(line))
        # Refused: the volume was initialized with other credentials; the fix is the Tier B recreate.
        self.commands.unlink(missing_ok=True)
        self.env['FAKE_CONNECTION'] = 'authentication_failed'
        recreate = shlex.join(['oasis', '--project', str(self.root), 'recreate-database-volume', '--confirm',
                               'cc-shop'])
        env_file = self.root / 'dev/.env'
        self.assert_report(self.expected(
            'FAIL postgres_connection=authentication_failed\n'
            f'  fix: the PostgreSQL that {self.conf} names refuses the account Odoo uses: its volume was initialized '
            f'with other credentials than {env_file}; {recreate} recreates it with them (Tier B: it deletes every '
            'database of the service)'))
        # Refused by another server than the compose service: correct the account there, no recreate.
        compose = self.root / 'dev/compose.yml'
        for options, where in (('db_host = db.example.invalid\ndb_port = 6001\n',
                                'db_host db.example.invalid, db_port 6001'),
                               ('db_host = 127.0.0.1\n', 'db_host 127.0.0.1, no db_port')):
            with self.subTest(options=options):
                self.commands.unlink()
                self.conf.write_text(f'[options]\nhttp_port = {self.port}\n{options}')
                self.assert_report(self.expected(
                    'FAIL postgres_connection=authentication_failed\n'
                    f'  fix: the PostgreSQL that {self.conf} names ({where}) refuses the account Odoo uses, and it is '
                    f'not the service of {compose} (published on 127.0.0.1:6001): correct that account on that '
                    f'server, or set db_host = 127.0.0.1 and the db_port {compose} publishes in {self.conf}; then run '
                    'oasis doctor again'))
        # Refused while odoo.conf sets its own account, other than the env file's: that is the fix.
        self.commands.unlink()
        self.conf.write_text(f'[options]\nhttp_port = {self.port}\ndb_host = 127.0.0.1\ndb_port = 6001\n'
                             'db_password = other\n')
        self.assert_report(self.expected(
            'FAIL postgres_connection=authentication_failed\n'
            f'  fix: {self.conf} sets db_password to other values than {env_file}: remove db_password from '
            f'{self.conf} so Odoo uses the account of {env_file}, then run oasis doctor again',
            after={'odoo_conf': f'WARN odoo_conf_password\n  fix: remove db_password from {self.conf} once the '
                                f'account of {env_file} is the one PostgreSQL accepts (oasis doctor checks it); oasis '
                                'setup --apply removes it itself when both files hold the same values'}))

    def test_the_connection_is_left_out_when_a_check_it_needs_failed(self):
        self.python.write_text(self.python.read_text().replace('echo 3.12', 'echo 3.11'))
        result = self.doctor()
        self.assertNotIn('postgres_connection', result.stdout)
        self.assertIn('FAIL python=3.11 expected=3.12\n', result.stdout)

    @unittest.skipIf(os.getuid() == 0, 'root reads any file')
    def test_unreadable_env_file_fails(self):
        env_file = self.root / 'dev/.env'
        env_file.chmod(0)
        self.addCleanup(env_file.chmod, 0o600)
        self.assert_report(self.expected(f'FAIL env_file=unreadable\n  fix: make {env_file} readable by you'))

    # -- the series of the module manifests (S11) -----------------------------------------------

    def test_a_module_of_another_series_is_one_fail(self):
        manifest = self.root / 'coffee/__manifest__.py'
        manifest.write_text("{'name': 'Coffee', 'version': '15.0.1.0.0'}\n")
        (self.root / 'tea').mkdir()
        (self.root / 'tea/__manifest__.py').write_text("{'name': 'Tea', 'version': '16.0.1.0.0'}\n")
        self.assert_report(self.expected(after={'odoo_release': (
            'FAIL module_series=15.0 module=coffee expected=19.0\n'
            '  fix: run oasis in a checkout of an Odoo 19.0 branch, or set the version of coffee to 19.0.x.y.z if '
            f'it is an Odoo 19.0 module; for Odoo 15.0 here, run oasis setup to add a [series."15.0"] section to '
            f'{self.workspace}')}))
        # Versions that are not series-style, or of the configured series, are ignored.
        for version in ('1.0', '19.0.1.0.0', '1.2.3.4.5', '2.0.1.0.0'):
            with self.subTest(version=version):
                self.commands.unlink(missing_ok=True)
                manifest.write_text(f"{{'name': 'Coffee', 'version': '{version}'}}\n")
                (self.root / 'tea/__manifest__.py').write_text(f"{{'name': 'Tea', 'version': '{version}'}}\n")
                self.assert_report(self.expected())


class DoctorSurfaceTests(unittest.TestCase):
    def test_gentle_shell_command_runs_doctor(self):
        source = (ROOT / 'pi/extensions/oasis.ts').read_text()
        # The subcommand table (usage pinned in pi/tests/commands.test.ts) and its dispatch.
        self.assertIn('name: "doctor"', (ROOT / 'pi/lib/commands.ts').read_text())
        self.assertIn('doctor: (ctx) => doctor(ctx),', source)
        self.assertIn('run(root, ["doctor"]', source)
        self.assertNotIn('oasis_doctor', source)

    def test_readme_explains_doctor_and_check_environment(self):
        # The section moved from the README to its own topic file, linked from the README.
        self.assertIn('](docs/checking-environment.md)', (ROOT / 'README.md').read_text())
        section = (ROOT / 'docs/checking-environment.md').read_text()
        self.assertTrue(section.startswith('# Checking the environment\n'))
        self.assertIn('oasis --project /absolute/project doctor', section)
        self.assertIn('check-environment', section)
        self.assertIn('doctor_failures=', section)


if __name__ == '__main__':
    unittest.main()
