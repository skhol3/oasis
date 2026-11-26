"""`oasis status --json`: what is ready, what is missing and the next oasis command (v0.16.0 S3).

The checkout is tests/test_setup.py's fixture, configured with `oasis setup --apply` and its fake uv; docker is
a fake that answers `compose ps` with FAKE_PS and the database query with FAKE_DATABASES, and records every call,
so nothing reaches a real service.
"""
import oasis_test_env  # noqa: F401  first: XDG_CONFIG_HOME is scratch (tests/oasis_test_env.py)
import json
import subprocess
import sys
import unittest

import test_setup
from test_setup import CLI

DOCKER = '''#!/bin/sh
printf 'docker %s\\n' "$*" >> "$FAKE_DOCKER_LOG"
case "$*" in
  *" ps --format json "*) printf '%s' "${FAKE_PS:-}" ;;
  *"SELECT datname FROM pg_database"*) printf '%s' "${FAKE_DATABASES:-}" ;;
  *) exit 9 ;;
esac
'''
CHECKS = ('workspace', 'environment', 'locks', 'database_service', 'databases', 'server')


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
        self.assertEqual(status['next'], f'{program} list-databases')
        # Read only: compose ps and nothing else (no `up`).
        calls = self.docker_log.read_text().splitlines()
        self.assertEqual(len(calls), 1)
        self.assertIn(' ps --format json db', calls[0])
        self.env['FAKE_PS'] = '{"Service":"db","State":"running","Health":"healthy"}\n'
        status = self.status_json()
        self.assertEqual(status['checks']['database_service'], {'ready': True, 'detail': 'running'})
        self.assertEqual(status['checks']['databases'], {'ready': False, 'detail': []})
        self.assertEqual(status['next'], f'{program} install-module shop_sale')
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

    def test_an_invalid_configuration_needs_doctor(self):
        (self.checkout / 'oasis-workspace.toml').write_text('workspace_version = 1\n')
        status = self.status_json()
        self.assertFalse(status['checks']['workspace']['ready'])
        self.assertEqual(status['next'], f'oasis --project {self.checkout} doctor')
        self.assertFalse(self.docker_log.exists())


if __name__ == '__main__':
    unittest.main()
