"""Public CLI checks for the staged, non-secret tooling configuration reader."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

READER = Path(__file__).resolve().parents[1] / 'tools' / 'config.py'
PROFILE = '''[tooling]
version = "19.0"
python_version = "3.12"
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


class ConfigCliTests(unittest.TestCase):
    def setUp(self):
        fixture_root = Path(__file__).resolve().parent / 'fixturesroot'
        fixture_root.mkdir(exist_ok=True)
        self.addCleanup(fixture_root.rmdir)
        self.scratch = tempfile.TemporaryDirectory(dir=fixture_root)
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name) / 'a project'
        self.root.mkdir()

    def run_reader(self):
        return subprocess.run([sys.executable, '-B', str(READER), str(self.root)],
                              capture_output=True, text=True, env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})

    def test_missing_profile_has_no_output_and_fails(self):
        result = self.run_reader()
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (2, '', 'ERROR: Missing tooling configuration: ' + str(self.root / '.odoo19-agent.toml') + '\n'))

    def test_wrong_version_rejected_without_emitting_assignments(self):
        (self.root / '.odoo19-agent.toml').write_text(PROFILE.replace('version = "19.0"', 'version = "18.0"'))
        result = self.run_reader()
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (2, '', 'ERROR: Tooling requires Odoo 19.0 and Python 3.12.\n'))

    def test_unsafe_prefix_rejected_without_emitting_assignments(self):
        (self.root / '.odoo19-agent.toml').write_text(PROFILE.replace('cc_test_', 'cc_test_; echo bad'))
        result = self.run_reader()
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (2, '', 'ERROR: Unsafe tooling database prefixes.\n'))

    def test_community_only_config_does_not_require_enterprise(self):
        (self.root / '.odoo19-agent.toml').write_text(PROFILE.replace('enterprise = "../../source/enterprise"\n', ''))
        result = self.run_reader()
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertNotIn('ENTERPRISE_SOURCE=', result.stdout)

    def test_ambiguous_advisory_value_is_rejected(self):
        (self.root / '.odoo19-agent.toml').write_text(
            '[odoo]\nversion = "18.0"\ncommunity = "wrong-source"\n' + PROFILE)
        result = self.run_reader()
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (2, '', 'ERROR: Conflicting advisory and tooling values: odoo.version.\n'))

    def test_too_broad_prefix_rejected(self):
        (self.root / '.odoo19-agent.toml').write_text(PROFILE.replace('cc_test_', 'a_'))
        result = self.run_reader()
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (2, '', 'ERROR: Unsafe tooling database prefixes.\n'))

    def test_isolated_environment_parent_can_contain_spaces(self):
        (self.root / '.odoo19-agent.toml').write_text(
            PROFILE.replace('../../environments/corpus cafe',
                            '../../isolated environments/corpus cafe'))
        result = self.run_reader()
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertIn('isolated environments/corpus cafe', result.stdout)

    def test_environment_target_cannot_be_system_or_project_root(self):
        for target in ('/', '.'):
            (self.root / '.odoo19-agent.toml').write_text(
                PROFILE.replace('../../environments/corpus cafe', target))
            result = self.run_reader()
            self.assertEqual((result.returncode, result.stdout, result.stderr),
                             (2, '', 'ERROR: Unsafe tooling environment target.\n'))

    def test_space_in_project_path_is_shell_quoted(self):
        (self.root / '.odoo19-agent.toml').write_text(PROFILE)
        result = self.run_reader()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, '')
        self.assertIn("PROJECT_ROOT='" + str(self.root) + "'\n", result.stdout)
        self.assertIn("PROJECT_ENVIRONMENT='" + str((self.root / '../../environments/corpus cafe').resolve()) + "'\n", result.stdout)

    def test_logs_path_is_resolved_from_the_checkout_and_emitted_last(self):
        (self.root / '.odoo19-agent.toml').write_text(PROFILE + "logs = '../shared logs'\n")
        result = self.run_reader()
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertEqual(result.stdout.splitlines()[-1],
                         "LOGS_DIR='" + str((self.root / '../shared logs').resolve()) + "'")
        self.assertEqual(result.stdout.count('LOGS_DIR='), 1)

    def test_absent_logs_key_emits_an_empty_logs_dir_last(self):
        (self.root / '.odoo19-agent.toml').write_text(PROFILE)
        result = self.run_reader()
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertEqual(result.stdout.splitlines()[-1], "LOGS_DIR=''")

    def test_invalid_logs_path_is_rejected_without_emitting_assignments(self):
        for value in ('""', '7', '["logs"]', '"a\\nb"', '"a\\u0000b"'):
            with self.subTest(value=value):
                (self.root / '.odoo19-agent.toml').write_text(PROFILE + f'logs = {value}\n')
                result = self.run_reader()
                self.assertEqual((result.returncode, result.stdout, result.stderr),
                                 (2, '', 'ERROR: Invalid tooling path: logs.\n'))


if __name__ == '__main__':
    unittest.main()
