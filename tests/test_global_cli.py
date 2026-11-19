"""Public global CLI checks with isolated fake tools and project roots."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / 'odoo19'
PUBLIC = ('audit-dependencies', 'bootstrap', 'check-environment', 'create-database',
          'drop-database', 'gc', 'init-dev-database', 'install-module', 'lint-module', 'list-databases', 'model-info',
          'module-status', 'odoo-shell', 'start', 'status', 'stop', 'test-module', 'update-module',
          'verify-module', 'worktree-init')


class GlobalCliTests(unittest.TestCase):
    def setUp(self):
        fixture_root = Path(__file__).resolve().parent / 'fixturesroot'
        fixture_root.mkdir(exist_ok=True)
        self.addCleanup(fixture_root.rmdir)
        self.scratch = tempfile.TemporaryDirectory(dir=fixture_root)
        self.addCleanup(self.scratch.cleanup)
        self.temp = Path(self.scratch.name)
        self.bundle = self.temp / 'bundle'
        tools = self.bundle / 'tools'
        tools.mkdir(parents=True)
        shutil.copyfile(CLI, self.bundle / 'odoo19')
        self.project = self.temp / 'a project'
        self.project.mkdir()
        (self.project / '.odoo19-agent.toml').write_text('[tooling]\nversion = "19.0"\n')
        self.log = self.temp / 'calls.json'
        self.fake = ('#!/bin/bash\nFAKE_TOOL="$0" exec python3 -c '\
                     "'import json, os, sys; "
                     "open(os.environ[\"FAKE_LOG\"], \"a\").write(json.dumps({"
                     "\"argv\": sys.argv[1:], \"root\": os.environ.get(\"ODOO19_PROJECT_ROOT\"), "
                     "\"stdin\": sys.stdin.read(), \"tool\": os.path.basename(os.environ[\"FAKE_TOOL\"])"
                     "}) + \"\\n\"); print(\"delegated\"); "
                     "print(\"delegated error\", file=sys.stderr); sys.exit(17)' "
                     '"$@"\n')
        for name in PUBLIC:
            (tools / name).write_text(self.fake)

    def invoke(self, *args, input=''):
        env = {**os.environ, 'FAKE_LOG': str(self.log), 'PYTHONDONTWRITEBYTECODE': '1',
               'ODOO19_PROJECT_ROOT': str(self.temp / 'wrong'),
               'ODOO19_TOOLS_DIR': str(self.temp / 'wrong')}
        return subprocess.run([sys.executable, '-B', str(self.bundle / 'odoo19'), *args],
                              input=input, text=True, capture_output=True, cwd=self.temp, env=env)

    def assert_no_calls(self, result, stderr):
        self.assertEqual((result.returncode, result.stdout, result.stderr), (2, '', stderr))
        self.assertFalse(self.log.exists())

    def test_help_without_project_lists_public_commands_and_explicit_contract(self):
        result = self.invoke('--help')
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stderr, '')
        self.assertIn('--project', result.stdout)
        self.assertIn('/absolute/project', result.stdout)
        self.assertIn('check-environment --quick', result.stdout)
        for name in PUBLIC:
            self.assertIn(name, result.stdout)
        [listed] = [line for line in result.stdout.splitlines() if line.startswith('Commands: ')]
        self.assertEqual(listed.removeprefix('Commands: ').split(', '), list(PUBLIC))
        self.assertFalse(self.log.exists())

    def test_dispatch_preserves_argv_stdin_exit_and_explicit_root(self):
        result = self.invoke('--project', str(self.project), 'odoo-shell', '--', '--project',
                             'two words', input='print(42)\n')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (17, 'delegated\n', 'delegated error\n'))
        self.assertEqual(json.loads(self.log.read_text()), {
            'argv': ['--', '--project', 'two words'], 'root': str(self.project),
            'stdin': 'print(42)\n', 'tool': 'odoo-shell'})

    def test_all_public_commands_preserve_dispatch(self):
        for name in PUBLIC:
            with self.subTest(command=name):
                self.log.unlink(missing_ok=True)
                result = self.invoke('--project', str(self.project), name, '--help')
                self.assertEqual((result.returncode, result.stdout, result.stderr),
                                 (17, 'delegated\n', 'delegated error\n'))
                self.assertEqual(json.loads(self.log.read_text()), {
                    'argv': ['--help'], 'root': str(self.project), 'stdin': '', 'tool': name})

    def test_existing_start_option_passes_through(self):
        result = self.invoke('--project', str(self.project), 'start', '--stop-after-init')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (17, 'delegated\n', 'delegated error\n'))
        self.assertEqual(json.loads(self.log.read_text())['argv'], ['--stop-after-init'])

    def test_rejects_bad_project_and_missing_profile_before_dispatch(self):
        absent = self.temp / 'absent'
        for args, error in (
                (('status',), 'ERROR: --project requires an absolute existing project directory.\n'),
                (('--project', 'relative', 'status'), 'ERROR: --project requires an absolute existing project directory.\n'),
                (('--project', str(absent), 'status'), 'ERROR: --project requires an absolute existing project directory.\n')):
            self.assert_no_calls(self.invoke(*args), error)
        (self.project / '.odoo19-agent.toml').unlink()
        self.assert_no_calls(self.invoke('--project', str(self.project), 'status'),
                             f'ERROR: Missing tooling configuration: {self.project / ".odoo19-agent.toml"}\n')

    def test_checkout_below_a_workspace_file_dispatches_without_profile(self):
        shutil.copyfile(ROOT / 'tools' / 'config.py', self.bundle / 'tools' / 'config.py')
        (self.project / '.odoo19-agent.toml').unlink()
        checkout = self.project / 'codigo' / 'shop'
        checkout.mkdir(parents=True)
        (self.project / 'oasis-workspace.toml').write_text('workspace_version = 1\n')
        result = self.invoke('--project', str(checkout), 'status', '--quick')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (17, 'delegated\n', 'delegated error\n'))
        self.assertEqual(json.loads(self.log.read_text()), {
            'argv': ['--quick'], 'root': str(checkout), 'stdin': '', 'tool': 'status'})
        self.log.unlink()
        # A profile on the way up ends the search: the checkout is neither legacy nor in a workspace.
        (self.project / 'codigo' / '.odoo19-agent.toml').write_text('[tooling]\n')
        self.assert_no_calls(self.invoke('--project', str(checkout), 'status'),
                             f'ERROR: Missing tooling configuration: {checkout / ".odoo19-agent.toml"}\n')

    def test_rejects_unknown_internal_and_pathlike_before_dispatch(self):
        for name in ('unknown', 'config.py', 'common.sh', 'audit_dependencies.py',
                     '../tools/status', '/bin/bash', 'status/../start'):
            self.assert_no_calls(self.invoke('--project', str(self.project), name),
                                 f'ERROR: Unsupported Odoo 19 command: {name}\n')

    def test_missing_packaged_tool_does_not_fall_back_to_inherited_tools(self):
        (self.bundle / 'tools/status').unlink()
        self.assert_no_calls(self.invoke('--project', str(self.project), 'status'),
                             f'Odoo 19 tools are not installed: {self.bundle / "tools/status"}\n')

    def test_staged_guidance_describes_full_path_and_optional_wrappers(self):
        readme = (ROOT / 'README.md').read_text()
        environment = (ROOT / 'odoo19-environment/SKILL.md').read_text()
        lifecycle = (ROOT / 'odoo19-module-lifecycle/SKILL.md').read_text()
        example = ('~/.agents/skills/odoo19/odoo19 --project /absolute/project '
                   'check-environment --quick')
        self.assertIn(example, readme)
        self.assertIn(example, environment)
        self.assertIn('Alternatively, if the project wants legacy local CLI entrypoints', readme)
        self.assertIn('Missing project wrappers alone are not a blocker', lifecycle)
        self.assertIn('mise', readme)

    def test_existing_config_guards_reject_bad_profile_before_effects(self):
        for name in ('common.sh', 'config.py', 'status'):
            shutil.copyfile(ROOT / 'tools' / name, self.bundle / 'tools' / name)
        profile = self.project / '.odoo19-agent.toml'
        for text, error in (
                ('[tooling]\nversion = "18.0"\n', 'ERROR: Tooling requires Odoo 19.0 and Python 3.12.\n'),
                ('[tooling]\nversion = "19.0"\npython_version = "3.12"\n'
                 'dev_prefix = "unsafe"\ntest_prefix = "unsafe"\n',
                 'ERROR: Unsafe tooling database prefixes.\n')):
            profile.write_text(text)
            self.assert_no_calls(self.invoke('--project', str(self.project), 'status'), error)


if __name__ == '__main__':
    unittest.main()
