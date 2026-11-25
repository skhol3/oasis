"""Public staged diagnostics/preview checks; all commands and inputs are fixture-local."""
import oasis_test_env  # noqa: F401  first: XDG_CONFIG_HOME is scratch (tests/oasis_test_env.py)
from pathlib import Path
import hashlib
import shutil
import subprocess
import sys
import unittest
import test_lifecycle as lifecycle

FILES = ('runtime.in', 'runtime.txt', 'dev.in', 'dev.txt')
COMPILED = 'locks_compiled=runtime.txt,dev.txt,lock.sha256\n'
# Put in front of a fake uv: `uv pip compile ... <input>.in -o <output>` records its argv and
# working directory, writes the output there (and echoes it, like uv), or fails for the input
# named by FAKE_COMPILE_FAIL.
COMPILING_UV = '''if [ "$1 $2" = "pip compile" ]; then
  printf 'uv %s (in %s)\\n' "$*" "$PWD" >> "$FAKE_LOG"
  prev= input= output=
  for arg; do
    if [ "$prev" = -o ]; then output=$arg; fi
    case "$arg" in *.in) input=$arg ;; esac
    prev=$arg
  done
  if [ -n "${FAKE_MUTATIONS:-}" ]; then echo "compile $input" >> "$FAKE_MUTATIONS"; fi
  if [ "$input" = "${FAKE_COMPILE_FAIL:-}" ]; then
    echo "error: No solution found when resolving $input" >&2
    exit 1
  fi
  printf '# fake lock of %s\\n' "$input" > "$output"
  printf '# fake lock of %s\\n' "$input"
  exit 0
fi
'''


def fingerprint(requirements):
    """lock.sha256 as `sha256sum runtime.in runtime.txt dev.in dev.txt` writes it there."""
    return ''.join(f'{hashlib.sha256((requirements / name).read_bytes()).hexdigest()}  {name}\n'
                   for name in FILES)


def fingerprint_with_overrides(requirements):
    """lock.sha256 with overrides.txt last, as tools/locks.py writes it when that file exists (S7)."""
    return fingerprint(requirements) + (
        f'{hashlib.sha256((requirements / "overrides.txt").read_bytes()).hexdigest()}  overrides.txt\n')


def contents(requirements):
    """The bytes of every file of the requirements directory."""
    return {path.name: path.read_bytes() for path in sorted(requirements.iterdir())}


class EnvironmentTests(unittest.TestCase):
    setUp = lifecycle.LifecycleTests.setUp
    invoke = lifecycle.LifecycleTests.invoke
    unchanged = lifecycle.LifecycleTests.unchanged

    def prepare(self, runtime=True):
        requirements = self.root / 'dev/requirements'
        requirements.mkdir(parents=True)
        for name in ('runtime.in', 'runtime.txt', 'dev.in', 'dev.txt', 'lock.sha256'):
            (requirements / name).write_text('# fixture\n')
        if runtime:
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

    def lockable(self, fingerprint_locks=True):
        """The prepared requirements with inputs of their own, the real sha256sum and a fake uv
        that compiles (COMPILING_UV); with fingerprint_locks, a lock.sha256 that matches them.
        Call it after missing_environment, which replaces the fake uv."""
        requirements = self.root / 'dev/requirements'
        (self.bindir / 'sha256sum').unlink()
        (requirements / 'runtime.in').write_text('# the Odoo requirements\n')
        (requirements / 'dev.in').write_text('# the development tools\n')
        uv = self.bindir / 'uv'
        uv.write_text(uv.read_text().replace('#!/bin/sh\n', '#!/bin/sh\n' + COMPILING_UV, 1))
        if fingerprint_locks:
            (requirements / 'lock.sha256').write_text(fingerprint(requirements))
        return requirements

    def running_database(self):
        docker = self.bindir / 'docker'
        docker.write_text(docker.read_text().replace('exit 0\n',
            'case "$*" in *"ps --status running --services"*) echo db ;; '
            '*"exec psql"*"SELECT 1"*) echo 1 ;; esac\nexit 0\n'))

    def compile_events(self, requirements, python='3.12'):
        return [f'uv pip compile --python-version {python} runtime.in -o runtime.txt (in {requirements})',
                f'uv pip compile --python-version {python} dev.in -o dev.txt (in {requirements})']

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

    def as_workspace(self, python=None, logs=False):
        """The fixture project read from an oasis-workspace.toml two levels above it, without its
        profile and without dev/runtime: [tooling].environment, or with python a named `default`
        environment that declares it; with logs, [tooling].logs = 'logs'. Returns the workspace
        directory."""
        base = self.root.parent.parent
        (self.root / 'oasis-workspace.toml').unlink()
        checkout = 'projects/a project/'
        tooling = ["community = 'source/odoo'",
                   f"config = '{checkout}dev/odoo.conf'", f"env_file = '{checkout}dev/.env'",
                   f"compose = '{checkout}dev/compose.yml'", f"requirements = '{checkout}dev/requirements'",
                   "addons_paths = ['.']", "db_service = 'db'", "dev_prefix = 'cc_dev_'",
                   "test_prefix = 'cc_test_'"]
        if logs:
            tooling.append("logs = 'logs'")
        if python is None:
            tooling.append("environment = 'environments/example'")
        tables = ([] if python is None else
                  ['', '[environments.default]', "path = 'environments/example'", f"python = '{python}'"])
        workspace = base / 'oasis-workspace.toml'
        workspace.write_text('\n'.join(["workspace_version = 1", "odoo_version = '19.0'", '', '[tooling]',
                                        *tooling, *tables]) + '\n')
        # The trust rule: neither the file nor its directory writable by group or others.
        workspace.chmod(0o644)
        base.chmod(0o755)
        return base

    def missing_environment(self, python='3.12'):
        """No environment yet: the fake uv creates one whose Python reports python and whose Odoo
        answers only once the lock is synced; docker reports a running, reachable database."""
        environment = self.python.parent.parent
        template = self.root / 'fake-python-template'
        template.write_text('''#!/bin/sh
if [ "$1" = "-c" ]; then
  case "$2" in
    *"sys.prefix"*) echo "$FAKE_ENV"; echo 'python prefix' >> "$FAKE_LOG" ;;
    *) echo PYTHON_VERSION; echo 'python version' >> "$FAKE_LOG" ;;
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
'''.replace('PYTHON_VERSION', python))
        self.python.unlink()
        self.python.parent.rmdir()
        (environment / 'pyvenv.cfg').unlink()
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
    echo 'home = /usr/bin' > "$FAKE_ENV/pyvenv.cfg"
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
        return environment

    def expected_apply_output(self, environment, python='3.12', locks=None):
        files = ('runtime.in', 'runtime.txt', 'dev.in', 'dev.txt', 'lock.sha256')
        return (f'mode=apply\nproject=a project\nenvironment={environment}\n'
                'lockfile=dev/requirements/dev.txt\nmutation=isolated_project_virtualenv\n'
                + (f'locks={locks}\n{COMPILED}' if locks else '')
                + ''.join(f'PASS file:dev/requirements/{name}\n' for name in files)
                + f'PASS python_version={python}\nPASS virtualenv={environment}\n'
                'PASS uv=0.1\nPASS odoo_version=19.0\nPASS dependency_locks=current\n'
                'PASS compose_config=valid\nPASS package_compatibility=valid\n'
                'locked_packages=0\nmissing_packages=0\nversion_mismatches=0\n'
                'PASS locked_environment=exact\nscope=all\ndeclared_distributions=0\n'
                'external_imports=0\nundeclared_dependencies=0\nPASS dependency_audit=clean\n'
                'PASS postgres_service=running\nPASS postgres_connection=ready\n'
                'environment_mode=full\nenvironment_failures=0\n')

    def test_fresh_apply_syncs_before_odoo_runtime_and_finishes_full_check(self):
        self.prepare()
        environment = self.missing_environment()
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
        # The snapshot goes to the checkout's log directory, no longer to dev/runtime.
        self.assertTrue((self.root / 'dev/logs/odoo19/bootstrap-before.txt').is_file())
        self.assertFalse((self.root / 'dev/runtime/bootstrap-before.txt').exists())

    def test_profile_preview_of_a_missing_environment_plans_python_3_12(self):
        self.prepare()
        environment = self.missing_environment()
        result = self.invoke('bootstrap')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (0, f'mode=preview\nproject=a project\nenvironment={environment}\n'
                             'lockfile=dev/requirements/dev.txt\nmutation=none\nenvironment_state=missing\n'
                             'planned_action=create_python_3.12_and_sync_lock\n', ''))
        self.unchanged()

    def test_workspace_preview_plans_the_named_environment_python(self):
        self.prepare(runtime=False)
        self.as_workspace(python='3.13')
        environment = self.missing_environment('3.13')
        result = self.invoke('bootstrap', '--preview')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (0, f'mode=preview\nproject=a project\nenvironment={environment}\n'
                             'lockfile=dev/requirements/dev.txt\nmutation=none\nenvironment_state=missing\n'
                             'planned_action=create_python_3.13_and_sync_lock\n', ''))
        self.unchanged()
        self.assertFalse(environment.exists())

    def test_workspace_apply_creates_the_named_environment_python_and_snapshots_to_its_logs(self):
        self.prepare(runtime=False)
        workspace = self.as_workspace(python='3.13', logs=True)
        environment = self.missing_environment('3.13')
        result = self.invoke('bootstrap', '--apply')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (0, self.expected_apply_output(environment, '3.13'), ''))
        self.assertEqual((self.root / 'mutations.log').read_text(), 'venv\nsync\n')
        events = self.commands.read_text().splitlines()
        self.assertEqual(events[:4], [
            f'uv venv --python 3.13 {environment}', 'python version',
            f'uv pip freeze --python {self.python}',
            f'uv pip sync --python {self.python} {self.root / "dev/requirements/dev.txt"}',
        ])
        # [tooling].logs: <logs>/main for a checkout outside git; nothing under dev/.
        self.assertTrue((workspace / 'logs/main/bootstrap-before.txt').is_file())
        self.assertFalse((self.root / 'dev/runtime').exists())
        self.assertFalse((self.root / 'dev/logs').exists())

    def test_workspace_single_environment_apply_uses_python_3_12_and_the_checkout_logs(self):
        self.prepare(runtime=False)
        self.as_workspace()
        environment = self.missing_environment()
        result = self.invoke('bootstrap', '--apply')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (0, self.expected_apply_output(environment), ''))
        self.assertEqual(self.commands.read_text().splitlines()[0], f'uv venv --python 3.12 {environment}')
        # Without [tooling].logs: the checkout's dev/logs/odoo19.
        self.assertTrue((self.root / 'dev/logs/odoo19/bootstrap-before.txt').is_file())
        self.assertFalse((self.root / 'dev/runtime').exists())

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
        self.assertTrue((self.root / 'dev/logs/odoo19/bootstrap-before.txt').is_file())

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

    def preview_output(self, environment, locks, state='ready', python='3.12'):
        action = 'sync_lock' if state == 'ready' else f'create_python_{python}_and_sync_lock'
        return (f'mode=preview\nproject=a project\nenvironment={environment}\n'
                f'lockfile=dev/requirements/dev.txt\nmutation=none\nlocks={locks}\n'
                f'environment_state={state}\nplanned_action=compile_locks_then_{action}\n')

    def test_missing_lock_and_stale_fingerprint_plan_the_compile_step(self):
        requirements = self.prepare()
        (requirements / 'dev.txt').unlink()
        result = self.invoke('bootstrap', '--preview')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (0, self.preview_output(self.python.parent.parent, 'missing'), ''))
        self.unchanged()
        self.assertFalse((requirements / 'dev.txt').exists())
        (requirements / 'dev.txt').touch()
        # lock.sha256 reports a mismatch and cannot even tell what runtime.in and dev.in were.
        self.env['FAKE_LOCK_STATUS'] = '1'
        result = self.invoke('bootstrap')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (0, self.preview_output(self.python.parent.parent, 'stale'), ''))
        self.unchanged()

    def test_missing_fingerprint_is_not_bypassed_by_a_fake_successful_hasher(self):
        requirements = self.prepare()
        (requirements / 'lock.sha256').unlink()
        result = self.invoke('bootstrap', '--preview')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (0, self.preview_output(self.python.parent.parent, 'missing'), ''))
        self.unchanged()
        result = self.invoke('check-environment')
        self.assertEqual(result.returncode, 1)
        self.assertIn('FAIL missing_file:dev/requirements/lock.sha256\n', result.stderr)
        self.assertIn('FAIL dependency_locks=stale_or_modified\n', result.stderr)

    def test_apply_compiles_missing_locks_with_the_declared_python_before_the_environment(self):
        self.prepare(runtime=False)
        self.as_workspace(python='3.13')
        environment = self.missing_environment('3.13')
        requirements = self.lockable(fingerprint_locks=False)
        for name in ('runtime.txt', 'dev.txt', 'lock.sha256'):
            (requirements / name).unlink()
        inputs = {name: (requirements / name).read_bytes() for name in ('runtime.in', 'dev.in')}
        result = self.invoke('bootstrap', '--apply')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (0, self.expected_apply_output(environment, '3.13', locks='missing'), ''))
        self.assertEqual((self.root / 'mutations.log').read_text(),
                         'compile runtime.in\ncompile dev.in\nvenv\nsync\n')
        events = self.commands.read_text().splitlines()
        self.assertEqual(events[:5], [
            *self.compile_events(requirements, '3.13'),
            f'uv venv --python 3.13 {environment}', 'python version',
            f'uv pip freeze --python {self.python}'])
        self.assertEqual((requirements / 'runtime.txt').read_text(), '# fake lock of runtime.in\n')
        self.assertEqual((requirements / 'dev.txt').read_text(), '# fake lock of dev.in\n')
        self.assertEqual((requirements / 'lock.sha256').read_text(), fingerprint(requirements))
        self.assertEqual({name: (requirements / name).read_bytes() for name in inputs}, inputs)

    def test_apply_recompiles_stale_locks_then_syncs_the_existing_environment(self):
        self.prepare()
        requirements = self.lockable()
        self.running_database()
        (requirements / 'dev.in').write_text('# the development tools, one more\n')
        result = self.invoke('bootstrap', '--apply')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (0, self.expected_apply_output(self.python.parent.parent, locks='stale'), ''))
        events = self.commands.read_text().splitlines()
        self.assertEqual(events[:4], [
            *self.compile_events(requirements),
            f'uv pip freeze --python {self.python}',
            f'uv pip sync --python {self.python} {requirements / "dev.txt"}'])
        self.assertNotIn('uv venv ', self.commands.read_text())
        self.assertEqual((requirements / 'dev.in').read_text(), '# the development tools, one more\n')
        self.assertEqual((requirements / 'lock.sha256').read_text(), fingerprint(requirements))

    def test_preview_of_missing_locks_and_environment_names_both_steps_and_changes_nothing(self):
        self.prepare()
        environment = self.missing_environment()
        requirements = self.lockable(fingerprint_locks=False)
        for name in ('runtime.txt', 'dev.txt', 'lock.sha256'):
            (requirements / name).unlink()
        before = contents(requirements)
        result = self.invoke('bootstrap', '--preview')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (0, self.preview_output(environment, 'missing', 'missing'), ''))
        self.unchanged()
        self.assertEqual(contents(requirements), before)
        self.assertFalse(environment.exists())

    def test_preview_of_stale_locks_names_the_compile_step_and_changes_nothing(self):
        self.prepare()
        requirements = self.lockable()
        (requirements / 'runtime.in').write_text('# the Odoo requirements, changed\n')
        before = contents(requirements)
        result = self.invoke('bootstrap')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (0, self.preview_output(self.python.parent.parent, 'stale'), ''))
        # No uv at all: not even the dry-run sync of a lock that is about to change.
        self.unchanged()
        self.assertEqual(contents(requirements), before)

    def test_current_locks_are_left_byte_identical_by_preview_and_apply(self):
        self.prepare()
        requirements = self.lockable()
        self.running_database()
        before = contents(requirements)
        preview = self.invoke('bootstrap', '--preview')
        self.assertEqual((preview.returncode, preview.stdout, preview.stderr),
                         (0, f'mode=preview\nproject=a project\nenvironment={self.python.parent.parent}\n'
                             'lockfile=dev/requirements/dev.txt\nmutation=none\nenvironment_state=ready\n', ''))
        self.assertEqual(self.commands.read_text(), f'uv pip sync --dry-run --python {self.python} '
                                                    f'{requirements / "dev.txt"}\n')
        self.commands.unlink()
        result = self.invoke('bootstrap', '--apply')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (0, self.expected_apply_output(self.python.parent.parent), ''))
        self.assertNotIn('pip compile', self.commands.read_text())
        self.assertEqual(contents(requirements), before)

    def test_a_failed_compile_stops_before_the_fingerprint_and_the_environment(self):
        self.prepare()
        environment = self.missing_environment()
        requirements = self.lockable()
        (requirements / 'dev.in').write_text('# the development tools, unsolvable\n')
        lock = (requirements / 'lock.sha256').read_bytes()
        self.env['FAKE_COMPILE_FAIL'] = 'dev.in'
        result = self.invoke('bootstrap', '--apply')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (
            2, f'mode=apply\nproject=a project\nenvironment={environment}\n'
               'lockfile=dev/requirements/dev.txt\nmutation=isolated_project_virtualenv\nlocks=stale\n',
            'error: No solution found when resolving dev.in\n'
            'uv pip compile of dev.in failed (exit 1); lock.sha256 was left as it was.\n'
            f'Fix {requirements / "dev.in"} or its access to the package index, '
            'then run oasis bootstrap --apply again.\n'))
        self.assertEqual((self.root / 'mutations.log').read_text(), 'compile runtime.in\ncompile dev.in\n')
        self.assertEqual((requirements / 'lock.sha256').read_bytes(), lock)
        self.assertEqual((requirements / 'dev.in').read_text(), '# the development tools, unsolvable\n')
        self.assertFalse(environment.exists())

    def test_a_lock_edited_by_hand_under_current_inputs_is_refused(self):
        self.prepare()
        requirements = self.lockable()
        (requirements / 'dev.txt').write_text('pylint==3.0.0\n')
        before = contents(requirements)
        for mode in ('--preview', '--apply'):
            result = self.invoke('bootstrap', mode)
            self.assertEqual((result.returncode, result.stdout, result.stderr), (
                2, '', 'Refusing bootstrap because dependency inputs or locks do not match lock.sha256.\n'
                       'runtime.in and dev.in match it, so a lock was changed by hand: move that lock away '
                       'for bootstrap to compile it again, or fingerprint it again in '
                       f'{requirements} with sha256sum runtime.in runtime.txt dev.in dev.txt > lock.sha256.\n'))
            self.unchanged()
            self.assertEqual(contents(requirements), before)

    # -- overrides.txt (v0.15.0 S7) -----------------------------------------------------------

    def test_an_overrides_file_the_fingerprint_does_not_record_makes_bootstrap_compile_with_it(self):
        self.prepare()
        requirements = self.lockable()
        self.running_database()
        (requirements / 'overrides.txt').write_text('-r ../requirements-overrides.txt\n')
        before = contents(requirements)
        # sha256sum --check passes (lock.sha256 does not name it), but the locks are stale.
        preview = self.invoke('bootstrap', '--preview')
        self.assertEqual((preview.returncode, preview.stdout, preview.stderr),
                         (0, self.preview_output(self.python.parent.parent, 'stale'), ''))
        self.unchanged()
        self.assertEqual(contents(requirements), before)
        result = self.invoke('bootstrap', '--apply')
        # The full check that ends the apply passes dependency_locks with the recorded overrides.txt.
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (0, self.expected_apply_output(self.python.parent.parent, locks='stale'), ''))
        self.assertEqual(self.commands.read_text().splitlines()[:2], [
            f'uv pip compile --python-version 3.12 --override overrides.txt runtime.in -o runtime.txt (in {requirements})',
            f'uv pip compile --python-version 3.12 --override overrides.txt dev.in -o dev.txt (in {requirements})'])
        self.assertEqual((requirements / 'lock.sha256').read_text(), fingerprint_with_overrides(requirements))
        self.assertEqual((requirements / 'overrides.txt').read_text(), '-r ../requirements-overrides.txt\n')
        # A changed overrides.txt makes them stale again.
        (requirements / 'overrides.txt').write_text('cryptography==3.4.8\n')
        self.commands.unlink()
        preview = self.invoke('bootstrap')
        self.assertEqual((preview.returncode, preview.stdout, preview.stderr),
                         (0, self.preview_output(self.python.parent.parent, 'stale'), ''))
        self.unchanged()

    def test_check_environment_fails_an_overrides_file_the_fingerprint_does_not_record(self):
        self.prepare()
        requirements = self.lockable()
        result = self.invoke('check-environment')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, self.expected_quick_output(), ''))
        (requirements / 'overrides.txt').write_text('cryptography==3.4.8\n')
        result = self.invoke('check-environment')
        self.assertEqual((result.returncode, result.stderr), (1, 'FAIL dependency_locks=stale_or_modified\n'))
        self.assertEqual(result.stdout, self.expected_quick_output().replace(
            'PASS dependency_locks=current\n', '').replace('environment_failures=0', 'environment_failures=1'))
        (requirements / 'lock.sha256').write_text(fingerprint_with_overrides(requirements))
        result = self.invoke('check-environment')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, self.expected_quick_output(), ''))

    def test_a_lock_edited_by_hand_with_overrides_names_overrides_in_the_refusal(self):
        self.prepare()
        requirements = self.lockable()
        (requirements / 'overrides.txt').write_text('cryptography==3.4.8\n')
        (requirements / 'lock.sha256').write_text(fingerprint_with_overrides(requirements))
        (requirements / 'dev.txt').write_text('pylint==3.0.0\n')
        before = contents(requirements)
        result = self.invoke('bootstrap', '--apply')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (
            2, '', 'Refusing bootstrap because dependency inputs or locks do not match lock.sha256.\n'
                   'runtime.in, dev.in and overrides.txt match it, so a lock was changed by hand: move that lock '
                   'away for bootstrap to compile it again, or fingerprint it again in '
                   f'{requirements} with sha256sum runtime.in runtime.txt dev.in dev.txt overrides.txt > '
                   'lock.sha256.\n'))
        self.unchanged()
        self.assertEqual(contents(requirements), before)

    def test_a_missing_input_stops_before_compiling(self):
        self.prepare()
        requirements = self.lockable(fingerprint_locks=False)
        (requirements / 'dev.txt').unlink()
        (requirements / 'dev.in').unlink()
        for mode in ('--preview', '--apply'):
            result = self.invoke('bootstrap', mode)
            self.assertEqual((result.returncode, result.stdout, result.stderr),
                             (2, '', f'Missing required local path: {requirements / "dev.in"}\n'))
            self.unchanged()

    @unittest.skipIf(shutil.which('uv', path='/usr/bin:/bin'), 'uv is installed in /usr/bin or /bin')
    def test_missing_uv_says_how_to_get_it(self):
        requirements = self.prepare()
        (requirements / 'dev.txt').unlink()
        (self.bindir / 'uv').unlink()
        self.env['PATH'] = f'{self.bindir}:/usr/bin:/bin'
        result = self.invoke('bootstrap', '--apply')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (
            2, '', 'uv is required to bootstrap this environment.\n'
                   'Install uv (https://docs.astral.sh/uv/), then run oasis bootstrap again.\n'))
        self.unchanged()
        self.assertFalse((requirements / 'dev.txt').exists())

    def expected_quick_output(self, python='3.12'):
        files = ('runtime.in', 'runtime.txt', 'dev.in', 'dev.txt', 'lock.sha256')
        return (''.join(f'PASS file:dev/requirements/{name}\n' for name in files)
                + f'PASS python_version={python}\nPASS virtualenv={self.python.parent.parent}\n'
                'PASS uv=0.1\nPASS odoo_version=19.0\nPASS dependency_locks=current\n'
                'PASS compose_config=valid\n'
                'SKIP locked_environment=use_--full\nSKIP dependency_audit=use_--full\n'
                'SKIP postgres_connection=use_--full\nenvironment_mode=quick\nenvironment_failures=0\n')

    def test_check_quick_reports_fixture_and_skips_full_checks(self):
        self.prepare()
        result = self.invoke('check-environment')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (0, self.expected_quick_output(), ''))
        self.assertNotIn('uv pip check', self.commands.read_text() if self.commands.exists() else '')

    def test_check_named_environment_passes_its_declared_python(self):
        self.prepare(runtime=False)
        self.as_workspace(python='3.13')
        self.python.write_text(self.python.read_text().replace('echo 3.12', 'echo 3.13'))
        result = self.invoke('check-environment', '--quick')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (0, self.expected_quick_output('3.13'), ''))

    def assert_python_mismatch(self, declared, found):
        self.python.write_text(self.python.read_text().replace('echo 3.12', f'echo {found}'))
        result = self.invoke('check-environment')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (
            2, '', f'Python {declared} is required; found {found}.\n'
                   f'Move {self.python.parent.parent} away and run oasis bootstrap --apply '
                   f'to recreate it with Python {declared}.\n'))
        self.unchanged()

    def test_check_named_environment_python_mismatch_names_expected_found_and_the_fix(self):
        self.prepare(runtime=False)
        self.as_workspace(python='3.13')
        self.assert_python_mismatch('3.13', '3.12')

    def test_check_profile_python_mismatch_names_expected_found_and_the_fix(self):
        self.prepare()
        self.assert_python_mismatch('3.12', '3.11')

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
