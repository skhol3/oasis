"""`oasis setup` asks for the Python environment it would create (v0.15.0 S8).

On a terminal (standard input and standard error), when setup would create the environment of a new
workspace or of a new series section and neither --environment nor --python is given, it asks: Enter
creates it, or the absolute path of an existing environment is adopted as --environment adopts one.
For a new one it asks the Python, one the series supports, the default marked; a wrong answer is
asked again. --python <x.y> gives that Python without asking. End of input or Ctrl-C at a question
changes nothing. Without a terminal setup asks nothing (tests/test_setup.py and
tests/test_setup_series.py run it with stdin from /dev/null and their plans stay byte for byte).

The terminal is a pseudo-terminal (pty) that is the controlling terminal of the setup process, with
echo off so what is read from it is exactly what setup writes to standard error; every directory is
scratch, through the fixtures of tests/test_setup.py and tests/test_setup_series.py (fake uv,
scratch XDG_CONFIG_HOME and HOME, git without configuration).
"""
import oasis_test_env  # noqa: F401  first: XDG_CONFIG_HOME is scratch (tests/oasis_test_env.py)
import errno
import fcntl
import os
from pathlib import Path
import pty
import select
import shutil
import subprocess
import sys
import termios
import time
import unittest

import test_setup
import test_setup_series

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / 'oasis'
DRY_RUN = 'dry run: nothing changed; run with --apply to set up\n'
PYTHONS_19 = '3.10, 3.11, 3.12, 3.13, 3.14'
PYTHONS_15 = '3.7, 3.8, 3.9, 3.10, 3.11, 3.12'


def environment_prompt(series, environment):
    return (f'Python environment for Odoo {series}: Enter creates {environment}, or type the absolute path of '
            'an existing environment to use instead: ')


def python_prompt(environment, pythons, default):
    return f'Python of the new environment {environment}, one of {pythons} [Enter: {default}]: '


def asked_again(answer, series, pythons, default):
    return f'{answer} is not a Python Odoo {series} supports; answer one of {pythons}, or Enter for {default}.\n'


def no_answer(series):
    return (f'ERROR: No answer for the Python environment of Odoo {series} (end of input): nothing changed; pass '
            '--environment <dir> or --python <x.y>.\n')


INTERRUPTED = '\nERROR: Interrupted at a question: nothing changed.\n'


def on_terminal(arguments, env, cwd, steps):
    """Run oasis with a pseudo-terminal as its controlling terminal (stdin and stderr), echo and output
    translation off. steps: (text setup writes, bytes to type once it has) in order. Returns the exit
    status, standard output and everything written to the terminal."""
    master, slave = pty.openpty()
    attributes = termios.tcgetattr(slave)
    attributes[1] &= ~termios.ONLCR
    attributes[3] &= ~termios.ECHO
    termios.tcsetattr(slave, termios.TCSANOW, attributes)

    def controlling():
        os.setsid()
        fcntl.ioctl(0, termios.TIOCSCTTY, 0)
    process = subprocess.Popen([sys.executable, '-B', str(CLI), *arguments], stdin=slave, stdout=subprocess.PIPE,
                               stderr=slave, env=env, cwd=cwd, text=True, preexec_fn=controlling)
    os.close(slave)
    written, position = b'', 0

    def read(timeout):
        nonlocal written
        if not select.select([master], [], [], timeout)[0]:
            return False
        try:
            chunk = os.read(master, 4096)
        except OSError as exc:
            if exc.errno != errno.EIO:
                raise
            chunk = b''
        written += chunk
        return bool(chunk)
    try:
        for expected, typed in steps:
            expected = expected.encode()
            deadline = time.monotonic() + 30
            while written.find(expected, position) < 0 and time.monotonic() < deadline and process.poll() is None:
                read(0.2)
            while read(0.1):
                pass
            found = written.find(expected, position)
            if found < 0:
                process.kill()
                stdout, _ = process.communicate(timeout=30)
                raise AssertionError(f'never asked {expected!r}; the terminal had {written!r}, stdout {stdout!r}')
            position = found + len(expected)
            os.write(master, typed)
        stdout, _ = process.communicate(timeout=60)
        while read(0.2):
            pass
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate()
        os.close(master)
    return process.returncode, stdout, written.decode()


@unittest.skipUnless(shutil.which('git'), 'git is required')
class NewWorkspacePromptTests(unittest.TestCase):
    """A new workspace (Odoo 19.0, the shop checkout of tests/test_setup.py)."""
    setUp = test_setup.SetupTests.setUp
    git = test_setup.SetupTests.git
    odoo_source = test_setup.SetupTests.odoo_source
    module = test_setup.SetupTests.module
    setup_cmd = test_setup.SetupTests.setup_cmd
    tree = test_setup.SetupTests.tree
    compose_name = test_setup.SetupTests.compose_name
    plan = test_setup.SetupTests.plan
    port_of = test_setup.SetupTests.port_of
    assert_refused = test_setup.SetupTests.assert_refused
    existing_environment = test_setup.SetupTests.existing_environment

    def terminal(self, *arguments, steps=()):
        return on_terminal(['--project', str(self.checkout), 'setup', *arguments], self.env, self.scratch, steps)

    def venv(self):
        return self.checkout / '.oasis/venv'

    def named(self, python):
        """The fixture's new workspace file with the default named environment of that Python."""
        return (test_setup.WORKSPACE.format(base='.oasis/').replace("environment = '.oasis/venv'\n", '')
                + f"\n[environments.default]\npath = '.oasis/venv'\npython = '{python}'\n")

    def test_on_a_terminal_the_plan_asks_and_enter_twice_gives_the_plan_without_a_terminal(self):
        before = self.tree()
        status, stdout, written = self.terminal('--community', str(self.source), '--no-enterprise', steps=(
            (environment_prompt('19.0', self.venv()), b'\n'), (python_prompt(self.venv(), PYTHONS_19, '3.12'), b'\n')))
        self.assertEqual((status, stdout), (0, self.plan(self.port_of(stdout)) + DRY_RUN), written)
        self.assertEqual(written, environment_prompt('19.0', self.venv()) + python_prompt(self.venv(), PYTHONS_19,
                                                                                          '3.12'))
        self.assertEqual(self.tree(), before)
        self.assertFalse(self.log.exists())

    def test_on_a_terminal_apply_adopts_an_answered_environment_as_environment_adopts_it(self):
        environment = self.existing_environment('shop', '3.12.3')
        workspace = self.checkout / 'oasis-workspace.toml'
        requirements = self.checkout / '.oasis/config/requirements'
        status, stdout, written = self.terminal('--apply', '--community', str(self.source), '--no-enterprise', steps=(
            (environment_prompt('19.0', self.venv()), f'{environment}\n'.encode()),))
        self.assertEqual((status, written), (0, environment_prompt('19.0', self.venv())), stdout)
        plan = self.plan(self.port_of(stdout)).replace("  environment = '.oasis/venv'",
                                                       f"  environment = '{environment}'")
        plan = plan.replace(
            f'create the environment {self.venv()} with Python 3.12 (uv venv) and sync dev.txt (uv pip sync)',
            f'adopt the environment {environment} (answered): Python 3.12 (its pyvenv.cfg); setup never creates, '
            'syncs or deletes it')
        self.assertTrue(stdout.startswith(plan + f'verified: {self.checkout} loads its configuration from {workspace}\n'
                                          f'compiled {requirements}/runtime.txt, dev.txt and lock.sha256\n'
                                          'next steps:\n'), stdout)
        self.assertIn(f'bootstrap --apply syncs the adopted environment {environment} to them', stdout)
        self.assertEqual(workspace.read_text(), test_setup.WORKSPACE.format(base='.oasis/').replace(
            "environment = '.oasis/venv'", f"environment = '{environment}'"))
        self.assertEqual(self.log.read_text().splitlines(), [
            f'uv pip compile --python-version 3.12 runtime.in -o runtime.txt (in {requirements})',
            f'uv pip compile --python-version 3.12 dev.in -o dev.txt (in {requirements})'])
        self.assertFalse((self.scratch / 'python-ran').exists())
        self.assertFalse(self.venv().exists())

    def test_an_answered_path_is_refused_as_environment_refuses_it(self):
        plain = self.scratch / 'plain'
        plain.mkdir()
        old = self.existing_environment('old', '3.9.18')
        before = self.tree()
        for answer, message in (
                ('envs/shop', '--environment requires an absolute existing directory.'),
                (str(self.scratch / 'missing'), '--environment requires an absolute existing directory.'),
                (str(plain), f'--environment {plain} is not a Python environment (no pyvenv.cfg).'),
                (str(old), f'--environment {old} has Python 3.9, which Odoo 19.0 does not support (3.10 to 3.14).')):
            with self.subTest(answer=answer):
                status, stdout, written = self.terminal('--apply', '--community', str(self.source), '--no-enterprise',
                                                        steps=((environment_prompt('19.0', self.venv()),
                                                                f'{answer}\n'.encode()),))
                self.assertEqual((status, stdout, written),
                                 (2, '', environment_prompt('19.0', self.venv()) + f'ERROR: {message}\n'))
                self.assertEqual(self.tree(), before)
                self.assertFalse(self.log.exists())

    def test_a_python_answer_gives_the_new_environment_its_python_and_a_wrong_one_is_asked_again(self):
        prompt = python_prompt(self.venv(), PYTHONS_19, '3.12')
        status, stdout, written = self.terminal('--apply', '--community', str(self.source), '--no-enterprise', steps=(
            (environment_prompt('19.0', self.venv()), b'\n'), (prompt, b'3.9\n'), (prompt, b'x\n'),
            (prompt, b'3.13\n')))
        self.assertEqual(status, 0, written + stdout)
        self.assertEqual(written, environment_prompt('19.0', self.venv()) + prompt
                         + asked_again('3.9', '19.0', PYTHONS_19, '3.12') + prompt
                         + asked_again('x', '19.0', PYTHONS_19, '3.12') + prompt)
        requirements = self.checkout / '.oasis/config/requirements'
        self.assertIn(f'compile {requirements}/runtime.txt, dev.txt and lock.sha256 with Python 3.13 (uv pip compile)\n'
                      f'create the environment {self.venv()} with Python 3.13 (uv venv) and sync dev.txt '
                      '(uv pip sync)\n',
                      stdout)
        self.assertEqual((self.checkout / 'oasis-workspace.toml').read_text(), self.named('3.13'))
        self.assertEqual([line.split(' (in ')[0] for line in self.log.read_text().splitlines()], [
            'uv pip compile --python-version 3.13 runtime.in -o runtime.txt',
            'uv pip compile --python-version 3.13 dev.in -o dev.txt',
            f'uv venv --python 3.13 {self.venv()}',
            f'uv pip sync --python {self.venv()}/bin/python {requirements}/dev.txt'])
        values = subprocess.run([sys.executable, '-B', str(test_setup.READER), str(self.checkout)],
                                capture_output=True, text=True, env=self.env)
        self.assertIn('PYTHON_VERSION=3.13\n', values.stdout)

    def test_python_gives_the_version_without_asking(self):
        before = self.tree()
        default = self.setup_cmd('--python', '3.12', '--community', str(self.source), '--no-enterprise')
        self.assertEqual((default.returncode, default.stdout, default.stderr),
                         (0, self.plan(self.port_of(default.stdout)) + DRY_RUN, ''))
        status, stdout, written = self.terminal('--python', '3.13', '--community', str(self.source),
                                                '--no-enterprise')
        self.assertEqual((status, written), (0, ''), stdout)
        self.assertIn('with Python 3.13 (uv venv)', stdout)
        self.assertEqual(self.tree(), before)
        self.assertFalse(self.log.exists())
        result = self.setup_cmd('--apply', '--python', '3.13', '--community', str(self.source), '--no-enterprise')
        self.assertEqual((result.returncode, result.stderr), (0, ''), result.stdout)
        self.assertIn('  [environments.default]\n  path = \'.oasis/venv\'\n  python = \'3.13\'\n', result.stdout)
        self.assertEqual((self.checkout / 'oasis-workspace.toml').read_text(), self.named('3.13'))
        self.assertIn(f'uv venv --python 3.13 {self.venv()}', self.log.read_text())
        self.assertIn('uv pip compile --python-version 3.13 runtime.in', self.log.read_text())
        # Once configured, --python is an option that does not apply.
        self.log.unlink()
        before = self.tree()
        self.assert_refused(self.setup_cmd('--python', '3.13'),
                            f'--python: {self.checkout} is already configured by '
                            f'{self.checkout / "oasis-workspace.toml"}; setup only fills what is missing.', before)

    def test_python_that_the_series_does_not_support_or_that_cannot_apply_is_refused(self):
        environment = self.existing_environment('shop', '3.12.3')
        before = self.tree()
        for arguments, message in (
                (('--python', '3.9'), '--python 3.9 is not a Python Odoo 19.0 supports (3.10 to 3.14).'),
                (('--python', '3'), '--python 3 is not a Python Odoo 19.0 supports (3.10 to 3.14).'),
                (('--python', '3.12', '--environment', str(environment)),
                 '--python cannot be combined with --environment: an adopted environment keeps the Python of its '
                 'pyvenv.cfg.'),
                (('--environment', str(environment), '--python', '3.12'),
                 '--python cannot be combined with --environment: an adopted environment keeps the Python of its '
                 'pyvenv.cfg.')):
            with self.subTest(arguments=arguments):
                self.assert_refused(self.setup_cmd(*arguments, '--community', str(self.source), '--no-enterprise'),
                                    message, before)
        # The environment setup would create exists: it is kept, so there is no environment to give a Python, and
        # on a terminal nothing is asked about it.
        (self.venv() / 'bin').mkdir(parents=True)
        (self.venv() / 'pyvenv.cfg').write_text('home = /usr/bin\nversion = 3.12.3\n')
        before = self.tree()
        self.assert_refused(self.setup_cmd('--python', '3.13', '--community', str(self.source), '--no-enterprise'),
                            f'--python 3.13: the environment {self.venv()} exists and is kept; setup creates no '
                            'environment, so drop --python.', before)
        status, stdout, written = self.terminal('--community', str(self.source), '--no-enterprise')
        self.assertEqual((status, written), (0, ''), stdout)
        self.assertIn(f'kept the environment {self.venv()}\n', stdout)
        self.assertEqual(self.tree(), before)

    def test_end_of_input_or_ctrl_c_at_a_question_changes_nothing(self):
        before = self.tree()
        first = environment_prompt('19.0', self.venv())
        second = python_prompt(self.venv(), PYTHONS_19, '3.12')
        for name, steps, status, tail in (
                ('end of input, environment', ((first, b'\x04'),), 2, no_answer('19.0')),
                ('end of input, python', ((first, b'\n'), (second, b'\x04')), 2, no_answer('19.0')),
                ('ctrl-c, environment', ((first, b'\x03'),), 130, INTERRUPTED),
                ('ctrl-c, python', ((first, b'\n'), (second, b'\x03')), 130, INTERRUPTED)):
            with self.subTest(name=name):
                code, stdout, written = self.terminal('--apply', '--community', str(self.source), '--no-enterprise',
                                                      steps=steps)
                self.assertEqual((code, stdout), (status, ''), written)
                self.assertEqual(written, ''.join(prompt for prompt, _typed in steps) + tail)
                self.assertNotIn('Traceback', written)
                self.assertEqual(self.tree(), before)
                self.assertFalse(self.log.exists())

    def test_help_and_usage_name_python(self):
        result = self.setup_cmd('--help')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertIn('[--environment <dir> | --python <x.y>]', result.stdout.splitlines()[0])
        self.assertIn('--python <x.y>', result.stdout.split('\n', 1)[1])
        self.assertIn('it asks on a terminal: Enter creates it', ' '.join(result.stdout.split()))
        for arguments in (('--python',), ('--python', '3.12', '--python', '3.13')):
            with self.subTest(arguments=arguments):
                usage = self.setup_cmd(*arguments)
                self.assertEqual((usage.returncode, usage.stdout), (2, ''))
                self.assertTrue(usage.stderr.startswith('Usage: '), usage.stderr)


@unittest.skipUnless(shutil.which('git'), 'git is required')
class SeriesPromptTests(unittest.TestCase):
    """A new series section (the 15.0 checkout of the corpus-cafe workspace of tests/test_setup_series.py)."""
    setUp = test_setup_series.SeriesSetupTests.setUp
    git = test_setup_series.SeriesSetupTests.git
    odoo_source = test_setup_series.SeriesSetupTests.odoo_source
    make_module = test_setup_series.SeriesSetupTests.make_module
    write_machine = test_setup_series.SeriesSetupTests.write_machine
    series_files = test_setup_series.SeriesSetupTests.series_files
    setup_cmd = test_setup_series.SeriesSetupTests.setup_cmd
    reader = test_setup_series.SeriesSetupTests.reader
    tree = test_setup_series.SeriesSetupTests.tree
    compose_name = test_setup_series.SeriesSetupTests.compose_name
    port_of = test_setup_series.SeriesSetupTests.port_of
    assert_refused = test_setup_series.SeriesSetupTests.assert_refused
    indented = test_setup_series.SeriesSetupTests.indented
    new_plan = test_setup_series.SeriesSetupTests.new_plan
    existing_environment = test_setup_series.SeriesSetupTests.existing_environment
    billing_o15 = test_setup_series.SeriesSetupTests.billing_o15
    named = test_setup_series.SeriesSetupTests.named

    SOURCE = ('--exception', 'report_xlsx')

    def terminal(self, *arguments, steps=()):
        return on_terminal(['--project', str(self.checkout), 'setup', *arguments], self.env, self.scratch, steps)

    def venv(self):
        return self.project / 'environments/cc-15.0'

    def with_python(self, plan, python):
        """new_plan for a section whose environment has that Python."""
        return plan.replace("  environment = 'environments/cc-15.0'\n",
                            f"  environment = 'environments/cc-15.0'\n  python = '{python}'\n").replace(
            f'with Python {test_setup_series.PYTHON_15} ', f'with Python {python} ')

    def sources(self):
        return ('--community', str(self.source15), '--no-enterprise', *self.SOURCE)

    def test_on_a_terminal_the_plan_asks_and_enter_twice_gives_the_plan_without_a_terminal(self):
        self.workspace.write_text(test_setup_series.V1)
        before = self.tree()
        status, stdout, written = self.terminal(*self.sources(), steps=(
            (environment_prompt('15.0', self.venv()), b'\n'), (python_prompt(self.venv(), PYTHONS_15, '3.10'), b'\n')))
        self.assertEqual((status, stdout), (0, self.new_plan(self.port_of(stdout)) + DRY_RUN), written)
        self.assertEqual(written, environment_prompt('15.0', self.venv())
                         + python_prompt(self.venv(), PYTHONS_15, '3.10'))
        self.assertEqual(self.tree(), before)
        self.assertFalse(self.log.exists())

    def test_on_a_terminal_apply_adopts_an_answered_environment_as_environment_adopts_it(self):
        folder, environment = self.billing_o15()
        requirements = folder / 'requirements'
        before = self.tree()
        flagged = self.setup_cmd('--environment', str(environment), *self.SOURCE)
        self.assertEqual((flagged.returncode, flagged.stderr), (0, ''))
        status, stdout, written = self.terminal('--apply', *self.SOURCE, steps=(
            (environment_prompt('15.0', self.venv()), f'{environment}\n'.encode()),))
        self.assertEqual((status, written), (0, environment_prompt('15.0', self.venv())), stdout)
        # The plan of --environment, answered.
        plan = flagged.stdout[:-len(DRY_RUN)].replace(f'adopt the environment {environment} (from --environment)',
                                                      f'adopt the environment {environment} (answered)')
        self.assertTrue(stdout.startswith(plan), stdout)
        self.assertIn(f"  environment = '{environment}'\n  python = '3.8'\n", stdout)
        self.assertEqual(self.log.read_text().splitlines(), [
            f'uv pip compile --python-version 3.8 --override overrides.txt runtime.in -o runtime.txt '
            f'(in {requirements})',
            f'uv pip compile --python-version 3.8 --override overrides.txt dev.in -o dev.txt (in {requirements})'])
        self.assertFalse((self.scratch / 'python-ran').exists())
        self.assertNotEqual(self.tree(), before)

    def test_a_python_answer_gives_the_section_its_python_and_a_wrong_one_is_asked_again(self):
        self.workspace.write_text(test_setup_series.V1)
        prompt = python_prompt(self.venv(), PYTHONS_15, '3.10')
        status, stdout, written = self.terminal('--apply', *self.sources(), steps=(
            (environment_prompt('15.0', self.venv()), b'\n'), (prompt, b'3.13\n'), (prompt, b'3.8\n')))
        self.assertEqual(status, 0, written + stdout)
        self.assertEqual(written, environment_prompt('15.0', self.venv()) + prompt
                         + asked_again('3.13', '15.0', PYTHONS_15, '3.10') + prompt)
        self.assertTrue(stdout.startswith(self.with_python(self.new_plan(self.port_of(stdout)), '3.8')), stdout)
        self.assertIn("[series.\"15.0\"]\nenvironment = 'environments/cc-15.0'\npython = '3.8'\n",
                      self.workspace.read_text())
        self.assertIn(f'uv venv --python 3.8 {self.venv()}', self.log.read_text())
        values = self.reader(self.checkout)
        self.assertIn('PYTHON_VERSION=3.8\n', values.stdout)

    def test_python_gives_the_section_its_python_without_asking(self):
        self.workspace.write_text(test_setup_series.V1)
        before = self.tree()
        result = self.setup_cmd('--python', '3.8', *self.sources())
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (0, self.with_python(self.new_plan(self.port_of(result.stdout)), '3.8') + DRY_RUN, ''))
        default = self.setup_cmd('--python', '3.10', *self.sources())
        self.assertEqual((default.returncode, default.stdout, default.stderr),
                         (0, self.new_plan(self.port_of(default.stdout)) + DRY_RUN, ''))
        status, stdout, written = self.terminal('--python', '3.8', *self.sources())
        self.assertEqual((status, written), (0, ''), stdout)
        self.assertEqual(self.tree(), before)
        self.assertFalse(self.log.exists())
        for value in ('3.13', '3.6', 'three'):
            with self.subTest(value=value):
                self.assert_refused(self.setup_cmd('--python', value, *self.sources()),
                                    f'--python {value} is not a Python Odoo 15.0 supports (3.7 to 3.12).', before)
        # In a checkout of the workspace's own series there is no section to add.
        self.assert_refused(self.setup_cmd('--python', '3.12', root=self.checkout19),
                            f'--python: {self.checkout19} is already configured by {self.workspace}; setup only '
                            'fills what is missing.', before)

    def test_python_over_a_named_environment_gives_the_section_that_environment_with_the_python(self):
        text = self.named(test_setup_series.V2, 'environments/cc-{series}', '3.12')
        self.workspace.write_text(text)
        same = self.setup_cmd('--python', '3.12', *self.sources())
        self.assertEqual((same.returncode, same.stderr), (0, ''))
        self.assertNotIn('  environment =', same.stdout.split('[series."15.0"]')[2])
        result = self.setup_cmd('--apply', '--python', '3.8', *self.sources())
        self.assertEqual((result.returncode, result.stderr), (0, ''), result.stdout)
        self.assertIn("[series.\"15.0\"]\nenvironment = 'environments/cc-15.0'\npython = '3.8'\n",
                      self.workspace.read_text())
        self.assertIn(f'create the environment {self.venv()} with Python 3.8 (uv venv)', result.stdout)
        values = self.reader(self.checkout)
        for line in (f'PROJECT_ENVIRONMENT={self.venv()}', 'PYTHON_VERSION=3.8'):
            self.assertIn(line + '\n', values.stdout)
        after19 = self.reader(self.checkout19)
        self.assertEqual((after19.returncode, after19.stderr), (0, ''))
        self.assertIn('PYTHON_VERSION=3.12\n', after19.stdout)

    def test_end_of_input_or_ctrl_c_at_a_question_changes_nothing(self):
        self.workspace.write_text(test_setup_series.V1)
        before = self.tree()
        first = environment_prompt('15.0', self.venv())
        second = python_prompt(self.venv(), PYTHONS_15, '3.10')
        for name, steps, status, tail in (
                ('end of input, python', ((first, b'\n'), (second, b'\x04')), 2, no_answer('15.0')),
                ('ctrl-c, environment', ((first, b'\x03'),), 130, INTERRUPTED)):
            with self.subTest(name=name):
                code, stdout, written = self.terminal('--apply', *self.sources(), steps=steps)
                self.assertEqual((code, stdout), (status, ''), written)
                self.assertEqual(written, ''.join(prompt for prompt, _typed in steps) + tail)
                self.assertEqual(self.tree(), before)
                self.assertFalse(self.log.exists())


if __name__ == '__main__':
    unittest.main()
