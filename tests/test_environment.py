"""Public staged diagnostics/preview checks; all commands and inputs are fixture-local."""
from pathlib import Path
import subprocess
import sys
import unittest
import test_lifecycle as lifecycle


class EnvironmentTests(unittest.TestCase):
    setUp = lifecycle.LifecycleTests.setUp
    invoke = lifecycle.LifecycleTests.invoke
    unchanged = lifecycle.LifecycleTests.unchanged

    def prepare(self):
        requirements = self.root / 'dev/requirements'
        requirements.mkdir(parents=True)
        for name in ('runtime.in', 'runtime.txt', 'dev.in', 'dev.txt', 'lock.sha256'):
            (requirements / name).write_text('# fixture\n')
        (self.root / 'dev/runtime').mkdir()
        (self.bindir / 'sha256sum').write_text('#!/bin/sh\nexit "${FAKE_LOCK_STATUS:-0}"\n')
        (self.bindir / 'sha256sum').chmod(0o755)
        (self.bindir / 'uv').write_text('#!/bin/sh\n'
                                          'if [ "$1" = "--version" ]; then echo "uv 0.1"; exit 0; fi\n'
                                          'printf "uv %s\\n" "$*" >> "$FAKE_LOG"\n')
        (self.bindir / 'uv').chmod(0o755)
        self.env['FAKE_HOST_PYTHON'] = sys.executable
        self.python.write_text(self.python.read_text().replace(
            'if [ "$1" = "-c" ]; then echo 3.12; exit 0; fi',
            'if [ "$1" = "-c" ]; then\n'
            '  case "$2" in *"sys.prefix"*) echo "' + str(self.python.parent.parent) + '" ;; *) echo 3.12 ;; esac\n'
            '  exit 0\nfi').replace(
                'if [ "$2" = "--version" ]; then',
                'case "$1" in */audit_dependencies.py) exec "$FAKE_HOST_PYTHON" -B "$@" ;; '
                '*/check_environment.py) echo "locked_packages=0"; echo "missing_packages=0"; '
                'echo "version_mismatches=0"; exit 0 ;; esac\n'
                'if [ "$2" = "--version" ]; then'))
        return requirements

    def test_invalid_option_usage_names_project_wrapper(self):
        self.prepare()
        for command, tail in (
                ('bootstrap', ' [--preview|--apply]'),
                ('check-environment', ' [--quick|--full]')):
            result = self.invoke(command, '--invalid')
            self.assertEqual((result.returncode, result.stdout, result.stderr),
                             (2, '', 'Usage: ' + str(self.root / 'dev/scripts' / command) + tail + '\n'))
            self.unchanged()
        result = self.invoke('audit-dependencies', 'coffee', 'extra')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (2, '', 'Usage: ' + str(self.root / 'dev/scripts/audit-dependencies') +
                          ' [module]\n'))
        self.unchanged()

    def expected_apply_output(self, environment):
        files = ('runtime.in', 'runtime.txt', 'dev.in', 'dev.txt', 'lock.sha256')
        return (f'mode=apply\nproject=a project\nenvironment={environment}\n'
                'lockfile=dev/requirements/dev.txt\nmutation=isolated_project_virtualenv\n'
                + ''.join(f'PASS file:dev/requirements/{name}\n' for name in files)
                + f'PASS python_version=3.12\nPASS virtualenv={environment}\n'
                'PASS uv=0.1\nPASS odoo_version=19.0\nPASS dependency_locks=current\n'
                'PASS compose_config=valid\nPASS package_compatibility=valid\n'
                'locked_packages=0\nmissing_packages=0\nversion_mismatches=0\n'
                'PASS locked_environment=exact\nscope=all\ndeclared_distributions=0\n'
                'external_imports=0\nundeclared_dependencies=0\nPASS dependency_audit=clean\n'
                'PASS postgres_service=running\nPASS postgres_connection=ready\n'
                'environment_mode=full\nenvironment_failures=0\n')

    def test_fresh_apply_syncs_before_odoo_runtime_and_finishes_full_check(self):
        self.prepare()
        environment = self.python.parent.parent
        template = self.root / 'fake-python-template'
        template.write_text('''#!/bin/sh
if [ "$1" = "-c" ]; then
  case "$2" in
    *"sys.prefix"*) echo "$FAKE_ENV"; echo 'python prefix' >> "$FAKE_LOG" ;;
    *) echo 3.12; echo 'python version' >> "$FAKE_LOG" ;;
  esac
  exit 0
fi
if [ "$2" = "--version" ]; then
  echo 'python odoo-version' >> "$FAKE_LOG"
  if [ ! -f "$FAKE_SYNCED" ]; then echo 'fake dependencies missing' >&2; exit 29; fi
  echo 'Odoo Server 19.0'
  exit 0
fi
case "$1" in
  */audit_dependencies.py) exec "$FAKE_HOST_PYTHON" -B "$@" ;;
  */check_environment.py) printf 'locked_packages=0\\nmissing_packages=0\\nversion_mismatches=0\\n'; exit 0 ;;
esac
exit 97
''')
        self.python.unlink()
        self.python.parent.rmdir()
        environment.rmdir()
        self.env.update(FAKE_ENV=str(environment), FAKE_PYTHON=str(self.python),
                        FAKE_TEMPLATE=str(template), FAKE_SYNCED=str(self.root / 'synced'),
                        FAKE_MUTATIONS=str(self.root / 'mutations.log'))
        uv = self.bindir / 'uv'
        uv.write_text('''#!/bin/sh
if [ "$1" = "--version" ]; then echo 'uv 0.1'; exit 0; fi
printf 'uv %s\\n' "$*" >> "$FAKE_LOG"
case "$1 $2" in
  'venv --python')
    echo venv >> "$FAKE_MUTATIONS"
    mkdir -p "${FAKE_PYTHON%/*}"
    cp "$FAKE_TEMPLATE" "$FAKE_PYTHON"
    chmod +x "$FAKE_PYTHON" ;;
  'pip sync')
    echo sync >> "$FAKE_MUTATIONS"
    touch "$FAKE_SYNCED" ;;
esac
''')
        docker = self.bindir / 'docker'
        docker.write_text(docker.read_text().replace('exit 0\n',
            'case "$*" in *"ps --status running --services"*) echo db ;; '
            '*"exec psql"*"SELECT 1"*) echo 1 ;; esac\nexit 0\n'))
        result = self.invoke('bootstrap', '--apply')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (0, self.expected_apply_output(environment), ''))
        self.assertEqual((self.root / 'mutations.log').read_text(), 'venv\nsync\n')
        events = self.commands.read_text().splitlines()
        self.assertEqual(events[:6], [
            f'uv venv --python 3.12 {environment}', 'python version',
            f'uv pip freeze --python {self.python}',
            f'uv pip sync --python {self.python} {self.root / "dev/requirements/dev.txt"}',
            'python version', 'python odoo-version',
        ])
        # Bootstrap, full check, explicit version report, and dependency audit.
        self.assertEqual(events.count('python odoo-version'), 4)
        self.assertTrue((self.root / 'dev/runtime/bootstrap-before.txt').is_file())

    def test_existing_incomplete_venv_can_preview_and_explicitly_repair(self):
        self.prepare()
        synced = self.root / 'synced'
        self.env['FAKE_SYNCED'] = str(synced)
        old_python = self.python.read_text()
        self.python.write_text(old_python.replace(
            'if [ "$2" = "--version" ]; then echo "Odoo Server 19.0"; exit 0; fi',
            'if [ "$2" = "--version" ]; then '
            '[ -f "$FAKE_SYNCED" ] || exit 29; echo "Odoo Server 19.0"; exit 0; fi'))
        uv = self.bindir / 'uv'
        uv.write_text(uv.read_text().replace(
            'printf "uv %s\\n" "$*" >> "$FAKE_LOG"',
            'printf "uv %s\\n" "$*" >> "$FAKE_LOG"\n'
            'if [ "$1 $2" = "pip sync" ] && [ "$3" != "--dry-run" ]; then '
            'echo sync >> "$FAKE_MUTATIONS"; touch "$FAKE_SYNCED"; fi'))
        self.env['FAKE_MUTATIONS'] = str(self.root / 'mutations.log')
        docker = self.bindir / 'docker'
        docker.write_text(docker.read_text().replace('exit 0\n',
            'case "$*" in *"ps --status running --services"*) echo db ;; '
            '*"exec psql"*"SELECT 1"*) echo 1 ;; esac\nexit 0\n'))
        preview = self.invoke('bootstrap')
        expected_preview = (f'mode=preview\nproject=a project\nenvironment={self.python.parent.parent}\n'
                            'lockfile=dev/requirements/dev.txt\nmutation=none\n'
                            'environment_state=ready\n')
        self.assertEqual((preview.returncode, preview.stdout, preview.stderr), (0, expected_preview, ''))
        self.assertFalse(synced.exists())
        self.assertFalse((self.root / 'mutations.log').exists())
        self.commands.write_text('')
        result = self.invoke('bootstrap', '--apply')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (0, self.expected_apply_output(self.python.parent.parent), ''))
        self.assertEqual((self.root / 'mutations.log').read_text(), 'sync\n')
        self.assertTrue(synced.is_file())
        self.assertIn('uv pip sync --python ' + str(self.python), self.commands.read_text())
        self.assertNotIn('uv venv ', self.commands.read_text())

    def test_apply_requires_option_and_uses_only_fixture_uv(self):
        self.prepare()
        docker = self.bindir / 'docker'
        docker.write_text(docker.read_text().replace('exit 0\n',
            'case "$*" in *"ps --status running --services"*) echo db ;; '
            '*"exec psql"*"SELECT 1"*) echo 1 ;; esac\nexit 0\n'))
        result = self.invoke('bootstrap', '--apply')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, '')
        self.assertIn('mode=apply\n', result.stdout)
        self.assertIn('mutation=isolated_project_virtualenv\n', result.stdout)
        self.assertIn('environment_mode=full\nenvironment_failures=0\n', result.stdout)
        log = self.commands.read_text()
        self.assertIn('uv pip sync --python ' + str(self.python), log)
        self.assertNotIn('uv venv ', log)
        self.assertNotIn('uv pip sync --dry-run', log)
        self.assertTrue((self.root / 'dev/runtime/bootstrap-before.txt').is_file())

    def test_preview_is_default_and_never_syncs(self):
        requirements = self.prepare()
        result = self.invoke('bootstrap')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (0, 'mode=preview\nproject=a project\nenvironment=' + str(self.python.parent.parent) +
                          '\nlockfile=dev/requirements/dev.txt\nmutation=none\nenvironment_state=ready\n', ''))
        self.assertEqual(self.commands.read_text(),
                         'uv pip sync --dry-run --python ' + str(self.python) + ' ' +
                         str(requirements / 'dev.txt') + '\n')

    def test_existing_wrong_python_blocks_apply_before_uv(self):
        self.prepare()
        self.python.write_text(self.python.read_text().replace('echo 3.12', 'echo 3.11'))
        result = self.invoke('bootstrap', '--apply')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (2, '', 'Python 3.12 is required; found 3.11.\n'))
        self.unchanged()

    def test_unverified_source_blocks_apply_before_uv(self):
        self.prepare()
        (self.source / 'odoo/release.py').write_text('version_info = (18, 0)\n')
        result = self.invoke('bootstrap', '--apply')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (2, '', 'Odoo source must declare release 19.0.\n'))
        self.unchanged()

    def test_missing_lock_and_stale_fingerprint_block_preview_and_apply(self):
        requirements = self.prepare()
        (requirements / 'dev.txt').unlink()
        for mode in ('--preview', '--apply'):
            result = self.invoke('bootstrap', mode)
            self.assertEqual((result.returncode, result.stdout, result.stderr),
                             (2, '', 'Missing required local path: ' + str(requirements / 'dev.txt') + '\n'))
            self.unchanged()
        (requirements / 'dev.txt').touch()
        self.env['FAKE_LOCK_STATUS'] = '1'
        result = self.invoke('bootstrap', '--apply')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (2, '', 'Refusing bootstrap because dependency inputs or locks do not match lock.sha256.\n'
                          'Regenerate the locks and fingerprint before preview or apply.\n'))
        self.unchanged()

    def test_missing_fingerprint_is_not_bypassed_by_a_fake_successful_hasher(self):
        requirements = self.prepare()
        (requirements / 'lock.sha256').unlink()
        result = self.invoke('bootstrap', '--apply')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (2, '', 'Refusing bootstrap because dependency inputs or locks do not match lock.sha256.\n'
                          'Regenerate the locks and fingerprint before preview or apply.\n'))
        self.unchanged()
        result = self.invoke('check-environment')
        self.assertEqual(result.returncode, 1)
        self.assertIn('FAIL missing_file:dev/requirements/lock.sha256\n', result.stderr)
        self.assertIn('FAIL dependency_locks=stale_or_modified\n', result.stderr)

    def test_check_quick_reports_fixture_and_skips_full_checks(self):
        self.prepare()
        result = self.invoke('check-environment')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, '')
        self.assertIn('PASS python_version=3.12\n', result.stdout)
        self.assertIn('PASS dependency_locks=current\n', result.stdout)
        self.assertTrue(result.stdout.endswith(
            'SKIP locked_environment=use_--full\nSKIP dependency_audit=use_--full\n'
            'SKIP postgres_connection=use_--full\nenvironment_mode=quick\nenvironment_failures=0\n'))
        self.assertNotIn('uv pip check', self.commands.read_text() if self.commands.exists() else '')

    def test_audit_explicit_roots_and_reject_unknown_module(self):
        requirements = self.prepare()
        (requirements / 'dev.in').write_text('# no external imports\n')
        (self.root / 'coffee/__init__.py').write_text('import datetime\n')
        result = self.invoke('audit-dependencies', 'coffee')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (0, 'scope=coffee\ndeclared_distributions=0\nexternal_imports=0\n'
                          'undeclared_dependencies=0\n', ''))
        result = self.invoke('audit-dependencies', 'bad-name')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (2, '', 'ERROR: Module not found in this repository: bad-name\n'))

    def test_audit_python_helper_path_runs_as_python_with_project_args(self):
        self.prepare()
        (self.root / 'dev/requirements/dev.in').write_text('# no imports\n')
        helper = self.root / 'dev/scripts/audit_dependencies.py'
        helper.parent.mkdir(parents=True, exist_ok=True)
        helper.write_bytes((lifecycle.STAGE / 'project-wrappers/audit_dependencies.py').read_bytes())
        result = subprocess.run([sys.executable, '-B', str(helper), 'coffee'],
                                text=True, capture_output=True, env=self.env)
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (0, 'scope=coffee\ndeclared_distributions=0\nexternal_imports=0\n'
                          'undeclared_dependencies=0\n', ''))

    def test_audit_python_helper_help_omits_internal_config_arguments(self):
        self.prepare()
        helper = self.root / 'dev/scripts/audit_dependencies.py'
        helper.parent.mkdir(parents=True, exist_ok=True)
        helper.write_bytes((lifecycle.STAGE / 'project-wrappers/audit_dependencies.py').read_bytes())
        result = subprocess.run([sys.executable, '-B', str(helper), '--help'],
                                text=True, capture_output=True, env=self.env)
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertIn('usage: audit_dependencies.py [-h] [module]\n', result.stdout)
        self.assertNotIn('--project-root', result.stdout)

    def test_lock_helper_public_cli_and_missing_lock(self):
        self.prepare()
        helper = self.root / 'dev/scripts/check_environment.py'
        helper.parent.mkdir(parents=True, exist_ok=True)
        helper.write_bytes((lifecycle.STAGE / 'project-wrappers/check_environment.py').read_bytes())
        result = subprocess.run([sys.executable, '-B', str(helper),
                                 str(self.root / 'dev/requirements/absent.txt')],
                                text=True, capture_output=True, env=self.env)
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (2, '', 'ERROR: Lockfile not found: ' +
                          str(self.root / 'dev/requirements/absent.txt') + '\n'))


if __name__ == '__main__':
    unittest.main()
