"""Lifecycle CLI tests use only a disposable project and deterministic command fakes."""
from pathlib import Path
import os
import random
import re
import socket
import subprocess
import sys
import tempfile
import unittest

STAGE = Path(__file__).resolve().parents[1]
WORKSPACE = (Path(__file__).resolve().parent / 'fixture-workspace.toml').read_text()
CHECKOUT_SLUG = re.compile(r'^checkout_slug = .*\n', re.MULTILINE)


def write_config(root, text):
    """Write a fixture configuration into the checkout root: the workspace text as
    oasis-workspace.toml, except its [tooling].checkout_slug line (a workspace file refuses it),
    which becomes the checkout's oasis-checkout.toml; without one, no checkout file is left."""
    slugs = CHECKOUT_SLUG.findall(text)
    (root / 'oasis-workspace.toml').write_text(CHECKOUT_SLUG.sub('', text))
    checkout = root / 'oasis-checkout.toml'
    if slugs:
        checkout.write_text('[tooling]\n' + ''.join(slugs))
    elif checkout.exists():
        checkout.unlink()


def free_port():
    """A port that is free on 127.0.0.1 now (tests bind 127.0.0.1 only)."""
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        return probe.getsockname()[1]


def ephemeral_range():
    """The kernel's ip_local_port_range, or Linux's default when it cannot be read."""
    try:
        low, high = map(int, Path('/proc/sys/net/ipv4/ip_local_port_range').read_text().split())
    except (OSError, ValueError):
        return 32768, 60999
    return low, high


def bindable(port):
    """Whether 127.0.0.1:port can be bound now, probed like the tools (SO_REUSEADDR)."""
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(('127.0.0.1', port))
        except OSError:
            return False
    return True


def quiet_ports(count, excluded=()):
    """A port P with P .. P+count-1 free on 127.0.0.1, all outside the ephemeral range.

    A test that expects exactly the port after a configured one (a linked worktree's first
    free port) needs that port to stay free until the tool probes it. free_port's ports come
    from the ephemeral range, where bind(0) hands out odd ports and connect() gives every
    outgoing loopback connection of any process an even source port: P+1 of an odd P can be
    taken in the meantime. Outside that range the kernel never allocates a port, so only a
    process binding that exact port could take it. Ports in excluded are never part of the
    range. Falls back to free_port when the ephemeral range leaves no room.
    """
    low, high = ephemeral_range()
    candidates = [*range(1024, low - count + 1), *range(high + 1, 65536 - count + 1)]
    for _ in range(200):
        port = random.choice(candidates) if candidates else free_port()
        span = range(port, port + count)
        if port + count <= 65536 and not set(span) & set(excluded) and all(map(bindable, span)):
            return port
    raise AssertionError('no free port range on 127.0.0.1')


def any_test_port(line):
    """The Odoo test process gets a fresh free --http-port and second (gevent) port; compare
    the rest exactly.

    Only the test process (a --test-tags line) and a valid port (1-65535) are replaced;
    start's ports stay exact. test_runtime_state checks that the test ports were free.
    """
    if ' --test-tags ' not in line:
        return line

    def replace(match):
        return f' --{match.group(1)}=<free>' if 1 <= int(match.group(2)) <= 65535 else match.group(0)
    return re.sub(r' --(http-port|gevent-port)=(\d{1,5})(?= )', replace, line)


# The fixture's odoo.conf names an addons_path, as a project's did before oasis composed one,
# so the Odoo command lines keep -c alone; test_path_free_conf covers a conf without it.
CONF_ADDONS = 'addons_path = /srv/oasis-fixture/addons\n'


def conf_text(options=''):
    """The text of a fixture odoo.conf with these [options] lines."""
    return '[options]\n' + CONF_ADDONS + options


RUN_DATABASE = r'_r[0-9a-f]{6}'


def any_run_database(line):
    """A disposable test database gets a fresh _r<6 hex> per run; compare the rest exactly.

    Only `-d <name>` arguments are rewritten, to `<name>_r<run>` (or `..._r<run>_update`);
    test_disposable_tests checks the names themselves.
    """
    return re.sub(r'(-d \S+?)_r[0-9a-f]{6}(?=(?:_update)?(?:\s|$))', r'\1_r<run>', line)


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        fixture_root = Path(__file__).resolve().parent / 'fixturesroot'
        fixture_root.mkdir(exist_ok=True)
        self.addCleanup(fixture_root.rmdir)
        self.scratch = tempfile.TemporaryDirectory(dir=fixture_root)
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name) / 'workspace/projects/a project'
        self.root.mkdir(parents=True)
        (self.root / 'oasis-workspace.toml').write_text(WORKSPACE)
        self.source = (self.root / '../../source/odoo').resolve()
        self.python = (self.root / '../../environments/example/bin/python').resolve()
        self.source.mkdir(parents=True, exist_ok=True)
        self.python.parent.mkdir(parents=True, exist_ok=True)
        for name in ('dev/odoo.conf', 'dev/.env', 'dev/compose.yml', 'coffee/__manifest__.py'):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()
        (self.root / 'dev/odoo.conf').write_text(conf_text())
        (self.source / 'odoo-bin').touch()
        (self.source / 'odoo').mkdir(exist_ok=True)
        (self.source / 'odoo/release.py').write_text('version_info = (19, 0, 0, "final", 0)\n')
        self.commands = self.root / 'commands.log'
        self.bindir = self.root / 'fake bin'
        self.bindir.mkdir()
        self.python.write_text('#!/bin/sh\n'
                               'if [ "$1" = "-c" ]; then echo 3.12; exit 0; fi\n'
                               'if [ "$2" = "--version" ]; then echo "Odoo Server 19.0"; exit 0; fi\n'
                               'printf "odoo %s\\n" "$*" >> "$FAKE_LOG"\n'
                               'if [ "$2" = "shell" ]; then cat; fi\n')
        docker = self.bindir / 'docker'
        # A reset (dropdb --if-exists + createdb) records its database, so later phases of
        # the same run see it; FAKE_EXISTS=1 makes every database exist.
        docker.write_text('''#!/bin/sh
printf "docker %s\\n" "$*" >> "$FAKE_LOG"
for last; do :; done
case "$*" in
  *"dropdb --if-exists"*"createdb"*) printf "%s\\n" "$last" >> "$FAKE_LOG.databases" ;;
  *"exec psql"*"SELECT 1 FROM pg_database"*)
    name=$(printf "%s" "$*" | sed -n "s/.*datname = '\\([^']*\\)'.*/\\1/p")
    if [ "${FAKE_EXISTS:-0}" = 1 ] || grep -qsx "$name" "$FAKE_LOG.databases"; then echo 1; fi ;;
  *"exec psql"*"SELECT count(*) FROM pg_stat_activity"*) echo "${FAKE_SESSIONS:-0}" ;;
  *"to_regclass"*) echo t ;;
  *"COALESCE(latest_version"*) printf 'installed\\t19.0\\n' ;;
esac
exit 0
''')
        self.python.chmod(0o755)
        docker.chmod(0o755)
        self.env = {**os.environ, 'PATH': str(self.bindir) + ':' + os.environ['PATH'],
                    'FAKE_LOG': str(self.commands), 'PYTHONDONTWRITEBYTECODE': '1',
                    'ODOO19_TOOLS_DIR': str(STAGE / 'tools'),
                    # Keep git discovery inside the scratch project: no checkout identity
                    # leaks from the repository that holds the fixtures.
                    'GIT_CEILING_DIRECTORIES': self.scratch.name}
        # Server records (tools/runtime_state.py) stay in a private runtime directory per test.
        self.runtime = tempfile.TemporaryDirectory(prefix='oasis-runtime-')
        self.addCleanup(self.runtime.cleanup)
        self.env['XDG_RUNTIME_DIR'] = self.runtime.name

    def invoke(self, command, *args, input=None):
        path = self.root / 'dev/scripts' / command
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((STAGE / 'project-wrappers' / command).read_bytes())
        return subprocess.run(['bash', str(path), *args], text=True, input=input,
                              cwd=self.root, env=self.env, capture_output=True)

    def unchanged(self):
        self.assertFalse(self.commands.exists(), self.commands.read_text() if self.commands.exists() else '')

    def test_usage_names_project_wrapper_not_global_tool(self):
        for command, args, tail in (
                ('update-module', ('coffee',), ' <module> <database>'),
                ('list-databases', ('unexpected',), '')):
            result = self.invoke(command, *args)
            self.assertEqual((result.returncode, result.stdout, result.stderr),
                             (2, '', 'Usage: ' + str(self.root / 'dev/scripts' / command) + tail + '\n'))
            self.unchanged()

    def test_wrong_runtime_version_rejects_before_docker(self):
        self.python.write_text(self.python.read_text().replace('echo 3.12', 'echo 3.11'))
        result = self.invoke('install-module', 'coffee')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (2, '', 'Python 3.12 is required; found 3.11.\n'))
        self.unchanged()

    def test_wrong_odoo_runtime_rejects_before_docker(self):
        self.python.write_text(self.python.read_text().replace('Odoo Server 19.0', 'Odoo Server 119.0'))
        result = self.invoke('install-module', 'coffee')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (2, '', (
            f'Odoo runtime 19.0 is required; {self.source / "odoo-bin"} reports: Odoo Server 119.0.\n'
            'Point [tooling].community at an Odoo 19.0 source, then check it with oasis doctor.\n')))
        self.unchanged()

    def test_odoo_shell_refuses_extra_arguments_with_its_usage(self):
        usage = 'Usage: ' + str(self.root / 'dev/scripts/odoo-shell') + ' <database>\n'
        self.env['FAKE_EXISTS'] = '1'
        for args in (('cc_dev_coffee', 'extra'), ('cc_dev_coffee', '--', 'x'), ('--help', 'extra'), ()):
            with self.subTest(args=args):
                result = self.invoke('odoo-shell', *args, input='print(42)\n')
                self.assertEqual((result.returncode, result.stdout, result.stderr), (2, '', usage))
                self.unchanged()

    def test_invalid_module_rejects_before_docker(self):
        result = self.invoke('install-module', "coffee';DROP")
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (2, '', 'Module must use only letters, numbers, and underscores.\n'))
        self.unchanged()

    def test_install_default_and_piped_shell(self):
        result = self.invoke('install-module', 'coffee')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))
        self.assertIn('odoo ' + str(self.source / 'odoo-bin') + ' -c ' + str(self.root / 'dev/odoo.conf') +
                      ' -d cc_dev_coffee -i coffee --without-demo --stop-after-init\n', self.commands.read_text())
        self.env['FAKE_EXISTS'] = '1'
        result = self.invoke('odoo-shell', 'cc_dev_coffee', input='print(42)\n')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, 'print(42)\n', ''))
        self.assertIn(' shell -c ' + str(self.root / 'dev/odoo.conf') + ' -d cc_dev_coffee\n',
                      self.commands.read_text())

    def test_missing_tools_fails_clearly_without_fallback(self):
        self.env['ODOO19_TOOLS_DIR'] = str(self.root / 'not installed')
        result = self.invoke('status')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (2, '', 'oasis tools are not installed: ' +
                          str(self.root / 'not installed/status') + '\n'))
        self.unchanged()

    def test_missing_config_and_bad_release_precede_external_commands(self):
        (self.root / 'oasis-workspace.toml').unlink()
        result = self.invoke('status')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (2, '', f'ERROR: Missing tooling configuration: no oasis-workspace.toml at or above {self.root}.\n'))
        self.unchanged()
        # A legacy profile is refused before anything runs, with the fix, also next to a workspace.
        profile = self.root / '.odoo19-agent.toml'
        profile.write_text('[tooling]\n')
        refusal = (f'ERROR: {profile} is the old profile format, no longer read: run oasis migrate --plan to see '
                   'its conversion to oasis-workspace.toml, then oasis migrate --apply.\n')
        for workspace in (False, True):
            if workspace:
                (self.root / 'oasis-workspace.toml').write_text(WORKSPACE)
            result = self.invoke('status')
            self.assertEqual((result.returncode, result.stdout, result.stderr), (2, '', refusal))
            self.unchanged()
        profile.unlink()
        (self.source / 'odoo/release.py').write_text('version_info = (18, 0)\n')
        result = self.invoke('status')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (2, '', 'Odoo source must declare release 19.0.\n'))
        self.unchanged()

    def test_invalid_database_blocks_sql_for_update_and_shell(self):
        for command, args in [('update-module', ('coffee', "unsafe'")),
                              ('odoo-shell', ("unsafe'",))]:
            result = self.invoke(command, *args)
            self.assertEqual((result.returncode, result.stdout, result.stderr),
                             (2, '', 'Database name must use only letters, numbers, and underscores.\n'))
            self.unchanged()

    def test_unmanaged_demo_rejected_without_commands(self):
        result = self.invoke('install-module', '--with-demo', 'coffee', 'other_db')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (2, '', 'Managed databases must use cc_dev_<name> or cc_test_<name>: other_db\n'))
        self.unchanged()

    def test_test_reset_refuses_active_sessions(self):
        self.env.update(FAKE_EXISTS='1', FAKE_SESSIONS='2')
        result = self.invoke('test-module', 'coffee', 'cc_test_coffee')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (3, '', 'Refusing to reset database with 2 active session(s): cc_test_coffee\n'
                          'Close those sessions or explicitly drop the database with --terminate.\n'))
        self.assertNotIn('dropdb ', self.commands.read_text())
        self.assertNotIn('odoo ', self.commands.read_text())

    def test_drop_requires_terminate_then_explicit_terminate(self):
        # Only cc_dev_coffee exists (its trash name is free); drop-database moves it to the trash.
        Path(str(self.commands) + '.databases').write_text('cc_dev_coffee\n')
        self.env.update(FAKE_SESSIONS='2')
        plan = (r'database=cc_dev_coffee\nsize=unknown\nsessions=2\nfilestore=none\n'
                r'trash=(cc_dev_coffee_trash_\d{8}_\d{6})\n')
        result = self.invoke('drop-database', 'cc_dev_coffee')
        self.assertEqual((result.returncode, result.stderr),
                         (3, 'Refusing to drop database with 2 active session(s): cc_dev_coffee\n'
                          'Retry with --terminate only after confirming those sessions may be closed.\n'))
        self.assertRegex(result.stdout, rf'\A{plan}\Z')
        self.assertNotIn('pg_terminate_backend', self.commands.read_text())
        self.assertNotIn('ALTER DATABASE', self.commands.read_text())
        result = self.invoke('drop-database', 'cc_dev_coffee', '--terminate')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertRegex(result.stdout, rf'\A{plan}Database moved to trash: cc_dev_coffee -> \1\n'
                                        r'Restore it with: oasis trash restore \1\n\Z')
        self.assertIn('pg_terminate_backend', self.commands.read_text())
        self.assertNotIn('dropdb', self.commands.read_text())

    def test_update_uses_explicit_existing_managed_database_and_test_defaults(self):
        result = self.invoke('update-module', 'coffee', 'other_db')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (2, '', 'Managed databases must use cc_dev_<name> or cc_test_<name>: other_db\n'))
        self.unchanged()
        self.env['FAKE_EXISTS'] = '1'
        result = self.invoke('update-module', 'coffee', 'cc_dev_coffee')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))
        self.assertIn('-d cc_dev_coffee -u coffee --stop-after-init', self.commands.read_text())
        self.assertNotIn('createdb', self.commands.read_text())
        del self.env['FAKE_EXISTS']
        result = self.invoke('test-module', 'coffee')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))
        self.assertRegex(self.commands.read_text(), '-d cc_test_coffee' + RUN_DATABASE +
                         ' -i coffee --without-demo --test-tags /coffee --stop-after-init')

    def test_only_runs_one_class_or_method(self):
        for only, tags in (('TestOrder', '/coffee:TestOrder'), ('TestOrder.test_total', '/coffee:TestOrder.test_total')):
            with self.subTest(only=only):
                self.commands.unlink(missing_ok=True)
                result = self.invoke('test-module', '--only', only, 'coffee')
                self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))
                self.assertRegex(self.commands.read_text(), '-d cc_test_coffee' + RUN_DATABASE +
                                 f' -i coffee --without-demo --test-tags {tags} --stop-after-init')
        self.commands.unlink(missing_ok=True)
        result = self.invoke('test-module', '--compact', '--only', 'TestOrder', 'coffee')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertRegex(result.stdout, r'(?m)^phase=tests database=cc_test_coffee_r[0-9a-f]{6} exit=0$')
        self.assertIn(' --test-tags /coffee:TestOrder --stop-after-init', self.commands.read_text())

    def test_only_refuses_anything_but_a_class_or_method(self):
        for only in ('', 'Test Order', 'a,b', '/other:Test', 'Test.one.two', '-Test', 'Test;id', '.method'):
            with self.subTest(only=only):
                result = self.invoke('test-module', '--only', only, 'coffee')
                self.assertEqual((result.returncode, result.stdout), (2, ''))
                self.assertEqual(result.stderr, '--only takes a test class or Class.method.\n')
                self.unchanged()
        result = self.invoke('test-module', '--only')
        self.assertEqual((result.returncode, result.stdout), (2, ''))
        self.unchanged()

    def test_update_module_compact_keeps_the_log_on_disk(self):
        self.env['FAKE_EXISTS'] = '1'
        self.python.write_text(self.python.read_text() +
            'case " $* " in *" -u "*) echo "update out"; echo "update err" >&2; exit "${FAKE_UPDATE_EXIT:-0}" ;; esac\n')
        for code in (0, 7):
            with self.subTest(code=code):
                self.env['FAKE_UPDATE_EXIT'] = str(code)
                result = self.invoke('update-module', '--compact', 'coffee', 'cc_dev_coffee')
                self.assertEqual((result.returncode, result.stderr), (code, ''))
                lines = result.stdout.splitlines()
                self.assertEqual(lines[0], f'phase=update database=cc_dev_coffee exit={code}')
                self.assertEqual([line.split('=', 1)[0] for line in lines[1:]], ['stdout_log', 'stderr_log'])
                out, err = (Path(line.split('=', 1)[1]) for line in lines[1:])
                self.assertEqual((out.read_text(), err.read_text()), ('update out\n', 'update err\n'))
                self.assertEqual({out.stat().st_mode & 0o777, err.stat().st_mode & 0o777}, {0o600})
                self.assertEqual(out.parent, err.parent)
                self.assertRegex(str(out), r'/dev/logs/odoo19/run-[^/]+/stdout\.log$')
        self.assertIn('-d cc_dev_coffee -u coffee --stop-after-init', self.commands.read_text())

    def test_update_module_compact_refuses_before_any_log(self):
        logs = self.root / 'dev/logs/odoo19'
        for args, message in (
                (('coffee', 'other_db'), 'Managed databases must use cc_dev_<name> or cc_test_<name>: other_db\n'),
                (('coffee', 'cc_dev_coffee'), None)):  # the database does not exist
            with self.subTest(args=args):
                result = self.invoke('update-module', '--compact', *args)
                self.assertEqual((result.returncode, result.stdout), (2, ''))
                if message:
                    self.assertEqual(result.stderr, message)
                self.assertFalse(logs.exists() and any(logs.iterdir()))
        self.assertNotIn(' -u ', self.commands.read_text() if self.commands.exists() else '')

    def odoo_lines(self):
        return [line for line in self.commands.read_text().splitlines() if line.startswith('odoo ')]

    def resets(self):
        return self.commands.read_text().count('dropdb --if-exists')

    def test_reuse_installs_once_then_updates(self):
        result = self.invoke('test-module', '--reuse', 'coffee')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))
        self.assertEqual(self.resets(), 1)
        self.assertRegex(self.odoo_lines()[-1],
                         r' -d cc_test_coffee -i coffee --without-demo --test-tags /coffee --stop-after-init$')
        # The database now exists with the module installed: the next runs update it and keep it.
        result = self.invoke('test-module', '--reuse', '--only', 'TestOrder.test_total', 'coffee')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))
        self.assertEqual(self.resets(), 1)
        self.assertRegex(self.odoo_lines()[-1],
                         r' -d cc_test_coffee -u coffee --test-tags /coffee:TestOrder\.test_total --stop-after-init$')
        self.assertNotIn('--without-demo', self.odoo_lines()[-1])
        result = self.invoke('test-module', '--compact', '--reuse', 'coffee')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        lines = result.stdout.splitlines()
        self.assertEqual(lines[:2], ['phase=tests database=cc_test_coffee exit=0',
                                     'database_lifecycle=reused mode=update'])
        self.assertEqual([line.split('=', 1)[0] for line in lines[2:]], ['stdout_log', 'stderr_log'])
        self.assertEqual(self.resets(), 1)
        self.assertRegex(self.odoo_lines()[-1], r' -d cc_test_coffee -u coffee --test-tags /coffee --stop-after-init$')

    def test_reuse_reinstalls_when_the_module_is_not_installed(self):
        docker = self.bindir / 'docker'
        docker.write_text(docker.read_text().replace("printf 'installed\\t19.0\\n'", "printf 'uninstalled\\t\\n'"))
        self.env['FAKE_EXISTS'] = '1'
        result = self.invoke('test-module', '--compact', '--reuse', 'coffee')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertEqual(result.stdout.splitlines()[:2], ['phase=tests database=cc_test_coffee exit=0',
                                                          'database_lifecycle=reused mode=install'])
        self.assertEqual(self.resets(), 1)
        self.assertRegex(self.odoo_lines()[-1],
                         r' -d cc_test_coffee -i coffee --without-demo --test-tags /coffee --stop-after-init$')

    def test_reuse_stops_when_the_module_state_cannot_be_read(self):
        docker = self.bindir / 'docker'
        for query in ('*"to_regclass"*) echo t ;;', "*\"COALESCE(latest_version\"*) printf 'installed\\t19.0\\n' ;;"):
            with self.subTest(query=query.split(')')[0]):
                original = docker.read_text()
                self.assertIn(query, original)
                docker.write_text(original.replace(query, query.split(')')[0] + ') echo "connection lost" >&2; exit 2 ;;'))
                self.env['FAKE_EXISTS'] = '1'
                self.commands.unlink(missing_ok=True)
                result = self.invoke('test-module', '--reuse', 'coffee')
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, '')
                # Neither reset nor tested: the working database is left as it was.
                self.assertEqual(self.resets(), 0)
                self.assertEqual(self.odoo_lines(), [])
                docker.write_text(original)

    def test_a_failed_existence_probe_stops_instead_of_looking_missing(self):
        docker = self.bindir / 'docker'
        probe = '*"exec psql"*"SELECT 1 FROM pg_database"*)'
        original = docker.read_text()
        self.assertIn(probe, original)
        docker.write_text(original.replace(probe, probe + ' echo "connection lost" >&2; exit 2 ;;\n  *"never matches"*)'))
        for command, args in (('test-module', ('--reuse', 'coffee')), ('module-status', ('coffee', 'cc_test_coffee')),
                              ('update-module', ('coffee', 'cc_dev_coffee'))):
            with self.subTest(command=command):
                self.commands.unlink(missing_ok=True)
                result = self.invoke(command, *args)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn('database_state=missing', result.stdout)
                self.assertNotIn('does not exist', result.stderr)
                self.assertIn('Cannot check whether database', result.stderr)
                self.assertEqual(self.resets(), 0)
                self.assertEqual(self.odoo_lines(), [])

    def test_reuse_takes_an_explicit_database_in_the_test_namespace(self):
        result = self.invoke('test-module', '--reuse', 'coffee', 'cc_test_iterate')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))
        self.assertRegex(self.odoo_lines()[-1], r' -d cc_test_iterate -i coffee ')
        before = self.commands.read_text()
        for database, message in (
                ('cc_dev_coffee', 'Test databases must use the cc_test_ prefix.\n'),
                ('cc_test_coffee_r0a1b2c', 'Database names ending in _r<6 hex> are reserved for disposable runs: cc_test_coffee_r0a1b2c\n')):
            with self.subTest(database=database):
                result = self.invoke('test-module', '--reuse', 'coffee', database)
                self.assertEqual((result.returncode, result.stdout, result.stderr), (2, '', message))
                self.assertEqual(self.commands.read_text(), before)

    def test_custom_prefixes_and_verify_distinct_names(self):
        path = self.root / 'oasis-workspace.toml'
        path.write_text(WORKSPACE.replace('cc_dev_', 'demo_dev_').replace('cc_test_', 'demo_test_'))
        result = self.invoke('install-module', 'coffee')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))
        self.assertIn('-d demo_dev_coffee -i coffee', self.commands.read_text())
        before = self.commands.read_text()
        result = self.invoke('verify-module', 'coffee', 'demo_test_same', 'demo_test_same')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (2, '', 'Test and update verification require different databases.\n'))
        self.assertEqual(self.commands.read_text(), before)

    def test_verify_has_distinct_test_and_fresh_install_update_phases(self):
        result = self.invoke('verify-module', 'coffee')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, '')
        tests = re.search('^tests_database=(cc_test_coffee' + RUN_DATABASE + ')$', result.stdout, re.M).group(1)
        self.assertIn(f'update_database={tests}_update\n', result.stdout)
        self.assertIn('update_baseline=current_code_fresh_install\n', result.stdout)
        self.assertIn('current_code_update_exit=0\n', result.stdout)
        log = self.commands.read_text()
        self.assertIn(f'-d {tests} -i coffee --without-demo --test-tags /coffee --stop-after-init', log)
        self.assertIn(f'-d {tests}_update -i coffee --without-demo --stop-after-init', log)
        self.assertIn(f'-d {tests}_update -u coffee --stop-after-init', log)

    def configure_test_database(self, value='cc_test_shared'):
        path = self.root / 'oasis-workspace.toml'
        path.write_text(WORKSPACE.replace('test_prefix =', f'test_database = "{value}"\ntest_prefix ='))

    def test_configured_test_database_and_explicit_override(self):
        self.configure_test_database()
        for args, database in [(('coffee',), 'cc_test_shared'),
                               (('coffee', 'cc_test_isolated'), 'cc_test_isolated')]:
            result = self.invoke('test-module', *args)
            self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))
            self.assertIn(f'-d {database} -i coffee', self.commands.read_text())
        self.assertNotIn('cc_dev_', self.commands.read_text())

    def test_unconfigured_profile_does_not_inherit_database_from_environment(self):
        self.env['TEST_DATABASE'] = 'cc_test_unintended'
        result = self.invoke('test-module', 'coffee')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))
        self.assertNotIn('cc_test_unintended', self.commands.read_text())
        self.assertRegex(self.commands.read_text(), '-d cc_test_coffee' + RUN_DATABASE + ' -i coffee')

    def test_invalid_configured_test_target_blocks_commands(self):
        for value in ('cc_dev_manual', 'other_db', 'cc_test_', 'cc_test_bad;echo',
                      'cc_test_' + 'a' * 49):
            self.configure_test_database(value)
            result = self.invoke('test-module', 'coffee')
            self.assertEqual((result.returncode, result.stdout, result.stderr),
                             (2, '', 'ERROR: Unsafe tooling test database.\n'))
            self.unchanged()

    def test_verify_uses_configured_target_and_separate_update_baseline(self):
        self.configure_test_database()
        result = self.invoke('verify-module', 'coffee')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertIn('tests_database=cc_test_shared\n', result.stdout)
        self.assertIn('update_database=cc_test_shared_update\n', result.stdout)
        self.assertIn('update_baseline=current_code_fresh_install\n', result.stdout)

    def test_configured_name_boundary_and_verify_override(self):
        database = 'cc_test_' + 'a' * 48
        self.configure_test_database(database)
        result = self.invoke('test-module', 'coffee')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))
        self.assertIn(f'-d {database} -i coffee', self.commands.read_text())
        result = self.invoke('verify-module', 'coffee', 'cc_test_isolated')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertIn('tests_database=cc_test_isolated\n', result.stdout)
        self.assertIn('update_database=cc_test_isolated_update\n', result.stdout)

    def test_compact_tests_preserve_streams_and_failure_status(self):
        self.configure_test_database()
        self.python.write_text(self.python.read_text() +
                               'echo "tests stdout"\necho "tests stderr" >&2\nexit 7\n')
        result = self.invoke('test-module', '--compact', 'coffee')
        self.assertEqual((result.returncode, result.stderr), (7, ''))
        lines = result.stdout.splitlines()
        self.assertEqual(lines[0], 'phase=tests database=cc_test_shared exit=7')
        logs = dict(line.split('=', 1) for line in lines[1:])
        self.assertEqual(set(logs), {'stdout_log', 'stderr_log'})
        self.assertEqual(Path(logs['stdout_log']).read_text(), 'tests stdout\n')
        self.assertEqual(Path(logs['stderr_log']).read_text(), 'tests stderr\n')
        self.assertEqual(Path(logs['stdout_log']).stat().st_mode & 0o777, 0o600)
        self.assertTrue(Path(logs['stdout_log']).is_relative_to(self.root / 'dev/logs/odoo19'))

    def test_compact_verify_retains_each_phase_logs(self):
        self.configure_test_database()
        result = self.invoke('verify-module', '--compact', 'coffee')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        for phase in ('tests', 'prepare_update_database', 'fresh_install', 'current_code_update'):
            line = next(line for line in result.stdout.splitlines() if line.startswith(f'phase={phase} '))
            self.assertIn('exit=0', line)
        paths = [line.split('=', 1)[1] for line in result.stdout.splitlines()
                 if line.startswith(('stdout_log=', 'stderr_log='))]
        self.assertEqual(len(paths), 8)
        self.assertTrue(all(Path(path).is_file() for path in paths))
        self.assertEqual(len(set(paths)), 8)

    def test_compact_refusal_retains_error_without_reset(self):
        self.configure_test_database()
        self.env.update(FAKE_EXISTS='1', FAKE_SESSIONS='2')
        result = self.invoke('test-module', '--compact', 'coffee')
        self.assertEqual((result.returncode, result.stderr), (3, ''))
        lines = result.stdout.splitlines()
        self.assertEqual(lines[0], 'phase=tests database=cc_test_shared exit=3')
        logs = dict(line.split('=', 1) for line in lines[1:])
        self.assertEqual(Path(logs['stdout_log']).read_text(), '')
        self.assertEqual(Path(logs['stderr_log']).read_text(),
                         'Refusing to reset database with 2 active session(s): cc_test_shared\n'
                         'Close those sessions or explicitly drop the database with --terminate.\n')
        self.assertNotIn('dropdb ', self.commands.read_text())
        self.assertNotIn('odoo ', self.commands.read_text())

    def test_compact_help_does_not_run_commands(self):
        for command in ('test-module', 'verify-module'):
            result = self.invoke(command, '--help')
            self.assertEqual((result.returncode, result.stderr), (0, ''))
            self.assertIn('[--compact]', result.stdout)
            self.assertIn('sequentially', result.stdout)
            self.unchanged()

    def test_configured_target_still_refuses_active_sessions(self):
        self.configure_test_database()
        self.env.update(FAKE_EXISTS='1', FAKE_SESSIONS='2')
        result = self.invoke('test-module', 'coffee')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (3, '', 'Refusing to reset database with 2 active session(s): cc_test_shared\n'
                          'Close those sessions or explicitly drop the database with --terminate.\n'))
        self.assertNotIn('dropdb ', self.commands.read_text())
        self.assertNotIn('odoo ', self.commands.read_text())

    def test_odoo_command_lines_outside_git_are_exact(self):
        odoo = 'odoo ' + str(self.source / 'odoo-bin')
        conf = str(self.root / 'dev/odoo.conf')
        port = free_port()
        (self.root / 'dev/odoo.conf').write_text(conf_text(f'http_port = {port}\n'))
        for command, args, exists, line in (
                ('test-module', ('coffee',), '0', f'{odoo} -c {conf} --http-port=<free> --gevent-port=<free> -d cc_test_coffee_r<run> '
                 '-i coffee --without-demo --test-tags /coffee --stop-after-init'),
                ('install-module', ('coffee',), '0',
                 f'{odoo} -c {conf} -d cc_dev_coffee -i coffee --without-demo --stop-after-init'),
                ('update-module', ('coffee', 'cc_dev_coffee'), '1',
                 f'{odoo} -c {conf} -d cc_dev_coffee -u coffee --stop-after-init'),
                ('odoo-shell', ('cc_dev_coffee',), '1', f'{odoo} shell -c {conf} -d cc_dev_coffee'),
                ('start', ('--workers=0',), '0', f'{odoo} -c {conf} --http-port={port} --workers=0')):
            with self.subTest(command=command):
                self.env['FAKE_EXISTS'] = exists
                result = self.invoke(command, *args, input='')
                self.assertEqual(result.returncode, 0)
                if command == 'start':
                    self.assertRegex(result.stderr, rf'^oasis start: http://localhost:{port} \(pid \d+\)\n$')
                else:
                    self.assertEqual(result.stderr, '')
                self.assertEqual([any_run_database(any_test_port(entry))
                                  for entry in self.commands.read_text().splitlines()
                                  if entry.startswith('odoo ')], [line])
                self.commands.unlink()

    def test_demo_off_argv_on_odoo_19_is_byte_identical_to_before(self):
        # The demo-off options now come from the capability table (ODOO_DEMO_OFF_ARGS); for
        # 19.0 it keeps the previous explicit --without-demo, so these argv are unchanged.
        odoo = 'odoo ' + str(self.source / 'odoo-bin')
        conf = str(self.root / 'dev/odoo.conf')
        (self.root / 'dev/odoo.conf').write_text(conf_text())
        for command, before in (
                ('test-module', [odoo, '-c', conf, '--http-port=<free>', '--gevent-port=<free>', '-d', 'cc_test_coffee_r<run>', '-i',
                                 'coffee', '--without-demo', '--test-tags', '/coffee', '--stop-after-init']),
                ('install-module', [odoo, '-c', conf, '-d', 'cc_dev_coffee', '-i', 'coffee', '--without-demo',
                                    '--stop-after-init'])):
            with self.subTest(command=command):
                self.env['FAKE_EXISTS'] = '0'
                result = self.invoke(command, 'coffee', input='')
                self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))
                self.assertEqual([any_run_database(any_test_port(entry))
                                  for entry in self.commands.read_text().splitlines() if entry.startswith('odoo ')],
                                 [' '.join(before)])
                self.commands.unlink()
        # The install-module help names the same default as before.
        result = self.invoke('install-module', '--help')
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.splitlines()[1], 'Default: --without-demo. The database must be managed '
                                                        '(cc_dev_/cc_test_) and defaults to cc_dev_<module>.')

    def test_start_status_stop_create_list_and_module_status(self):
        port = free_port()
        (self.root / 'dev/odoo.conf').write_text(conf_text(f'http_port = {port}\n'))
        result = self.invoke('start')
        self.assertEqual((result.returncode, result.stdout), (0, ''))
        self.assertRegex(result.stderr, rf'^oasis start: http://localhost:{port} \(pid \d+\)\n$')
        for command, args, output in (
                ('status', (), 'server: stopped\n'),
                ('stop', (), 'No Odoo server running for this checkout.\n'),
                ('create-database', ('cc_dev_coffee',), 'Database ready: cc_dev_coffee\n'),
                ('list-databases', (), ''),
                ('module-status', ('coffee', 'cc_dev_coffee'),
                 'database=cc_dev_coffee\nmodule=coffee\ndatabase_state=missing\nmodule_state=unknown\n')):
            result = self.invoke(command, *args)
            self.assertEqual((result.returncode, result.stdout, result.stderr), (0, output, ''), command)
        self.assertIn(f' --http-port={port}\n', self.commands.read_text())


if __name__ == '__main__':
    unittest.main()
