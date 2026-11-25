"""The suite never reads the user's machine configuration (v0.14.0 S2, S10; AGENTS.md: tests never
touch a real configuration).

tests/oasis_test_env.py points XDG_CONFIG_HOME at a fresh empty system temp directory when a test
module imports it, so the machine file `$XDG_CONFIG_HOME/oasis/config.toml` resolves to scratch, absent,
in the test process and in every subprocess that inherits its environment; test_bundle checks that
every test module imports it. A test that needs a machine file sets its own XDG_CONFIG_HOME.
"""
import oasis_test_env  # noqa: F401  first: XDG_CONFIG_HOME is scratch (tests/oasis_test_env.py)
import importlib.util
import os
from pathlib import Path
import pwd
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
TESTS = Path(__file__).resolve().parent
READER = ROOT / 'tools' / 'config.py'
# Prints where tools/config.py would look for the machine file in this environment.
PRINT_MACHINE_FILE = ('import importlib.util, sys\n'
                      'spec = importlib.util.spec_from_file_location("oasis_config_probe", sys.argv[1])\n'
                      'config = importlib.util.module_from_spec(spec); spec.loader.exec_module(config)\n'
                      'print(config.machine_file())\n')


def real_machine_files():
    """Where the user's real machine file would be: under the account's home (whatever HOME says)."""
    return {Path(pwd.getpwuid(os.getuid()).pw_dir) / '.config' / 'oasis' / 'config.toml'}


class TestEnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.scratch = Path(tempfile.mkdtemp(prefix='oasis-test-env-')).resolve()
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)

    def assert_scratch(self, machine):
        config_home = Path(os.environ['XDG_CONFIG_HOME'])
        self.assertNotIn(machine, real_machine_files())
        self.assertEqual(machine, config_home / 'oasis' / 'config.toml')
        self.assertTrue(config_home.name.startswith('oasis-test-config-'), config_home)
        self.assertEqual(config_home.parent, Path(tempfile.gettempdir()).resolve())
        self.assertFalse(os.path.lexists(machine), machine)

    def test_the_machine_file_resolves_to_scratch_in_this_process(self):
        spec = importlib.util.spec_from_file_location('oasis_config_under_test', READER)
        config = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(config)
        self.assert_scratch(config.machine_file())

    def test_the_machine_file_resolves_to_scratch_in_a_subprocess(self):
        result = subprocess.run([sys.executable, '-B', '-c', PRINT_MACHINE_FILE, str(READER)], cwd=self.scratch,
                                env={**os.environ}, capture_output=True, text=True)
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assert_scratch(Path(result.stdout.strip()))

    def test_a_hostile_home_machine_file_is_not_read(self):
        # Even with HOME at a home whose machine file declares an Enterprise, the inherited
        # environment keeps the reader on the empty scratch location.
        home = self.scratch / 'home'
        hostile = home / '.config' / 'oasis' / 'config.toml'
        hostile.parent.mkdir(parents=True)
        hostile.write_text("[series.\"19.0\"]\ncommunity = '/hostile/odoo'\nenterprise = '/hostile/enterprise'\n")
        project = self.scratch / 'acme'
        project.mkdir()
        (project / 'oasis-workspace.toml').write_text(
            "workspace_version = 1\nodoo_version = '19.0'\n\n[tooling]\ncommunity = '/x/odoo'\n"
            "environment = 'environments/acme'\nconfig = 'config/odoo.conf'\nenv_file = 'config/.env'\n"
            "compose = 'config/compose.yml'\nrequirements = 'config/requirements'\naddons_paths = ['.']\n"
            "db_service = 'db'\ndev_prefix = 'acme_dev_'\ntest_prefix = 'acme_test_'\n")
        result = subprocess.run([sys.executable, '-B', str(READER), str(project)], cwd=self.scratch,
                                env={**os.environ, 'HOME': str(home)}, capture_output=True, text=True)
        self.assertEqual((result.returncode, result.stderr), (0, ''), result.stdout)
        self.assertIn('ODOO_SOURCE=/x/odoo\n', result.stdout)
        self.assertNotIn('ENTERPRISE_SOURCE=', result.stdout)
        self.assertNotIn('/hostile/', result.stdout)

    def test_the_guard_replaces_an_inherited_config_home_and_removes_its_directory_at_exit(self):
        inherited = self.scratch / 'inherited-config'
        probe = ('import sys\nsys.path.insert(0, sys.argv[1])\nimport os, oasis_test_env\n'
                 'print(os.environ["XDG_CONFIG_HOME"]); print(sorted(os.listdir(os.environ["XDG_CONFIG_HOME"])))\n')
        result = subprocess.run([sys.executable, '-B', '-c', probe, str(TESTS)], cwd=self.scratch,
                                env={**os.environ, 'XDG_CONFIG_HOME': str(inherited)}, capture_output=True, text=True)
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        used, listing = result.stdout.splitlines()
        self.assertNotEqual(Path(used), inherited)
        self.assertTrue(Path(used).name.startswith('oasis-test-config-'), used)
        self.assertEqual(listing, '[]')
        self.assertFalse(os.path.lexists(used), used)


if __name__ == '__main__':
    unittest.main()
