"""`oasis status --json`: what is ready, what is missing and the next oasis command (v0.16.0 S3).

The checkout is tests/test_setup.py's fixture, configured with `oasis setup --apply` and its fake uv; docker is
a fake that answers `compose ps` with FAKE_PS and the database query with FAKE_DATABASES, and records every call,
so nothing reaches a real service.
"""
import oasis_test_env  # noqa: F401  first: XDG_CONFIG_HOME is scratch (tests/oasis_test_env.py)
import importlib.util
import json
import os
import shlex
import subprocess
import sys
import unittest
from unittest import mock

import test_setup
from test_setup import CLI, ROOT

DOCKER = '''#!/bin/sh
printf 'docker %s\\n' "$*" >> "$FAKE_DOCKER_LOG"
case "$*" in
  *" ps --format json "*) [ -z "${FAKE_PS_FAIL:-}" ] || exit 1; printf '%s' "${FAKE_PS:-}" ;;
  *"SELECT datname FROM pg_database"*) [ -z "${FAKE_QUERY_FAIL:-}" ] || exit 1; printf '%s' "${FAKE_DATABASES:-}" ;;
  *) exit 9 ;;
esac
'''
CHECKS = ('workspace', 'environment', 'locks', 'database_service', 'databases', 'server')
RUNNING = '{"Service":"db","State":"running","Health":"healthy"}\n'


class StatusJsonTests(unittest.TestCase):
    setUp_fixture = test_setup.SetupTests.setUp
    git = test_setup.SetupTests.git
    odoo_source = test_setup.SetupTests.odoo_source
    module = test_setup.SetupTests.module
    setup_cmd = test_setup.SetupTests.setup_cmd

    def setUp(self):
        self.setUp_fixture()
        (self.bindir / 'docker').write_text(DOCKER)
        (self.bindir / 'docker').chmod(0o755)
        self.docker_log = self.scratch / 'docker.log'
        self.env.update({'FAKE_DOCKER_LOG': str(self.docker_log), 'XDG_RUNTIME_DIR': str(self.scratch / 'run')})
        (self.scratch / 'run').mkdir(mode=0o700)

    def status(self, *args):
        result = subprocess.run([sys.executable, '-B', str(CLI), '--project', str(self.checkout), 'status', *args],
                                capture_output=True, text=True, env=self.env, stdin=subprocess.DEVNULL)
        return result

    def status_json(self):
        result = self.status('--json')
        self.assertEqual((result.returncode, result.stderr), (0, ''), result.stdout)
        self.assertEqual(result.stdout.count('\n'), 1)
        return json.loads(result.stdout)

    def test_an_unconfigured_checkout_needs_the_setup_plan(self):
        status = self.status_json()
        self.assertEqual(status['project'], str(self.checkout))
        self.assertEqual((status['ready'], status['missing']), ([], list(CHECKS)))
        self.assertEqual(status['checks']['workspace'],
                         {'ready': False, 'detail': f'no oasis-workspace.toml at or above {self.checkout}'})
        self.assertEqual(status['next'], f'oasis --project {self.checkout} setup --plan --json')
        self.assertFalse(self.docker_log.exists())
        # The human status still refuses an unconfigured checkout, as before.
        human = self.status()
        self.assertEqual((human.returncode, human.stdout), (2, ''))
        self.assertTrue(human.stderr.startswith('ERROR: Missing tooling configuration'))

    def test_the_json_status_runs_isolated_from_python_variables(self):
        # tools/status runs status_json.py as tools/doctor runs doctor.py (python3 -I -B): a module that
        # PYTHONPATH plants is not imported. tools/status is run directly, so the launcher's own Python is unaffected.
        planted = self.scratch / 'planted'
        planted.mkdir()
        (planted / 'json.py').write_text('raise ImportError("planted json")\n')
        env = {**self.env, 'PYTHONPATH': str(planted), 'OASIS_PROJECT_ROOT': str(self.checkout),
               'OASIS_ENTRYPOINT': str(CLI)}
        result = subprocess.run(['/bin/bash', str(ROOT / 'tools/status'), '--json'], capture_output=True, text=True,
                                env=env, stdin=subprocess.DEVNULL)
        self.assertEqual((result.returncode, result.stderr), (0, ''), result.stdout)
        self.assertEqual(json.loads(result.stdout)['project'], str(self.checkout))
        self.assertEqual(result.stdout, self.status('--json').stdout)

    def test_a_configured_checkout_reports_each_step_and_the_next_command(self):
        applied = self.setup_cmd('--apply', '--community', str(self.source), '--no-enterprise')
        self.assertEqual(applied.returncode, 0, applied.stderr)
        program = f'oasis --project {self.checkout}'
        status = self.status_json()
        self.assertEqual(status['ready'], ['workspace', 'environment', 'locks'])
        self.assertEqual(status['missing'], ['database_service', 'databases', 'server'])
        self.assertEqual(status['checks']['workspace'],
                         {'ready': True, 'detail': str(self.checkout / 'oasis-workspace.toml')})
        self.assertEqual(status['checks']['environment'], {'ready': True, 'detail': str(self.checkout / '.oasis/venv')})
        self.assertEqual(status['checks']['locks'], {'ready': True, 'detail': 'current'})
        self.assertEqual(status['checks']['database_service'], {'ready': False, 'detail': 'stopped'})
        self.assertEqual(status['checks']['databases'],
                         {'ready': False, 'detail': 'unknown while the database service is stopped'})
        self.assertEqual(status['checks']['server'], {'ready': False, 'detail': 'stopped'})
        # list-databases would start the service, which the policy's "reads and reports" does not say: the command
        # that starts it is named instead, start-database, which names no env file (an agent harness may refuse a
        # command that does).
        self.assertEqual(status['next'], f'{program} start-database')
        self.assertNotIn('.env', json.dumps(status['next']))
        # Read only: compose ps and nothing else (no `up`).
        calls = self.docker_log.read_text().splitlines()
        self.assertEqual(len(calls), 1)
        self.assertIn(' ps --format json db', calls[0])
        # A state compose ps cannot report: doctor, which checks docker.
        self.env['FAKE_PS_FAIL'] = '1'
        status = self.status_json()
        self.assertEqual(status['checks']['database_service'],
                         {'ready': False, 'detail': 'unknown (docker compose ps failed)'})
        self.assertEqual(status['next'], f'{program} doctor')
        del self.env['FAKE_PS_FAIL']
        self.env['FAKE_PS'] = '{"Service":"db","State":"running","Health":"healthy"}\n'
        status = self.status_json()
        self.assertEqual(status['checks']['database_service'], {'ready': True, 'detail': 'running'})
        self.assertEqual(status['checks']['databases'], {'ready': False, 'detail': []})
        # setup wrote [development] (its recommended answer without a terminal): init-dev-database works.
        self.assertEqual(status['next'], f'{program} init-dev-database shop_sale shop_dev_manual')
        self.env['FAKE_DATABASES'] = 'other_dev_x\nshop_dev_manual\nshop_test_x\n'
        status = self.status_json()
        self.assertEqual(status['checks']['databases'], {'ready': True, 'detail': ['shop_dev_manual', 'shop_test_x']})
        self.assertEqual(status['missing'], ['server'])
        self.assertEqual(status['next'], f'{program} start')
        # A stale lock comes before the database: bootstrap.
        requirements = self.checkout / '.oasis/config/requirements'
        (requirements / 'runtime.in').write_text((requirements / 'runtime.in').read_text() + 'requests\n')
        status = self.status_json()
        self.assertEqual(status['checks']['locks'], {'ready': False, 'detail': 'stale'})
        self.assertEqual(status['next'], f'{program} bootstrap --apply')

    def configured(self, *answers):
        applied = self.setup_cmd('--apply', '--community', str(self.source), '--no-enterprise', *answers)
        self.assertEqual(applied.returncode, 0, applied.stderr)
        return shlex.join(['oasis', '--project', str(self.checkout)])

    def test_each_state_of_the_database_service_and_its_next_command(self):
        program = self.configured()
        start = f'{program} start-database'
        # setup wrote [development] (v0.16.0 S6): the next database command is init-dev-database.
        init_dev = f'{program} init-dev-database shop_sale shop_dev_manual'
        for ps, detail, ready, next_command in (
                ('', 'stopped', False, start),
                ('{"Service":"db","State":"exited","Health":""}\n', 'stopped', False, start),
                ('{"Service":"db","State":"running","Health":"starting"}\n', 'starting', False, start),
                ('{"Service":"db","State":"running","Health":"unhealthy"}\n', 'unhealthy', False, f'{program} doctor'),
                ('not json\n', 'unknown (docker compose ps printed no JSON)', False, f'{program} doctor'),
                ('"text"', 'unknown (docker compose ps printed no JSON)', False, f'{program} doctor'),
                # The array form of older docker compose releases, and a service without a health check.
                ('[{"Service":"db","State":"running","Health":"healthy"}]', 'running', True, init_dev),
                ('{"Service":"db","State":"running"}\n', 'running', True, init_dev)):
            with self.subTest(ps=ps):
                self.env['FAKE_PS'] = ps
                status = self.status_json()
                self.assertEqual(status['checks']['database_service'], {'ready': ready, 'detail': detail})
                if not ready:
                    self.assertEqual(status['checks']['databases'],
                                     {'ready': False, 'detail': f'unknown while the database service is {detail}'})
                self.assertEqual(status['next'], next_command)
        self.assertNotIn(' up ', self.docker_log.read_text())

    def test_databases_that_cannot_be_read_need_doctor(self):
        program = self.configured()
        self.env.update(FAKE_PS=RUNNING, FAKE_QUERY_FAIL='1')
        status = self.status_json()
        self.assertEqual(status['checks']['databases'], {'ready': False, 'detail': 'unknown (the database query failed)'})
        self.assertEqual(status['next'], f'{program} doctor')
        # A worktree whose slug cannot be read (a legacy profile): the databases are unknown, as list-databases stops.
        del self.env['FAKE_QUERY_FAIL']
        worktree = self.checkout.parent / 'wt'
        self.git(self.checkout, 'worktree', 'add', '-q', '-b', 'wt', str(worktree))
        (worktree / '.odoo19-agent.toml').write_text('')
        status = self.status_json()
        self.assertFalse(status['checks']['databases']['ready'])
        self.assertTrue(status['checks']['databases']['detail'].startswith(
            f'unknown (Cannot read the checkout slug of {worktree}: '), status['checks']['databases'])
        self.assertEqual(status['next'], f'{program} doctor')

    def test_the_next_database_command_follows_the_workspace(self):
        program = self.configured('--answer', 'development=none')
        self.env['FAKE_PS'] = RUNNING
        self.assertEqual(self.status_json()['next'], f'{program} install-module shop_sale')
        workspace = self.checkout / 'oasis-workspace.toml'
        workspace.write_text(workspace.read_text() + "\n[development]\nadministrator_login = 'admin'\n")
        self.assertEqual(self.status_json()['next'], f'{program} init-dev-database shop_sale shop_dev_manual')
        (self.checkout / 'shop_sale/__manifest__.py').unlink()
        self.assertEqual(self.status_json()['next'], f'{program} create-database shop_dev_manual')

    def test_a_running_server_leaves_nothing_next(self):
        self.configured()
        self.env.update(FAKE_PS=RUNNING, FAKE_DATABASES='shop_dev_manual\n')
        # A live record of this checkout: the test process, within the start grace period.
        recorded = subprocess.run([sys.executable, '-I', '-B', str(ROOT / 'tools/runtime_state.py'), 'record',
                                   str(self.checkout), str(os.getpid()), '8069', str(self.source / 'odoo-bin')],
                                  env=self.env, capture_output=True, text=True)
        self.assertEqual((recorded.returncode, recorded.stderr), (0, ''))
        status = self.status_json()
        self.assertEqual((status['ready'], status['missing']), (list(CHECKS), []))
        self.assertEqual(status['checks']['server'], {'ready': True, 'detail': f'running pid {os.getpid()} port 8069'})
        self.assertIsNone(status['next'])

    def test_a_lock_changed_by_hand_needs_doctor(self):
        program = self.configured()
        lock = self.checkout / '.oasis/config/requirements/dev.txt'
        lock.write_text(lock.read_text() + '# edited\n')
        status = self.status_json()
        self.assertEqual(status['checks']['locks'], {'ready': False, 'detail': 'edited'})
        self.assertEqual(status['next'], f'{program} doctor')

    @unittest.skipIf(os.geteuid() == 0, 'root reads any file')
    def test_locks_that_cannot_be_read_are_unknown_in_one_json_object(self):
        program = self.configured()
        runtime_in = self.checkout / '.oasis/config/requirements/runtime.in'
        runtime_in.chmod(0)
        self.addCleanup(runtime_in.chmod, 0o644)
        status = self.status_json()
        self.assertEqual(status['checks']['locks'],
                         {'ready': False, 'detail': f"unknown ([Errno 13] Permission denied: '{runtime_in}')"})
        self.assertEqual(status['next'], f'{program} doctor')

    def test_a_configuration_that_cannot_be_read_is_unknown_in_one_json_object(self):
        self.configured()
        spec = importlib.util.spec_from_file_location('oasis_test_status_json', ROOT / 'tools/status_json.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with mock.patch.dict(os.environ, self.env, clear=True), \
                mock.patch.object(module.config, 'load', side_effect=PermissionError(13, 'Permission denied', 'x')):
            status = module.report(self.checkout)
        self.assertEqual(status['checks']['workspace'], {'ready': False, 'detail': "unknown ([Errno 13] Permission denied: 'x')"})
        self.assertEqual(status['next'], shlex.join(['oasis', '--project', str(self.checkout), 'doctor']))
        json.dumps(status)

    def test_the_project_path_is_shell_quoted_in_next(self):
        checkout = self.checkout.parent / "my shop's"
        self.checkout.rename(checkout)
        self.checkout = checkout
        status = self.status_json()
        self.assertEqual(status['next'], shlex.join(['oasis', '--project', str(checkout), 'setup', '--plan', '--json']))
        self.assertEqual(shlex.split(status['next'])[2], str(checkout))

    def test_extra_arguments_after_json_are_a_usage_error(self):
        self.configured()
        for args in (('--json', 'extra'), ('--json', '--json')):
            with self.subTest(args=args):
                result = self.status(*args)
                self.assertEqual((result.returncode, result.stdout, result.stderr),
                                 (2, '', f'Usage: {CLI} status [--json]\n'))
        self.assertFalse(self.docker_log.exists())

    def test_an_invalid_configuration_needs_doctor(self):
        (self.checkout / 'oasis-workspace.toml').write_text('workspace_version = 1\n')
        status = self.status_json()
        self.assertFalse(status['checks']['workspace']['ready'])
        self.assertEqual(status['next'], f'oasis --project {self.checkout} doctor')
        self.assertFalse(self.docker_log.exists())


if __name__ == '__main__':
    unittest.main()
