"""Public global CLI checks with isolated fake tools and project roots."""
import oasis_test_env  # noqa: F401  first: XDG_CONFIG_HOME is scratch (tests/oasis_test_env.py)
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / 'oasis'
# Entry points sharing one dispatcher: `oasis`, and `odoo19` kept as an alias.
PROGRAMS = ('oasis', 'odoo19')
PUBLIC = ('audit-dependencies', 'bootstrap', 'check-environment', 'create-database', 'doctor',
          'drop-database', 'gc', 'init-dev-database', 'install-module', 'lint-module', 'list-databases',
          'menu', 'migrate', 'model-info', 'module-info', 'module-status', 'odoo-shell', 'restart', 'setup', 'start',
          'status', 'stop', 'test-module', 'trash', 'update-module', 'verify-module', 'view-info', 'worktree-init',
          'xmlid-info')


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
        for program in PROGRAMS:
            shutil.copyfile(ROOT / program, self.bundle / program)
        self.project = self.temp / 'a project'
        self.project.mkdir()
        # The entry point finds the workspace file with the packaged tools/config.py.
        shutil.copyfile(ROOT / 'tools' / 'config.py', tools / 'config.py')
        (self.project / 'oasis-workspace.toml').write_text('workspace_version = 1\n')
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

    def invoke(self, *args, input='', program='oasis', cwd=None):
        # git stops below the scratch directory (never this repository), and the machine file is
        # looked for in a scratch directory that does not exist (never the real ~/.config).
        env = {**{key: value for key, value in os.environ.items() if not key.startswith('GIT_')},
               'FAKE_LOG': str(self.log), 'PYTHONDONTWRITEBYTECODE': '1',
               'GIT_CEILING_DIRECTORIES': str(self.temp.parent), 'GIT_CONFIG_GLOBAL': os.devnull,
               'GIT_CONFIG_NOSYSTEM': '1', 'XDG_CONFIG_HOME': str(self.temp / 'xdg'),
               'ODOO19_PROJECT_ROOT': str(self.temp / 'wrong'),
               'ODOO19_TOOLS_DIR': str(self.temp / 'wrong'),
               'OASIS_PROJECT_ROOT': str(self.temp / 'wrong'),
               'OASIS_ENTRYPOINT': str(self.temp / 'wrong'),
               'OASIS_TOOLS_DIR': str(self.temp / 'wrong')}
        return subprocess.run([sys.executable, '-B', str(self.bundle / program), *args],
                              input=input, text=True, capture_output=True, cwd=cwd or self.temp, env=env)

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

    def test_both_entry_points_dispatch_identically(self):
        # Every command, option, exit code and output is the same; help names the invoked program.
        observed = {}
        for program in PROGRAMS:
            with self.subTest(program=program):
                self.log.unlink(missing_ok=True)
                help_text = self.invoke('--help', program=program)
                self.assertEqual((help_text.returncode, help_text.stderr), (0, ''))
                self.assertTrue(help_text.stdout.startswith(f'usage: {program} [-h] [--project /absolute/project]'),
                                help_text.stdout)
                self.assertIn(f'Example: {program} --project /absolute/project check-environment --quick',
                              help_text.stdout)
                usage = self.invoke('--bogus', program=program)
                self.assertEqual(usage.returncode, 2)
                self.assertTrue(usage.stderr.startswith(f'usage: {program} '), usage.stderr)
                runs = [self.invoke('--project', str(self.project), 'odoo-shell', '--', 'two words',
                                    input='print(42)\n', program=program),
                        self.invoke('--project', str(self.project), 'unknown', program=program),
                        self.invoke('status', program=program)]
                observed[program] = (
                    help_text.stdout.replace(f'usage: {program} ', 'usage: PROG ', 1)
                    .replace(f'Example: {program} ', 'Example: PROG ').replace(f'&& {program} ', '&& PROG '),
                    usage.stderr.replace(program, 'PROG'),
                    [(run.returncode, run.stdout, run.stderr) for run in runs],
                    json.loads(self.log.read_text()))
        self.assertEqual(observed['oasis'], observed['odoo19'])
        # Without --project the current directory (here outside git, with no workspace file) is the project.
        self.assertEqual(observed['oasis'][2], [
            (17, 'delegated\n', 'delegated error\n'),
            (2, '', 'ERROR: Unsupported oasis command: unknown\n'),
            (2, '', f'ERROR: Missing tooling configuration: no oasis-workspace.toml at or above {self.temp}.\n')])

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

    def test_entry_point_sets_both_variable_names(self):
        # OASIS_* and the legacy ODOO19_* carry the same values; neither tools directory is inherited.
        names = [f'{prefix}_{name}' for name in ('PROJECT_ROOT', 'ENTRYPOINT', 'TOOLS_DIR')
                 for prefix in ('OASIS', 'ODOO19')]
        (self.bundle / 'tools/status').write_text(
            '#!/bin/bash\nexec python3 -c \'import json, os, sys; '
            'open(os.environ["FAKE_LOG"], "a").write(json.dumps({name: os.environ.get(name) '
            'for name in sys.argv[1:]}))\' ' + ' '.join(names) + '\n')
        for program in PROGRAMS:
            with self.subTest(program=program):
                self.log.unlink(missing_ok=True)
                result = self.invoke('--project', str(self.project), 'status', program=program)
                self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))
                entrypoint = str((self.bundle / program).resolve())
                self.assertEqual(json.loads(self.log.read_text()), {
                    'OASIS_PROJECT_ROOT': str(self.project), 'ODOO19_PROJECT_ROOT': str(self.project),
                    'OASIS_ENTRYPOINT': entrypoint, 'ODOO19_ENTRYPOINT': entrypoint,
                    'OASIS_TOOLS_DIR': None, 'ODOO19_TOOLS_DIR': None})

    def test_existing_start_option_passes_through(self):
        result = self.invoke('--project', str(self.project), 'start', '--stop-after-init')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (17, 'delegated\n', 'delegated error\n'))
        self.assertEqual(json.loads(self.log.read_text())['argv'], ['--stop-after-init'])

    def test_rejects_bad_project_and_missing_profile_before_dispatch(self):
        absent = self.temp / 'absent'
        for args, error in (
                (('--project', '', 'status'), 'ERROR: --project requires an absolute existing project directory.\n'),
                (('--project', 'relative', 'status'), 'ERROR: --project requires an absolute existing project directory.\n'),
                (('--project', str(absent), 'status'), 'ERROR: --project requires an absolute existing project directory.\n')):
            self.assert_no_calls(self.invoke(*args), error)
        (self.project / 'oasis-workspace.toml').unlink()
        self.assert_no_calls(self.invoke('--project', str(self.project), 'status'),
                             f'ERROR: Missing tooling configuration: no oasis-workspace.toml at or above {self.project}.\n')

    def test_a_legacy_profile_is_refused_before_dispatch_except_for_migrate_and_doctor(self):
        profile = self.project / '.odoo19-agent.toml'
        profile.write_text('[tooling]\nversion = "19.0"\n')
        for program in PROGRAMS:
            with self.subTest(program=program):
                self.assert_no_calls(self.invoke('--project', str(self.project), 'status', program=program), (
                    f'ERROR: {profile} is the old profile format, no longer read: run {program} migrate --plan to '
                    f'see its conversion to oasis-workspace.toml, then {program} migrate --apply.\n'))
        # Without the workspace file next to it, the same refusal (not the missing configuration).
        (self.project / 'oasis-workspace.toml').unlink()
        self.assertIn('is the old profile format', self.invoke('--project', str(self.project), 'list-databases').stderr)
        # migrate converts it and doctor reports it: both still run.
        for command in ('migrate', 'doctor'):
            with self.subTest(command=command):
                result = self.invoke('--project', str(self.project), command, '--plan')
                self.assertEqual((result.returncode, result.stdout, result.stderr),
                                 (17, 'delegated\n', 'delegated error\n'))
                self.assertEqual(json.loads(self.log.read_text()), {
                    'argv': ['--plan'], 'root': str(self.project), 'stdin': '', 'tool': command})
                self.log.unlink()

    def test_setup_runs_without_a_workspace_file_and_every_other_command_still_needs_one(self):
        # v0.14.0 S1: setup creates the workspace file, so it is the one command that runs before it.
        (self.project / 'oasis-workspace.toml').unlink()
        plain = self.temp / 'plain'
        plain.mkdir()
        for program in PROGRAMS:
            for args, cwd in ((('--project', str(self.project), 'setup', '--plan'), self.temp),
                              (('setup', '--plan'), plain)):
                with self.subTest(program=program, args=args):
                    self.log.unlink(missing_ok=True)
                    result = self.invoke(*args, program=program, cwd=cwd)
                    self.assertEqual((result.returncode, result.stdout, result.stderr),
                                     (17, 'delegated\n', 'delegated error\n'))
                    root = self.project if '--project' in args else plain
                    self.assertEqual(json.loads(self.log.read_text()),
                                     {'argv': ['--plan'], 'root': str(root), 'stdin': '', 'tool': 'setup'})
            # doctor runs too, so its FAIL can say `fix: oasis setup --apply`.
            self.log.unlink(missing_ok=True)
            result = self.invoke('--project', str(self.project), 'doctor', program=program, cwd=self.temp)
            self.assertEqual((result.returncode, result.stdout, result.stderr), (17, 'delegated\n', 'delegated error\n'))
            self.assertEqual(json.loads(self.log.read_text())['tool'], 'doctor')
            self.log.unlink(missing_ok=True)
            self.assert_no_calls(self.invoke('--project', str(self.project), 'status', program=program),
                                 f'ERROR: Missing tooling configuration: no oasis-workspace.toml at or above '
                                 f'{self.project}.\n')
        # A legacy profile is still refused before setup: migrate converts it.
        profile = self.project / '.odoo19-agent.toml'
        profile.write_text('[tooling]\n')
        self.assert_no_calls(self.invoke('--project', str(self.project), 'setup'), (
            f'ERROR: {profile} is the old profile format, no longer read: run oasis migrate --plan to '
            'see its conversion to oasis-workspace.toml, then oasis migrate --apply.\n'))

    def test_checkout_below_a_workspace_file_dispatches(self):
        (self.project / 'oasis-workspace.toml').unlink()
        checkout = self.project / 'codigo' / 'shop'
        checkout.mkdir(parents=True)
        (self.project / 'oasis-workspace.toml').write_text('workspace_version = 1\n')
        result = self.invoke('--project', str(checkout), 'status', '--quick')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (17, 'delegated\n', 'delegated error\n'))
        self.assertEqual(json.loads(self.log.read_text()), {
            'argv': ['--quick'], 'root': str(checkout), 'stdin': '', 'tool': 'status'})
        self.log.unlink()
        # A legacy profile above the checkout is not read and no longer ends the search.
        (self.project / 'codigo' / '.odoo19-agent.toml').write_text('[tooling]\n')
        result = self.invoke('--project', str(checkout), 'status')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (17, 'delegated\n', 'delegated error\n'))

    def test_without_project_the_current_directory_outside_git_is_the_project(self):
        # v0.14.0 S8: the same dispatch as --project <current directory>, through either entry point.
        below = self.project / 'addons'
        below.mkdir()
        for program in PROGRAMS:
            for cwd in (self.project, below):
                with self.subTest(program=program, cwd=str(cwd)):
                    self.log.unlink(missing_ok=True)
                    implicit = self.invoke('status', '--quick', program=program, cwd=cwd, input='x\n')
                    implicit_call = json.loads(self.log.read_text())
                    self.log.unlink()
                    explicit = self.invoke('--project', str(cwd), 'status', '--quick', program=program, cwd=cwd,
                                           input='x\n')
                    self.assertEqual((implicit.returncode, implicit.stdout, implicit.stderr),
                                     (17, 'delegated\n', 'delegated error\n'))
                    self.assertEqual((implicit.returncode, implicit.stdout, implicit.stderr),
                                     (explicit.returncode, explicit.stdout, explicit.stderr))
                    self.assertEqual(implicit_call, json.loads(self.log.read_text()))
                    self.assertEqual(implicit_call, {'argv': ['--quick'], 'root': str(cwd), 'stdin': 'x\n',
                                                     'tool': 'status'})

    def test_without_project_an_unconfigured_directory_is_refused_like_an_explicit_one(self):
        plain = self.temp / 'plain'
        plain.mkdir()
        for program in PROGRAMS:
            with self.subTest(program=program):
                implicit = self.invoke('status', program=program, cwd=plain)
                explicit = self.invoke('--project', str(plain), 'status', program=program, cwd=plain)
                self.assert_no_calls(implicit, f'ERROR: Missing tooling configuration: no oasis-workspace.toml '
                                               f'at or above {plain}.\n')
                self.assertEqual((implicit.returncode, implicit.stdout, implicit.stderr),
                                 (explicit.returncode, explicit.stdout, explicit.stderr))
        # A legacy profile in the current directory: the same refusal, and migrate still runs.
        profile = plain / '.odoo19-agent.toml'
        profile.write_text('[tooling]\n')
        self.assert_no_calls(self.invoke('status', cwd=plain), (
            f'ERROR: {profile} is the old profile format, no longer read: run oasis migrate --plan to '
            'see its conversion to oasis-workspace.toml, then oasis migrate --apply.\n'))
        result = self.invoke('migrate', '--plan', cwd=plain)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (17, 'delegated\n', 'delegated error\n'))
        self.assertEqual(json.loads(self.log.read_text())['root'], str(plain))

    def test_help_says_where_the_project_comes_from_without_project(self):
        for program in PROGRAMS:
            with self.subTest(program=program):
                result = self.invoke('--help', program=program)
                self.assertEqual((result.returncode, result.stderr), (0, ''))
                text = ' '.join(result.stdout.split())
                self.assertIn('without it, the git top level of the current directory '
                              '(the current directory outside git)', text)
                self.assertIn(f'Example: cd /absolute/project && {program} check-environment --quick', result.stdout)
        self.assertFalse(self.log.exists())

    def test_rejects_unknown_internal_and_pathlike_before_dispatch(self):
        for name in ('unknown', 'config.py', 'common.sh', 'audit_dependencies.py',
                     '../tools/status', '/bin/bash', 'status/../start'):
            self.assert_no_calls(self.invoke('--project', str(self.project), name),
                                 f'ERROR: Unsupported oasis command: {name}\n')

    def test_missing_packaged_tool_does_not_fall_back_to_inherited_tools(self):
        (self.bundle / 'tools/status').unlink()
        self.assert_no_calls(self.invoke('--project', str(self.project), 'status'),
                             f'oasis tools are not installed: {self.bundle / "tools/status"}\n')

    def test_staged_guidance_describes_full_path_and_optional_wrappers(self):
        # The setup and tool-manager sections moved from the README to their topic files.
        setup = (ROOT / 'docs/project-setup.md').read_text()
        troubleshooting = (ROOT / 'docs/troubleshooting.md').read_text()
        environment = (ROOT / 'odoo19-environment/SKILL.md').read_text()
        lifecycle = (ROOT / 'odoo19-module-lifecycle/SKILL.md').read_text()
        example = ('~/.agents/skills/odoo19/oasis --project /absolute/project '
                   'check-environment --quick')
        self.assertIn(example, setup)
        self.assertIn(example, environment)
        self.assertIn('Alternatively, if the project wants legacy local CLI entrypoints', setup)
        self.assertIn('Missing project wrappers alone are not a blocker', lifecycle)
        self.assertIn('mise', troubleshooting)

    def test_existing_config_guards_reject_bad_workspace_before_effects(self):
        for name in ('common.sh', 'oasis_env.sh', 'config.py', 'odoo_versions.py', 'status'):
            shutil.copyfile(ROOT / 'tools' / name, self.bundle / 'tools' / name)
        workspace = self.project / 'oasis-workspace.toml'
        for text, error in (
                ('workspace_version = 1\nodoo_version = "18.0"\n[tooling]\n',
                 f'ERROR: Unsupported odoo_version "18.0" in {workspace}; supported: 19.0, 15.0.\n'),
                ('workspace_version = 1\nodoo_version = "19.0"\n[tooling]\n'
                 'dev_prefix = "unsafe"\ntest_prefix = "unsafe"\n',
                 'ERROR: Unsafe tooling database prefixes.\n')):
            workspace.write_text(text)
            self.assert_no_calls(self.invoke('--project', str(self.project), 'status'), error)


if __name__ == '__main__':
    unittest.main()
