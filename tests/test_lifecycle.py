"""Lifecycle CLI tests use only a disposable project and deterministic command fakes."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest

STAGE = Path(__file__).resolve().parents[1]
PROFILE = (Path(__file__).resolve().parent / 'fixture-profile.toml').read_text()


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        fixture_root = Path(__file__).resolve().parent / 'fixturesroot'
        fixture_root.mkdir(exist_ok=True)
        self.addCleanup(fixture_root.rmdir)
        self.scratch = tempfile.TemporaryDirectory(dir=fixture_root)
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name) / 'workspace/projects/a project'
        self.root.mkdir(parents=True)
        (self.root / '.odoo19-agent.toml').write_text(PROFILE)
        self.source = (self.root / '../../source/odoo').resolve()
        self.python = (self.root / '../../environments/example/bin/python').resolve()
        self.source.mkdir(parents=True, exist_ok=True)
        self.python.parent.mkdir(parents=True, exist_ok=True)
        for name in ('dev/odoo.conf', 'dev/.env', 'dev/compose.yml', 'coffee/__manifest__.py'):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()
        (self.source / 'odoo-bin').touch()
        (self.source / 'odoo').mkdir(exist_ok=True)
        (self.source / 'odoo/release.py').write_text('version_info = (19, 0, 0, "final", 0)\n')
        self.commands = self.root / 'commands.log'
        self.bindir = self.root / 'fake bin'
        self.bindir.mkdir()
        self.python.write_text('#!/bin/sh\n'
                               'if [ "$1" = "-c" ]; then echo 3.12; exit 0; fi\n'
                               'if [ "$2" = "--version" ]; then echo "Odoo Server 19.0"; exit 0; fi\n'
                               'printf "odoo %s\\n" "$*" >> "$FAKE_LOG"\n'
                               'if [ "$2" = "shell" ]; then cat; fi\n')
        docker = self.bindir / 'docker'
        docker.write_text('''#!/bin/sh
printf "docker %s\\n" "$*" >> "$FAKE_LOG"
case "$*" in
  *"exec psql"*"SELECT 1 FROM pg_database"*) [ "${FAKE_EXISTS:-0}" = 1 ] && echo 1 ;;
  *"exec psql"*"SELECT count(*) FROM pg_stat_activity"*) echo "${FAKE_SESSIONS:-0}" ;;
  *"to_regclass"*) echo t ;;
  *"COALESCE(latest_version"*) printf 'installed\\t19.0\\n' ;;
esac
exit 0
''')
        self.python.chmod(0o755)
        docker.chmod(0o755)
        self.env = {**os.environ, 'PATH': str(self.bindir) + ':' + os.environ['PATH'],
                    'FAKE_LOG': str(self.commands), 'PYTHONDONTWRITEBYTECODE': '1',
                    'ODOO19_TOOLS_DIR': str(STAGE / 'tools')}

    def invoke(self, command, *args, input=None):
        path = self.root / 'dev/scripts' / command
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((STAGE / 'project-wrappers' / command).read_bytes())
        return subprocess.run(['bash', str(path), *args], text=True, input=input,
                              cwd=self.root, env=self.env, capture_output=True)

    def unchanged(self):
        self.assertFalse(self.commands.exists(), self.commands.read_text() if self.commands.exists() else '')

    def test_usage_names_project_wrapper_not_global_tool(self):
        for command, args, tail in (
                ('update-module', ('coffee',), ' <module> <database>'),
                ('list-databases', ('unexpected',), '')):
            result = self.invoke(command, *args)
            self.assertEqual((result.returncode, result.stdout, result.stderr),
                             (2, '', 'Usage: ' + str(self.root / 'dev/scripts' / command) + tail + '\n'))
            self.unchanged()

    def test_wrong_runtime_version_rejects_before_docker(self):
        self.python.write_text(self.python.read_text().replace('echo 3.12', 'echo 3.11'))
        result = self.invoke('install-module', 'coffee')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (2, '', 'Python 3.12 is required; found 3.11.\n'))
        self.unchanged()

    def test_wrong_odoo_runtime_rejects_before_docker(self):
        self.python.write_text(self.python.read_text().replace('Odoo Server 19.0', 'Odoo Server 119.0'))
        result = self.invoke('install-module', 'coffee')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (2, '', 'Odoo runtime 19.0 is required.\n'))
        self.unchanged()

    def test_invalid_module_rejects_before_docker(self):
        result = self.invoke('install-module', "coffee';DROP")
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (2, '', 'Module must use only letters, numbers, and underscores.\n'))
        self.unchanged()

    def test_install_default_and_piped_shell(self):
        result = self.invoke('install-module', 'coffee')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))
        self.assertIn('odoo ' + str(self.source / 'odoo-bin') + ' -c ' + str(self.root / 'dev/odoo.conf') +
                      ' -d cc_dev_coffee -i coffee --without-demo --stop-after-init\n', self.commands.read_text())
        result = self.invoke('odoo-shell', 'outside_db', input='print(42)\n')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, 'print(42)\n', ''))

    def test_missing_tools_fails_clearly_without_fallback(self):
        self.env['ODOO19_TOOLS_DIR'] = str(self.root / 'not installed')
        result = self.invoke('status')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (2, '', 'Odoo 19 tools are not installed: ' +
                          str(self.root / 'not installed/status') + '\n'))
        self.unchanged()

    def test_missing_config_and_bad_release_precede_external_commands(self):
        (self.root / '.odoo19-agent.toml').unlink()
        result = self.invoke('status')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (2, '', 'ERROR: Missing tooling configuration: ' +
                          str(self.root / '.odoo19-agent.toml') + '\n'))
        self.unchanged()
        (self.root / '.odoo19-agent.toml').write_text(PROFILE)
        (self.source / 'odoo/release.py').write_text('version_info = (18, 0)\n')
        result = self.invoke('status')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (2, '', 'Odoo source must declare release 19.0.\n'))
        self.unchanged()

    def test_invalid_database_blocks_sql_for_update_and_shell(self):
        for command, args in [('update-module', ('coffee', "unsafe'")),
                              ('odoo-shell', ("unsafe'",))]:
            result = self.invoke(command, *args)
            self.assertEqual((result.returncode, result.stdout, result.stderr),
                             (2, '', 'Database name must use only letters, numbers, and underscores.\n'))
            self.unchanged()

    def test_unmanaged_demo_rejected_without_commands(self):
        result = self.invoke('install-module', '--with-demo', 'coffee', 'other_db')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (2, '', 'Managed databases must use cc_dev_<name> or cc_test_<name>: other_db\n'))
        self.unchanged()

    def test_test_reset_refuses_active_sessions(self):
        self.env.update(FAKE_EXISTS='1', FAKE_SESSIONS='2')
        result = self.invoke('test-module', 'coffee')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (3, '', 'Refusing to reset database with 2 active session(s): cc_test_coffee\n'
                          'Close those sessions or explicitly drop the database with --terminate.\n'))
        self.assertNotIn('dropdb ', self.commands.read_text())
        self.assertNotIn('odoo ', self.commands.read_text())

    def test_drop_requires_terminate_then_explicit_terminate(self):
        self.env.update(FAKE_EXISTS='1', FAKE_SESSIONS='2')
        result = self.invoke('drop-database', 'cc_dev_coffee')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (3, '', 'Refusing to drop database with 2 active session(s): cc_dev_coffee\n'
                          'Retry with --terminate only after confirming those sessions may be closed.\n'))
        self.assertNotIn('pg_terminate_backend', self.commands.read_text())
        result = self.invoke('drop-database', 'cc_dev_coffee', '--terminate')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (0, 'Database dropped: cc_dev_coffee\n', ''))
        self.assertIn('pg_terminate_backend', self.commands.read_text())

    def test_update_allows_explicit_database_and_test_defaults(self):
        result = self.invoke('update-module', 'coffee', 'other_db')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))
        self.assertIn('-d other_db -u coffee --stop-after-init', self.commands.read_text())
        result = self.invoke('test-module', 'coffee')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))
        self.assertIn('-d cc_test_coffee -i coffee --without-demo --test-tags /coffee --stop-after-init',
                      self.commands.read_text())

    def test_custom_prefixes_and_verify_distinct_names(self):
        path = self.root / '.odoo19-agent.toml'
        path.write_text(PROFILE.replace('cc_dev_', 'demo_dev_').replace('cc_test_', 'demo_test_'))
        result = self.invoke('install-module', 'coffee')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))
        self.assertIn('-d demo_dev_coffee -i coffee', self.commands.read_text())
        before = self.commands.read_text()
        result = self.invoke('verify-module', 'coffee', 'demo_test_same', 'demo_test_same')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (2, '', 'Test and update verification require different databases.\n'))
        self.assertEqual(self.commands.read_text(), before)

    def test_verify_has_distinct_test_and_fresh_install_update_phases(self):
        result = self.invoke('verify-module', 'coffee')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, '')
        self.assertIn('tests_database=cc_test_coffee\n', result.stdout)
        self.assertIn('update_database=cc_test_coffee_update\n', result.stdout)
        self.assertIn('update_baseline=current_code_fresh_install\n', result.stdout)
        self.assertIn('current_code_update_exit=0\n', result.stdout)
        log = self.commands.read_text()
        self.assertIn('-d cc_test_coffee -i coffee --without-demo --test-tags /coffee --stop-after-init', log)
        self.assertIn('-d cc_test_coffee_update -i coffee --without-demo --stop-after-init', log)
        self.assertIn('-d cc_test_coffee_update -u coffee --stop-after-init', log)

    def configure_test_database(self, value='cc_test_shared'):
        path = self.root / '.odoo19-agent.toml'
        path.write_text(PROFILE.replace('test_prefix =', f'test_database = "{value}"\ntest_prefix ='))

    def test_configured_test_database_and_explicit_override(self):
        self.configure_test_database()
        for args, database in [(('coffee',), 'cc_test_shared'),
                               (('coffee', 'cc_test_isolated'), 'cc_test_isolated')]:
            result = self.invoke('test-module', *args)
            self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))
            self.assertIn(f'-d {database} -i coffee', self.commands.read_text())
        self.assertNotIn('cc_dev_', self.commands.read_text())

    def test_unconfigured_profile_does_not_inherit_database_from_environment(self):
        self.env['TEST_DATABASE'] = 'cc_test_unintended'
        result = self.invoke('test-module', 'coffee')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))
        self.assertNotIn('cc_test_unintended', self.commands.read_text())
        self.assertIn('-d cc_test_coffee -i coffee', self.commands.read_text())

    def test_invalid_configured_test_target_blocks_commands(self):
        for value in ('cc_dev_manual', 'other_db', 'cc_test_', 'cc_test_bad;echo',
                      'cc_test_' + 'a' * 49):
            self.configure_test_database(value)
            result = self.invoke('test-module', 'coffee')
            self.assertEqual((result.returncode, result.stdout, result.stderr),
                             (2, '', 'ERROR: Unsafe tooling test database.\n'))
            self.unchanged()

    def test_verify_uses_configured_target_and_separate_update_baseline(self):
        self.configure_test_database()
        result = self.invoke('verify-module', 'coffee')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertIn('tests_database=cc_test_shared\n', result.stdout)
        self.assertIn('update_database=cc_test_shared_update\n', result.stdout)
        self.assertIn('update_baseline=current_code_fresh_install\n', result.stdout)

    def test_configured_name_boundary_and_verify_override(self):
        database = 'cc_test_' + 'a' * 48
        self.configure_test_database(database)
        result = self.invoke('test-module', 'coffee')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))
        self.assertIn(f'-d {database} -i coffee', self.commands.read_text())
        result = self.invoke('verify-module', 'coffee', 'cc_test_isolated')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertIn('tests_database=cc_test_isolated\n', result.stdout)
        self.assertIn('update_database=cc_test_isolated_update\n', result.stdout)

    def test_compact_tests_preserve_streams_and_failure_status(self):
        self.configure_test_database()
        self.python.write_text(self.python.read_text() +
                               'echo "tests stdout"\necho "tests stderr" >&2\nexit 7\n')
        result = self.invoke('test-module', '--compact', 'coffee')
        self.assertEqual((result.returncode, result.stderr), (7, ''))
        lines = result.stdout.splitlines()
        self.assertEqual(lines[0], 'phase=tests database=cc_test_shared exit=7')
        logs = dict(line.split('=', 1) for line in lines[1:])
        self.assertEqual(set(logs), {'stdout_log', 'stderr_log'})
        self.assertEqual(Path(logs['stdout_log']).read_text(), 'tests stdout\n')
        self.assertEqual(Path(logs['stderr_log']).read_text(), 'tests stderr\n')
        self.assertEqual(Path(logs['stdout_log']).stat().st_mode & 0o777, 0o600)
        self.assertTrue(Path(logs['stdout_log']).is_relative_to(self.root / 'dev/logs/odoo19'))

    def test_compact_verify_retains_each_phase_logs(self):
        self.configure_test_database()
        result = self.invoke('verify-module', '--compact', 'coffee')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        for phase in ('tests', 'prepare_update_database', 'fresh_install', 'current_code_update'):
            line = next(line for line in result.stdout.splitlines() if line.startswith(f'phase={phase} '))
            self.assertIn('exit=0', line)
        paths = [line.split('=', 1)[1] for line in result.stdout.splitlines()
                 if line.startswith(('stdout_log=', 'stderr_log='))]
        self.assertEqual(len(paths), 8)
        self.assertTrue(all(Path(path).is_file() for path in paths))
        self.assertEqual(len(set(paths)), 8)

    def test_compact_refusal_retains_error_without_reset(self):
        self.configure_test_database()
        self.env.update(FAKE_EXISTS='1', FAKE_SESSIONS='2')
        result = self.invoke('test-module', '--compact', 'coffee')
        self.assertEqual((result.returncode, result.stderr), (3, ''))
        lines = result.stdout.splitlines()
        self.assertEqual(lines[0], 'phase=tests database=cc_test_shared exit=3')
        logs = dict(line.split('=', 1) for line in lines[1:])
        self.assertEqual(Path(logs['stdout_log']).read_text(), '')
        self.assertEqual(Path(logs['stderr_log']).read_text(),
                         'Refusing to reset database with 2 active session(s): cc_test_shared\n'
                         'Close those sessions or explicitly drop the database with --terminate.\n')
        self.assertNotIn('dropdb ', self.commands.read_text())
        self.assertNotIn('odoo ', self.commands.read_text())

    def test_compact_help_does_not_run_commands(self):
        for command in ('test-module', 'verify-module'):
            result = self.invoke(command, '--help')
            self.assertEqual((result.returncode, result.stderr), (0, ''))
            self.assertIn('[--compact]', result.stdout)
            self.assertIn('sequentially', result.stdout)
            self.unchanged()

    def test_configured_target_still_refuses_active_sessions(self):
        self.configure_test_database()
        self.env.update(FAKE_EXISTS='1', FAKE_SESSIONS='2')
        result = self.invoke('test-module', 'coffee')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (3, '', 'Refusing to reset database with 2 active session(s): cc_test_shared\n'
                          'Close those sessions or explicitly drop the database with --terminate.\n'))
        self.assertNotIn('dropdb ', self.commands.read_text())
        self.assertNotIn('odoo ', self.commands.read_text())

    def test_start_status_stop_create_list_and_module_status(self):
        for command, args, output in (
                ('start', ('--stop-after-init',), ''), ('status', (), ''), ('stop', (), ''),
                ('create-database', ('cc_dev_coffee',), 'Database ready: cc_dev_coffee\n'),
                ('list-databases', (), ''),
                ('module-status', ('coffee', 'cc_dev_coffee'),
                 'database=cc_dev_coffee\nmodule=coffee\ndatabase_state=missing\nmodule_state=unknown\n')):
            result = self.invoke(command, *args)
            self.assertEqual((result.returncode, result.stdout, result.stderr), (0, output, ''), command)
        self.assertIn(' --stop-after-init', self.commands.read_text())


if __name__ == '__main__':
    unittest.main()
