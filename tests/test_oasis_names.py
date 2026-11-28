"""oasis names in what the harness reads, sets and prints (v0.8.0 S2, S4). Since v0.17.0 (S3) only the
OASIS_* names are read: a legacy ODOO19_* variable is ignored, and neither the entry point nor a project
wrapper sets one.

The lifecycle fixture (fake docker/python, private runtime directory) and the public tools,
run directly with the variables the entry point or a project wrapper sets.
"""
import oasis_test_env  # noqa: F401  first: XDG_CONFIG_HOME is scratch (tests/oasis_test_env.py)
from pathlib import Path
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest

import test_lifecycle as lifecycle

BACKUP_STAMP = re.compile(r'\.bak-\d{8}T\d{6}Z')

ROOT = lifecycle.STAGE
TOOLS = ROOT / 'tools'
VARIABLES = ('PROJECT_ROOT', 'ENTRYPOINT', 'TOOLS_DIR', 'COMPOSE_LOCK_TIMEOUT', 'RUN_RESULT', 'REUSE_RESULT')
WRAPPERS = sorted((ROOT / 'project-wrappers').iterdir())
WRAPPER_VARIABLES = ('OASIS_PROJECT_ROOT', 'ODOO19_PROJECT_ROOT', 'OASIS_ENTRYPOINT', 'ODOO19_ENTRYPOINT',
                     'OASIS_TOOLS_DIR', 'ODOO19_TOOLS_DIR')
# Wrappers whose usage names the installed tool, not the wrapper: they set no entry point.
NO_ENTRYPOINT = {'common.sh', 'install-module', 'start', 'status', 'stop', 'test-module'}
ROOT_ERROR_SHELL = 'OASIS_PROJECT_ROOT must name an existing project directory.\n'
ROOT_ERROR = 'ERROR: OASIS_PROJECT_ROOT must name an absolute existing project directory.\n'
# Python tools that read the project root, with arguments that reach that check.
PYTHON_TOOLS = (('model-info', ('sale.order',)), ('module-info', ('sale',)), ('view-info', ('sale.order',)),
                ('xmlid-info', ('sale.view_order_form',)), ('lint-module', ('coffee',)),
                ('worktree-init', ('feat', 'feature/x', '--dry-run')), ('migrate', ()), ('doctor', ()))


class OasisVariableTests(unittest.TestCase):
    setUp_fixture = lifecycle.LifecycleTests.setUp

    def setUp(self):
        self.setUp_fixture()
        for prefix in ('OASIS_', 'ODOO19_'):
            for name in VARIABLES:
                self.env.pop(prefix + name, None)
        self.wrong = str(self.root / 'absent')

    def tool(self, command, *args, **variables):
        return subprocess.run(['bash', str(TOOLS / command), *args], text=True, cwd=self.root,
                              env={**self.env, **variables}, capture_output=True)

    def observed(self, result):
        # migrate's plan names backups with the current second (.bak-<YYYYMMDDTHHMMSSZ>); two runs
        # may fall in different seconds, so the stamp is not part of what is compared.
        def plain(text):
            return BACKUP_STAMP.sub('.bak-<stamp>', text)
        return result.returncode, plain(result.stdout), plain(result.stderr)

    def test_shell_tools_read_oasis_names_first(self):
        result = self.tool('check-environment', '--bogus', OASIS_PROJECT_ROOT=str(self.root),
                           OASIS_ENTRYPOINT='/opt/bin/oasis', ODOO19_PROJECT_ROOT=self.wrong,
                           ODOO19_ENTRYPOINT='/opt/old/oasis')
        self.assertEqual(self.observed(result), (2, '', 'Usage: /opt/bin/oasis [--quick|--full]\n'))

    def test_shell_tools_ignore_the_legacy_variable_names(self):
        # v0.17.0 S3: ODOO19_PROJECT_ROOT, ODOO19_ENTRYPOINT and ODOO19_COMPOSE_LOCK_TIMEOUT are not read.
        result = self.tool('check-environment', '--bogus', ODOO19_PROJECT_ROOT=str(self.root),
                           ODOO19_ENTRYPOINT='/opt/old/oasis')
        self.assertEqual(self.observed(result), (2, '', ROOT_ERROR_SHELL))
        result = self.tool('check-environment', '--bogus', OASIS_PROJECT_ROOT=str(self.root),
                           ODOO19_ENTRYPOINT='/opt/old/oasis')
        self.assertEqual(self.observed(result), (2, '', f'Usage: {TOOLS / "check-environment"} [--quick|--full]\n'))
        result = self.tool('check-environment', '--bogus', OASIS_PROJECT_ROOT=self.wrong,
                           ODOO19_PROJECT_ROOT=str(self.root))
        self.assertEqual(self.observed(result), (2, '', ROOT_ERROR_SHELL))

    def test_shell_tools_name_oasis_project_root_when_neither_is_set(self):
        self.assertEqual(self.observed(self.tool('check-environment')), (2, '', ROOT_ERROR_SHELL))

    def test_python_tools_name_oasis_project_root_when_neither_is_set(self):
        for command, args in PYTHON_TOOLS:
            with self.subTest(command=command):
                self.assertEqual(self.observed(self.tool(command, *args)), (2, '', ROOT_ERROR))

    def test_python_tools_read_only_oasis_project_root(self):
        for command, args in PYTHON_TOOLS:
            with self.subTest(command=command):
                oasis = self.tool(command, *args, OASIS_PROJECT_ROOT=str(self.root),
                                  ODOO19_PROJECT_ROOT=self.wrong)
                self.assertNotIn('PROJECT_ROOT', oasis.stderr)
                legacy = self.tool(command, *args, ODOO19_PROJECT_ROOT=str(self.root))
                self.assertEqual(self.observed(legacy), (2, '', ROOT_ERROR))
                wins = self.tool(command, *args, OASIS_PROJECT_ROOT=self.wrong,
                                 ODOO19_PROJECT_ROOT=str(self.root))
                self.assertEqual(self.observed(wins), (2, '', ROOT_ERROR))

    def test_doctor_reads_the_project_of_oasis_project_root_only(self):
        result = self.tool('doctor', OASIS_PROJECT_ROOT=str(self.root))
        self.assertEqual(result.stdout.splitlines()[0], 'PASS configuration=workspace')
        self.assertEqual(self.observed(self.tool('doctor', ODOO19_PROJECT_ROOT=str(self.root))), (2, '', ROOT_ERROR))

    def test_python_usage_names_the_oasis_entry_point_first(self):
        for command in ('doctor', 'migrate'):
            for variables, program in (
                    ({'OASIS_ENTRYPOINT': '/opt/bin/oasis', 'ODOO19_ENTRYPOINT': '/opt/old/oasis'}, '/opt/bin/oasis'),
                    ({'ODOO19_ENTRYPOINT': '/opt/old/oasis'}, 'oasis'),
                    ({}, 'oasis')):
                with self.subTest(command=command, variables=variables):
                    result = self.tool(command, '--bogus', **variables)
                    self.assertEqual((result.returncode, result.stdout), (2, ''))
                    self.assertEqual(result.stderr.split()[:3], ['Usage:', program, command],
                                     result.stderr)

    def test_run_results_pass_only_under_the_oasis_names(self):
        # RUN_RESULT and REUSE_RESULT pass between test-module --compact and the run it starts;
        # a legacy name in the caller's environment is not read.
        for args, name in ((('coffee',), 'RUN_RESULT'), (('--reuse', 'coffee'), 'REUSE_RESULT')):
            with self.subTest(name=name):
                written = self.root / f'written-{name}'
                result = self.tool('test-module', *args, OASIS_PROJECT_ROOT=str(self.root),
                                   **{f'OASIS_{name}': str(written)})
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(written.read_text(), 'yes\n' if name == 'RUN_RESULT' else 'install\n')
                stale = self.root / f'stale-{name}'
                result = self.tool('test-module', *args, OASIS_PROJECT_ROOT=str(self.root),
                                   **{f'ODOO19_{name}': str(stale)})
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertFalse(stale.exists())


class WrapperVariableTests(unittest.TestCase):
    setUp = lifecycle.LifecycleTests.setUp
    invoke = lifecycle.LifecycleTests.invoke
    unchanged = lifecycle.LifecycleTests.unchanged

    def fake_tools(self):
        """A tools directory whose every tool (and common.sh) records the wrapper's variables."""
        tools = self.root / 'fake tools'
        tools.mkdir()
        recorder = ('python3 -c \'import json, os, sys; json.dump({name: os.environ.get(name) for name in '
                    'sys.argv[2:]}, open(sys.argv[1], "w"))\' "$FAKE_ENV_OUT" ' + ' '.join(WRAPPER_VARIABLES) + '\n')
        for wrapper in WRAPPERS:
            if not wrapper.name.endswith('.py'):
                (tools / wrapper.name).write_text('#!/usr/bin/env bash\n' + recorder)
        # The Python wrappers run their helper with this Python (check_environment.py) or read
        # the configuration with config.py, then run the helper with the profile's Python.
        (tools / 'check_environment.py').write_text(
            'import json, os, sys\n'
            f'json.dump({{name: os.environ.get(name) for name in {WRAPPER_VARIABLES!r}}}, '
            'open(os.environ["FAKE_ENV_OUT"], "w"))\n')
        for name in ('config.py', 'odoo_versions.py'):
            (tools / name).write_bytes((TOOLS / name).read_bytes())
        (tools / 'audit_dependencies.py').touch()
        return tools

    def test_every_wrapper_sets_only_the_oasis_names(self):
        # v0.17.0 S3: no wrapper sets an ODOO19_* variable; a caller's legacy one passes through unread.
        for prefix in ('OASIS_', 'ODOO19_'):
            for name in VARIABLES:
                self.env.pop(prefix + name, None)
        tools = self.fake_tools()
        self.env['OASIS_TOOLS_DIR'] = str(tools)
        self.env['ODOO19_TOOLS_DIR'] = str(self.root / 'legacy tools')
        scripts = self.root / 'dev/scripts'
        scripts.mkdir(parents=True)
        self.assertEqual(len(WRAPPERS), 17)  # v0.20.0: no create-database wrapper
        for wrapper in WRAPPERS:
            with self.subTest(wrapper=wrapper.name):
                path = scripts / wrapper.name
                path.write_bytes(wrapper.read_bytes())
                out = self.root / f'env-{wrapper.name}.json'
                env = {**self.env, 'FAKE_ENV_OUT': str(out)}
                if wrapper.name.endswith('.py'):
                    argv = [sys.executable, '-B', str(path)]
                elif wrapper.name == 'common.sh':
                    argv = ['bash', '-c', 'source "$1"', 'caller', str(path)]
                else:
                    argv = ['bash', str(path)]
                result = subprocess.run(argv, text=True, cwd=self.root, env=env, capture_output=True)
                self.assertEqual((result.returncode, result.stderr), (0, ''), result.stdout)
                if wrapper.name == 'audit_dependencies.py':
                    # It passes the root as an argument; the profile's (fake) Python ran the helper.
                    self.assertIn(f'odoo {tools / "audit_dependencies.py"} --project-root {self.root} ',
                                  self.commands.read_text())
                    self.commands.unlink()
                    continue
                seen = json.loads(out.read_text())
                if wrapper.name == 'check_environment.py':
                    # The lockfile CLI takes paths as arguments and sets no variable.
                    self.assertEqual(seen, {**dict.fromkeys(WRAPPER_VARIABLES), 'OASIS_TOOLS_DIR': str(tools),
                                            'ODOO19_TOOLS_DIR': str(self.root / 'legacy tools')})
                    continue
                entrypoint = None if wrapper.name in NO_ENTRYPOINT else str(path)
                self.assertEqual(seen, {
                    'OASIS_PROJECT_ROOT': str(self.root), 'ODOO19_PROJECT_ROOT': None,
                    'OASIS_ENTRYPOINT': entrypoint, 'ODOO19_ENTRYPOINT': None,
                    'OASIS_TOOLS_DIR': str(tools), 'ODOO19_TOOLS_DIR': str(self.root / 'legacy tools')})
        self.unchanged()

    def test_wrappers_override_stale_oasis_names(self):
        # A wrapper sets OASIS_PROJECT_ROOT and OASIS_ENTRYPOINT, so a stale value of the caller is never read.
        self.env.update(OASIS_PROJECT_ROOT=str(self.root / 'absent'), OASIS_ENTRYPOINT='/stale/oasis')
        result = self.invoke('update-module', 'coffee')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (2, '', 'Usage: ' + str(self.root / 'dev/scripts/update-module') + ' <module> <database>\n'))
        self.unchanged()

    def test_wrappers_ignore_the_legacy_tools_dir(self):
        # v0.17.0 S3: ODOO19_TOOLS_DIR is not read; without OASIS_TOOLS_DIR a wrapper uses the install directory.
        home = self.root / 'home'
        self.env.pop('OASIS_TOOLS_DIR', None)
        self.env.update(HOME=str(home), ODOO19_TOOLS_DIR=str(TOOLS))
        installed = home / '.agents/skills/oasis/tools'
        result = self.invoke('status')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (2, '', f'oasis tools are not installed: {installed / "status"}\n'))
        for name in ('check_environment.py', 'audit_dependencies.py'):
            with self.subTest(wrapper=name):
                path = self.root / 'dev/scripts' / name
                path.write_bytes((ROOT / 'project-wrappers' / name).read_bytes())
                result = subprocess.run([sys.executable, '-B', str(path)], text=True, cwd=self.root,
                                        env=self.env, capture_output=True)
                self.assertEqual((result.returncode, result.stdout, result.stderr),
                                 (2, '', f'oasis tools are not installed: {installed / name}\n'))
        self.unchanged()

    def test_wrappers_read_oasis_tools_dir(self):
        self.env['OASIS_TOOLS_DIR'] = str(self.root / 'not installed')
        result = self.invoke('status')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (2, '', 'oasis tools are not installed: ' + str(self.root / 'not installed/status') + '\n'))
        for name, helper in (('check_environment.py', 'check_environment.py'),
                             ('audit_dependencies.py', 'audit_dependencies.py')):
            with self.subTest(wrapper=name):
                path = self.root / 'dev/scripts' / name
                path.write_bytes((ROOT / 'project-wrappers' / name).read_bytes())
                result = subprocess.run([sys.executable, '-B', str(path)], text=True, cwd=self.root,
                                        env=self.env, capture_output=True)
                self.assertEqual((result.returncode, result.stdout, result.stderr),
                                 (2, '', 'oasis tools are not installed: ' +
                                  str(self.root / 'not installed' / helper) + '\n'))
        self.unchanged()


class EntryPointHelpTests(unittest.TestCase):
    """Help that tells the user to run a command names the invoked entry point (S4)."""

    def setUp(self):
        fixture_root = Path(__file__).resolve().parent / 'fixturesroot'
        fixture_root.mkdir(exist_ok=True)
        self.addCleanup(fixture_root.rmdir)
        self.scratch = tempfile.TemporaryDirectory(dir=fixture_root)
        self.addCleanup(self.scratch.cleanup)
        self.project = Path(self.scratch.name)
        (self.project / 'oasis-workspace.toml').write_text('[tooling]\nversion = "19.0"\n')

    def run_help(self, program, *args):
        env = {key: value for key, value in os.environ.items()
               if not key.startswith(('OASIS_', 'ODOO19_'))}
        return subprocess.run([sys.executable, '-B', str(ROOT / program), *args], text=True,
                              cwd=self.project, env={**env, 'PYTHONDONTWRITEBYTECODE': '1'},
                              capture_output=True)

    def test_gc_hints_name_the_invoked_entry_point(self):
        for program in ('oasis',):
            for command, hint in (
                    ('test-module', f'behind: {program} gc lists such databases and {program} gc --apply drops them.\n'),
                    ('verify-module', f'Ctrl+C; {program} gc drops what a killed run left behind.')):
                with self.subTest(program=program, command=command):
                    result = self.run_help(program, '--project', str(self.project), command, '--help')
                    self.assertEqual((result.returncode, result.stderr), (0, ''))
                    self.assertIn(hint, result.stdout)

    def test_an_entry_point_file_named_odoo19_still_makes_hints_name_oasis(self):
        # v0.17.0 S3: the program a hint names is `oasis`, whatever the entry point's file name.
        for variables in ({'OASIS_ENTRYPOINT': '/opt/old/odoo19'},):
            for command, hint in (
                    ('test-module', 'behind: oasis gc lists such databases and oasis gc --apply drops them.\n'),
                    ('verify-module', 'Ctrl+C; oasis gc drops what a killed run left behind.')):
                with self.subTest(variables=variables, command=command):
                    env = {key: value for key, value in os.environ.items()
                           if not key.startswith(('OASIS_', 'ODOO19_'))}
                    result = subprocess.run(['bash', str(TOOLS / command), '--help'], text=True,
                                            cwd=self.project, capture_output=True,
                                            env={**env, 'PYTHONDONTWRITEBYTECODE': '1',
                                                 'OASIS_PROJECT_ROOT': str(self.project), **variables})
                    self.assertEqual((result.returncode, result.stderr), (0, ''))
                    self.assertIn(hint, result.stdout)
                    self.assertNotIn('odoo19 gc', result.stdout)

    def test_no_help_names_odoo_19_or_a_fixed_odoo19_command(self):
        commands = ('test-module', 'verify-module', 'update-module', 'odoo-shell', 'gc', 'stop',
                    'doctor', 'migrate', 'model-info', 'module-info', 'view-info', 'xmlid-info', 'lint-module',
                    'worktree-init')
        outputs = [self.run_help('oasis', '--help')]
        outputs += [self.run_help('oasis', '--project', str(self.project), command, '--help')
                    for command in commands]
        for command, result in zip(('--help', *commands), outputs):
            with self.subTest(command=command):
                self.assertEqual((result.returncode, result.stderr), (0, ''))
                self.assertNotIn('Odoo 19', result.stdout)
                self.assertNotIn('odoo19 ', result.stdout)
                self.assertNotIn('odoo19/<', result.stdout)


if __name__ == '__main__':
    unittest.main()
