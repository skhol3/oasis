"""Public CLI checks for the staged, non-secret tooling configuration reader."""
import oasis_test_env  # noqa: F401  first: XDG_CONFIG_HOME is scratch (tests/oasis_test_env.py)
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest

READER = Path(__file__).resolve().parents[1] / 'tools' / 'config.py'
# A workspace file in the checkout itself: every path resolves from the checkout, as before.
WORKSPACE = '''workspace_version = 1
odoo_version = "19.0"

[tooling]
community = "../../source/odoo"
enterprise = "../../source/enterprise"
environment = "../../environments/corpus cafe"
config = "dev/odoo.conf"
env_file = "dev/.env"
compose = "dev/compose.yml"
requirements = "dev/requirements"
addons_paths = ["."]
db_service = "db"
dev_prefix = "cc_dev_"
test_prefix = "cc_test_"
'''
# Appended after WORKSPACE_ROOT: the Odoo 19.0 options, no named environment, then DATA_DIR
# (empty without [tooling].data_dir) and AGENT_DESTRUCTIVE (ask without [tooling].agent_destructive).
APPENDED = ['ODOO_VERSION=19.0', 'ODOO_SECOND_PORT_OPTION=--gevent-port', 'ODOO_DEMO_OFF_ARGS=--without-demo',
            "ENVIRONMENT_NAME=''", 'PYTHON_VERSION=3.12', "DATA_DIR=''", 'AGENT_DESTRUCTIVE=ask']


class ConfigCliTests(unittest.TestCase):
    def setUp(self):
        fixture_root = Path(__file__).resolve().parent / 'fixturesroot'
        fixture_root.mkdir(exist_ok=True)
        self.addCleanup(fixture_root.rmdir)
        self.scratch = tempfile.TemporaryDirectory(dir=fixture_root)
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name) / 'a project'
        self.root.mkdir()
        self.workspace = self.root / 'oasis-workspace.toml'
        # No machine file: XDG_CONFIG_HOME names a scratch directory that does not exist, so these
        # checks prove the behaviour without one (never the real ~/.config).
        self.env = {**os.environ, 'PYTHONDONTWRITEBYTECODE': '1', 'XDG_CONFIG_HOME': str(Path(self.scratch.name) / 'xdg')}

    def run_reader(self):
        return subprocess.run([sys.executable, '-B', str(READER), str(self.root)],
                              capture_output=True, text=True, env=self.env)

    def test_missing_workspace_has_no_output_and_fails(self):
        result = self.run_reader()
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (2, '', f'ERROR: Missing tooling configuration: no oasis-workspace.toml at or above {self.root}.\n'))

    def test_an_old_profile_is_not_read(self):
        # v0.21.0 S6: `.odoo19-agent.toml` is neither read nor refused. Alone, the checkout has no configuration.
        (self.root / '.odoo19-agent.toml').write_text('[tooling]\nversion = "19.0"\n')
        result = self.run_reader()
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (2, '', f'ERROR: Missing tooling configuration: no oasis-workspace.toml at or above {self.root}.\n'))
        # Next to a workspace file, the workspace file configures the checkout as without the profile.
        self.workspace.write_text(WORKSPACE)
        with_profile = self.run_reader()
        (self.root / '.odoo19-agent.toml').unlink()
        self.assertEqual(with_profile.returncode, 0, with_profile.stderr)
        self.assertEqual((with_profile.stdout, with_profile.stderr), (self.run_reader().stdout, ''))

    def test_release_check_needs_the_file_and_the_series(self):
        # Its only caller, common.sh require_source, always passes the series.
        release = self.root / 'release.py'
        release.write_text('version_info = (19, 0, 0, "final", 0)\n')
        usage = ('ERROR: Usage: config.py <absolute-project-root>\n'
                 '       config.py --origins <absolute-project-root>\n'
                 '       config.py --release <release.py> <series>\n')
        for args, expected in ((('--release', str(release), '19.0'), (0, '', '')),
                               (('--release', str(release), '18.0'), (2, '', '')),
                               (('--release', str(release)), (2, '', usage)),
                               (('--release',), (2, '', usage)),
                               (('--release', str(release), '19.0', 'extra'), (2, '', usage)),
                               (('relative',), (2, '', usage)),
                               ((), (2, '', usage))):
            with self.subTest(args=args):
                result = subprocess.run([sys.executable, '-B', str(READER), *args], capture_output=True, text=True,
                                        env=self.env)
                self.assertEqual((result.returncode, result.stdout, result.stderr), expected)

    def test_wrong_version_rejected_without_emitting_assignments(self):
        self.workspace.write_text(WORKSPACE.replace('odoo_version = "19.0"', 'odoo_version = "18.0"'))
        result = self.run_reader()
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (2, '', f'ERROR: Unsupported odoo_version "18.0" in {self.workspace}; supported: 19.0, 15.0.\n'))

    def test_unsafe_prefix_rejected_without_emitting_assignments(self):
        self.workspace.write_text(WORKSPACE.replace('cc_test_', 'cc_test_; echo bad'))
        result = self.run_reader()
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (2, '', 'ERROR: Unsafe tooling database prefixes.\n'))

    def test_community_only_config_does_not_require_enterprise(self):
        self.workspace.write_text(WORKSPACE.replace('enterprise = "../../source/enterprise"\n', ''))
        result = self.run_reader()
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertNotIn('ENTERPRISE_SOURCE=', result.stdout)

    def test_ambiguous_advisory_value_is_rejected(self):
        self.workspace.write_text(
            WORKSPACE + '[odoo]\nversion = "18.0"\ncommunity = "wrong-source"\n')
        result = self.run_reader()
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (2, '', 'ERROR: Conflicting advisory and tooling values: odoo.version.\n'))

    def test_too_broad_prefix_rejected(self):
        self.workspace.write_text(WORKSPACE.replace('cc_test_', 'a_'))
        result = self.run_reader()
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (2, '', 'ERROR: Unsafe tooling database prefixes.\n'))

    def test_isolated_environment_parent_can_contain_spaces(self):
        self.workspace.write_text(
            WORKSPACE.replace('../../environments/corpus cafe',
                            '../../isolated environments/corpus cafe'))
        result = self.run_reader()
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertIn('isolated environments/corpus cafe', result.stdout)

    def test_environment_target_cannot_be_system_or_project_root(self):
        root = self.root.resolve()
        for target, resolved in (('/', '/'), ('.', root)):
            self.workspace.write_text(
                WORKSPACE.replace('../../environments/corpus cafe', target))
            result = self.run_reader()
            self.assertEqual((result.returncode, result.stdout, result.stderr),
                             (2, '', f'ERROR: Unsafe tooling environment target: {resolved} is or contains '
                                     f'the checkout {root}.\n'))

    def test_space_in_project_path_is_shell_quoted(self):
        self.workspace.write_text(WORKSPACE)
        result = self.run_reader()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, '')
        self.assertIn("PROJECT_ROOT='" + str(self.root) + "'\n", result.stdout)
        self.assertIn("PROJECT_ENVIRONMENT='" + str((self.root / '../../environments/corpus cafe').resolve()) + "'\n", result.stdout)

    def test_logs_path_is_resolved_from_the_checkout_and_emitted_before_the_workspace(self):
        self.workspace.write_text(WORKSPACE + "logs = '../shared logs'\n")
        result = self.run_reader()
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertEqual(result.stdout.splitlines()[-8:], [f'WORKSPACE_ROOT={shlex.quote(str(self.root))}', *APPENDED])
        self.assertEqual(result.stdout.splitlines()[-9],
                         "LOGS_DIR='" + str((self.root / '../shared logs').resolve()) + "'")
        self.assertEqual(result.stdout.count('LOGS_DIR='), 1)

    def test_absent_logs_key_emits_the_logs_next_to_the_workspace_file(self):
        # v0.17.0: without [tooling].logs, `logs` next to oasis-workspace.toml, as setup writes it (no dev/logs/odoo19).
        self.workspace.write_text(WORKSPACE)
        result = self.run_reader()
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertEqual(result.stdout.splitlines()[-9:],
                         [f'LOGS_DIR={shlex.quote(str(self.root / "logs"))}', f'WORKSPACE_ROOT={shlex.quote(str(self.root))}',
                          *APPENDED])

    def test_output_keeps_every_previous_assignment_and_appends_the_series_options(self):
        self.workspace.write_text(WORKSPACE)
        result = self.run_reader()
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        lines = result.stdout.splitlines()
        self.assertEqual([line.split('=', 1)[0] for line in lines], [
            'PROJECT_ROOT', 'PROJECT_NAME', 'DEV_PREFIX', 'TEST_PREFIX', 'TEST_DATABASE', 'ODOO_SOURCE',
            'ENTERPRISE_SOURCE', 'PROJECT_ENVIRONMENT', 'ODOO_CONFIG', 'ENV_FILE', 'COMPOSE_FILE',
            'REQUIREMENTS_DIR', 'ADDON_ROOTS', 'DB_SERVICE', 'PYTHON', 'ODOO_BIN', 'ENVIRONMENTS_DIR',
            'CHECKOUT_KIND', 'CHECKOUT_SLUG', 'CHECKOUT_MAIN_ROOT', 'LOGS_DIR', 'WORKSPACE_ROOT',
            'ODOO_VERSION', 'ODOO_SECOND_PORT_OPTION', 'ODOO_DEMO_OFF_ARGS', 'ENVIRONMENT_NAME',
            'PYTHON_VERSION', 'DATA_DIR', 'AGENT_DESTRUCTIVE'])
        self.assertEqual(lines[-7:], APPENDED)
        # The Python is derived (the series' default for [tooling].environment), never set.
        self.workspace.write_text(WORKSPACE + 'python_version = "3.13"\n')
        result = self.run_reader()
        self.assertEqual((result.returncode, result.stdout, result.stderr), (2, '', (
            f'ERROR: [tooling].python_version is derived in a workspace; remove it from {self.workspace}.\n')))

    def test_invalid_logs_path_is_rejected_without_emitting_assignments(self):
        for value in ('""', '7', '["logs"]', '"a\\nb"', '"a\\u0000b"'):
            with self.subTest(value=value):
                self.workspace.write_text(WORKSPACE + f'logs = {value}\n')
                result = self.run_reader()
                self.assertEqual((result.returncode, result.stdout, result.stderr),
                                 (2, '', 'ERROR: Invalid tooling path: logs.\n'))

    def test_agent_destructive_is_emitted_last_and_defaults_to_ask(self):
        for value in ('ask', 'deny', 'allow'):
            with self.subTest(value=value):
                self.workspace.write_text(WORKSPACE + f'agent_destructive = "{value}"\n')
                result = self.run_reader()
                self.assertEqual((result.returncode, result.stderr), (0, ''))
                self.assertEqual(result.stdout.splitlines()[-2:], ["DATA_DIR=''", f'AGENT_DESTRUCTIVE={value}'])
        self.workspace.write_text(WORKSPACE)
        result = self.run_reader()
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertEqual(result.stdout.splitlines()[-1], 'AGENT_DESTRUCTIVE=ask')

    def test_invalid_agent_destructive_is_rejected_without_emitting_assignments(self):
        for value in ('""', '"never"', '"Ask"', '"allow "', 'true', '1', '["ask"]'):
            with self.subTest(value=value):
                self.workspace.write_text(WORKSPACE + f'agent_destructive = {value}\n')
                result = self.run_reader()
                self.assertEqual((result.returncode, result.stdout, result.stderr),
                                 (2, '', 'ERROR: Invalid tooling agent_destructive: use ask, deny or allow.\n'))


if __name__ == '__main__':
    unittest.main()
