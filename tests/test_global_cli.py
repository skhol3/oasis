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
# The one entry point (v0.17.0 S3: the `odoo19` alias is gone).
PROGRAMS = ('oasis',)


# v0.20.0 S12: create-database is the one creator (init-dev-database is gone); S13: setup-postgres and
# recreate-postgres-volume. v0.21.0 S7: the deprecated aliases are gone.
PUBLIC = ('audit-dependencies', 'bootstrap', 'create-database', 'doctor',
          'drop-database', 'gc', 'install-module', 'lint-module', 'list-databases',
          'menu', 'model-info', 'module-info', 'module-status', 'odoo-shell', 'policy',
          'recreate-postgres-volume', 'restart', 'setup', 'setup-postgres', 'start',
          'status', 'stop', 'test-module', 'trash', 'update-module', 'verify-module', 'view-info',
          'worktree-init', 'xmlid-info')
# v0.21.0 S7: the deprecated aliases (v0.16.0 S5, v0.20.0 S13) and the command each named.
REMOVED_ALIASES = {'check-environment': 'doctor --environment', 'start-database': 'setup-postgres',
                   'recreate-database-volume': 'recreate-postgres-volume'}


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
                     "\"argv\": sys.argv[1:], \"root\": os.environ.get(\"OASIS_PROJECT_ROOT\"), "
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
        self.assertIn('doctor --environment --quick', result.stdout)
        # v0.21.0 S7: the deprecated aliases are gone from the command list and the help.
        self.assertNotIn('Deprecated aliases', result.stdout)
        for name in ('init-dev-database', *REMOVED_ALIASES):
            self.assertNotIn(name, result.stdout)
        for name in PUBLIC:
            self.assertIn(name, result.stdout)
        [listed] = [line for line in result.stdout.splitlines() if line.startswith('Commands: ')]
        self.assertEqual(listed.removeprefix('Commands: ').split(', '), list(PUBLIC))
        self.assertFalse(self.log.exists())

    def test_the_entry_point_under_any_file_name_dispatches_identically_and_names_oasis(self):
        # v0.17.0 S3: a copy of the entry point under another name (an `odoo19` left from an earlier
        # version, a link of the user's) runs every command alike, and help and usage name `oasis`.
        for name in ('odoo19', 'my-oasis'):
            shutil.copyfile(ROOT / 'oasis', self.bundle / name)
        observed = {}
        for program in ('oasis', 'odoo19', 'my-oasis'):
            with self.subTest(program=program):
                self.log.unlink(missing_ok=True)
                help_text = self.invoke('--help', program=program)
                self.assertEqual((help_text.returncode, help_text.stderr), (0, ''))
                self.assertTrue(help_text.stdout.startswith('usage: oasis [-h] [--project /absolute/project]'),
                                help_text.stdout)
                self.assertIn('Example: oasis --project /absolute/project doctor --environment --quick',
                              help_text.stdout)
                self.assertNotIn(program, help_text.stdout.replace('oasis', ''))
                usage = self.invoke('--bogus', program=program)
                self.assertEqual(usage.returncode, 2)
                self.assertTrue(usage.stderr.startswith('usage: oasis '), usage.stderr)
                runs = [self.invoke('--project', str(self.project), 'odoo-shell', '--', 'two words',
                                    input='print(42)\n', program=program),
                        self.invoke('--project', str(self.project), 'unknown', program=program),
                        self.invoke('status', program=program)]
                observed[program] = (help_text.stdout, usage.stderr,
                                     [(run.returncode, run.stdout, run.stderr) for run in runs],
                                     json.loads(self.log.read_text()))
        self.assertEqual(observed['odoo19'], observed['oasis'])
        self.assertEqual(observed['my-oasis'], observed['oasis'])
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

    def test_entry_point_sets_only_the_oasis_variable_names(self):
        # v0.17.0 S3: OASIS_PROJECT_ROOT and OASIS_ENTRYPOINT are set, OASIS_TOOLS_DIR is not inherited; the
        # legacy ODOO19_* the caller set pass through unchanged, since no tool reads them.
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
                    'OASIS_PROJECT_ROOT': str(self.project), 'ODOO19_PROJECT_ROOT': str(self.temp / 'wrong'),
                    'OASIS_ENTRYPOINT': entrypoint, 'ODOO19_ENTRYPOINT': None,
                    'OASIS_TOOLS_DIR': None, 'ODOO19_TOOLS_DIR': str(self.temp / 'wrong')})

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

    def test_an_old_profile_is_not_read(self):
        # v0.21.0 S6: `.odoo19-agent.toml` is neither read nor refused: next to a workspace file the command runs,
        # without one the checkout is unconfigured like any other.
        (self.project / '.odoo19-agent.toml').write_text('[tooling]\nversion = "19.0"\n')
        result = self.invoke('--project', str(self.project), 'status')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (17, 'delegated\n', 'delegated error\n'))
        self.log.unlink()
        (self.project / 'oasis-workspace.toml').unlink()
        self.assert_no_calls(self.invoke('--project', str(self.project), 'list-databases'),
                             f'ERROR: Missing tooling configuration: no oasis-workspace.toml at or above {self.project}.\n')

    def test_migrate_is_gone(self):
        # v0.21.0 S6: migrate only converted `.odoo19-agent.toml`; the name runs nothing, even with its tool on disk.
        (self.bundle / 'tools/migrate').write_text(self.fake)
        (self.project / '.odoo19-agent.toml').write_text('[tooling]\n')
        for args in (('migrate',), ('migrate', '--plan')):
            self.assert_no_calls(self.invoke('--project', str(self.project), *args),
                                 'ERROR: Unsupported oasis command: migrate\n')

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

    def test_policy_runs_without_a_workspace_file(self):
        # v0.16.0 S1: the agent contract is readable before any configuration exists.
        (self.project / 'oasis-workspace.toml').unlink()
        plain = self.temp / 'plain'
        plain.mkdir()
        for program in PROGRAMS:
            for args, cwd in ((('--project', str(self.project), 'policy', '--json'), self.temp),
                              (('policy', '--json'), plain)):
                with self.subTest(program=program, args=args):
                    self.log.unlink(missing_ok=True)
                    result = self.invoke(*args, program=program, cwd=cwd)
                    self.assertEqual((result.returncode, result.stdout, result.stderr),
                                     (17, 'delegated\n', 'delegated error\n'))
                    self.assertEqual(json.loads(self.log.read_text())['tool'], 'policy')

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
        # An old profile in the current directory is not read: the same refusal.
        (plain / '.odoo19-agent.toml').write_text('[tooling]\n')
        self.assert_no_calls(self.invoke('status', cwd=plain), f'ERROR: Missing tooling configuration: no '
                                                               f'oasis-workspace.toml at or above {plain}.\n')

    def test_help_says_where_the_project_comes_from_without_project(self):
        for program in PROGRAMS:
            with self.subTest(program=program):
                result = self.invoke('--help', program=program)
                self.assertEqual((result.returncode, result.stderr), (0, ''))
                text = ' '.join(result.stdout.split())
                self.assertIn('without it, the git top level of the current directory '
                              '(the current directory outside git)', text)
                self.assertIn(f'Example: cd /absolute/project && {program} doctor --environment --quick', result.stdout)
        self.assertFalse(self.log.exists())

    def test_init_dev_database_is_gone_without_an_alias(self):
        # v0.20.0 S12: create-database replaces it; the old name runs nothing, even with its tool on disk.
        (self.bundle / 'tools/init-dev-database').write_text(self.fake)
        self.assert_no_calls(self.invoke('--project', str(self.project), 'init-dev-database', 'coffee', 'cc_dev_x'),
                             'ERROR: Unsupported oasis command: init-dev-database\n')

    def test_the_deprecated_aliases_are_gone(self):
        # v0.21.0 S7: each old name runs nothing, even with its tool on disk: refused like any unknown command
        # (as migrate is), with or without arguments and a workspace file.
        for name in REMOVED_ALIASES:
            (self.bundle / 'tools' / name).write_text(self.fake)
        plain = self.temp / 'plain'
        plain.mkdir()
        for name in REMOVED_ALIASES:
            for args in ((), ('--full',), ('--confirm', 'cc-shop'), ('--help',)):
                for project in (self.project, plain):
                    with self.subTest(name=name, args=args, project=project.name):
                        self.assert_no_calls(self.invoke('--project', str(project), name, *args),
                                             f'ERROR: Unsupported oasis command: {name}\n')
        # The bundle ships neither their tool scripts nor the check-environment project wrapper.
        for name in REMOVED_ALIASES:
            self.assertFalse((ROOT / 'tools' / name).exists(), name)
        self.assertFalse((ROOT / 'project-wrappers/check-environment').exists())
        # The commands they named still run.
        for name, args in (('doctor', ('--environment', '--full')), ('setup-postgres', ()),
                           ('recreate-postgres-volume', ('--confirm', 'cc-shop'))):
            with self.subTest(command=name):
                self.log.unlink(missing_ok=True)
                result = self.invoke('--project', str(self.project), name, *args)
                self.assertEqual((result.returncode, result.stdout, result.stderr),
                                 (17, 'delegated\n', 'delegated error\n'))
                self.assertEqual(json.loads(self.log.read_text()),
                                 {'argv': list(args), 'root': str(self.project), 'stdin': '', 'tool': name})

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
        environment = (ROOT / 'odoo-environment/SKILL.md').read_text()
        lifecycle = (ROOT / 'odoo-module-lifecycle/SKILL.md').read_text()
        example = ('~/.agents/skills/oasis/oasis --project /absolute/project '
                   'doctor --environment --quick')
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
