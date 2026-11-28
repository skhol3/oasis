"""`oasis setup-postgres` (v0.16.0 S1, S6; named start-database before v0.20.0 S13): starts this checkout's database
service, Tier A, naming no env file. `start-database` stays as its deprecated alias: the same output and exit codes,
and one stderr line naming setup-postgres.

An agent harness may refuse any command that names an env file, so setup's next steps, `status --json` and
doctor name this command instead of the raw `docker compose --env-file ... up -d --wait`. The fake docker of
test_lifecycle records every call; FAKE_UP_FAIL makes `compose up` fail with a message that names the env file.
"""
import oasis_test_env  # noqa: F401  first: XDG_CONFIG_HOME is scratch (tests/oasis_test_env.py)
import shlex
import subprocess
import sys
import unittest

import test_lifecycle as lifecycle

ROOT = lifecycle.STAGE
PROGRAMS = ('oasis',)


class StartDatabaseTests(unittest.TestCase):
    setUp_fixture = lifecycle.LifecycleTests.setUp

    def setUp(self):
        self.setUp_fixture()
        self.env_file = self.root / 'dev/.env'
        self.compose_file = self.root / 'dev/compose.yml'
        docker = self.bindir / 'docker'
        head, tail = docker.read_text().rsplit('exit 0\n', 1)
        docker.write_text(head + 'case "$*" in\n'
                          '  *" up -d "*) if [ -n "${FAKE_UP_FAIL:-}" ]; then\n'
                          '      echo "Container db Creating" >&2\n'
                          '      echo "env file $3 is not valid" >&2; exit 3; fi\n'
                          '      echo "Container db Running" >&2 ;;\n'
                          'esac\nexit 0\n' + tail)

    def cli(self, *args, program='oasis', command='setup-postgres'):
        result = subprocess.run([sys.executable, '-B', str(ROOT / program), '--project', str(self.root),
                                 command, *args], text=True, capture_output=True, cwd=self.root,
                                env=self.env)
        # No output names the env file: a harness may refuse a command an agent copies from it.
        self.assertNotIn(str(self.env_file), result.stdout + result.stderr)
        return result

    def calls(self):
        return self.commands.read_text().splitlines() if self.commands.exists() else []

    def up(self):
        return (f'docker compose --env-file {self.env_file} -f {self.compose_file} '
                'up -d --wait --wait-timeout 60 db')

    def test_it_starts_the_service_as_the_database_commands_do_and_prints_one_line(self):
        for program in PROGRAMS:
            with self.subTest(program=program):
                self.commands.unlink(missing_ok=True)
                result = self.cli(program=program)
                self.assertEqual((result.returncode, result.stdout, result.stderr),
                                 (0, f'database service db is running ({self.compose_file})\n', ''))
                # common.sh wait_for_database: compose up of the service, nothing else.
                self.assertEqual(self.calls(), [self.up()])

    def test_a_failure_prints_what_compose_said_without_the_env_file_and_names_doctor(self):
        self.env['FAKE_UP_FAIL'] = '1'
        result = self.cli()
        doctor = shlex.join(['oasis', '--project', str(self.root), 'doctor'])
        self.assertEqual((result.returncode, result.stdout, result.stderr), (1, '', (
            'Container db Creating\nenv file [tooling].env_file is not valid\n'
            f'ERROR: the database service db did not start (exit 3); {doctor} checks its '
            'configuration.\n')))
        self.assertEqual(self.calls(), [self.up()])

    def test_a_missing_compose_or_env_file_names_setup_and_starts_nothing(self):
        setup = shlex.join(['oasis', '--project', str(self.root), 'setup', '--apply'])
        self.env_file.unlink()
        result = self.cli()
        self.assertEqual((result.returncode, result.stdout, result.stderr), (1, '', (
            f'ERROR: the env file of this checkout ([tooling].env_file) is missing: {setup} creates it.\n')))
        self.env_file.touch()
        self.compose_file.unlink()
        result = self.cli()
        self.assertEqual((result.returncode, result.stdout, result.stderr), (1, '', (
            f'ERROR: the compose file {self.compose_file} is missing: {setup} creates it.\n')))
        self.assertEqual(self.calls(), [])

    def test_usage_and_help(self):
        usage = f'Usage: {(ROOT / "oasis").resolve()}\n'
        for args in (('extra',), ('--help', 'extra'), ('--wait',)):
            with self.subTest(args=args):
                result = self.cli(*args)
                self.assertEqual((result.returncode, result.stdout, result.stderr), (2, '', usage))
        result = self.cli('--help')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertTrue(result.stdout.startswith(usage), result.stdout)
        self.assertIn('stop --database stops it', result.stdout)
        self.assertEqual(self.calls(), [])


class StartDatabaseAliasTests(unittest.TestCase):
    """v0.20.0 S13: start-database runs setup-postgres exactly, with one deprecation line first on stderr."""
    setUp_fixture = lifecycle.LifecycleTests.setUp
    setUp = StartDatabaseTests.setUp
    cli = StartDatabaseTests.cli
    calls = StartDatabaseTests.calls
    DEPRECATION = 'WARNING: start-database is a deprecated alias of setup-postgres: run setup-postgres instead.\n'

    def test_the_alias_runs_the_same_and_prints_the_deprecation_line(self):
        cases = [((), {}), (('--help',), {}), (('extra',), {}), ((), {'FAKE_UP_FAIL': '1'})]
        for args, variables in cases:
            with self.subTest(args=args, variables=variables):
                self.env.update(variables)
                self.commands.unlink(missing_ok=True)
                new = self.cli(*args)
                new_calls = self.calls()
                self.commands.unlink(missing_ok=True)
                old = self.cli(*args, command='start-database')
                self.assertEqual((old.returncode, old.stdout, old.stderr),
                                 (new.returncode, new.stdout, self.DEPRECATION + new.stderr))
                self.assertEqual(self.calls(), new_calls)
                for name in variables:
                    del self.env[name]
        # What it prints names the new name only (setup-postgres), never the alias, apart from that line.
        self.env['FAKE_UP_FAIL'] = '1'
        old = self.cli(command='start-database')
        self.assertNotIn('start-database', old.stdout + old.stderr.removeprefix(self.DEPRECATION))


if __name__ == '__main__':
    unittest.main()
