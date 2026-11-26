"""The series guard (v0.14.0 S11): a checkout whose module manifests carry a series-style version
(`<series>.x.y.z`) of another series than the configured odoo_version is refused by every command
that loads the configuration (tools/config.py load), with exit 2 before anything runs.

Every path lives in a fresh system temp directory; git is kept out with a ceiling and docker is a
fake that records its calls, so nothing reads a real project or starts a service.
"""
import oasis_test_env  # noqa: F401  first: XDG_CONFIG_HOME is scratch (tests/oasis_test_env.py)
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import unittest.mock

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / 'oasis'
READER = ROOT / 'tools' / 'config.py'
WORKSPACE = '''workspace_version = 1
odoo_version = '19.0'

[tooling]
community = '../source/odoo'
environment = '../environment'
config = 'dev/odoo.conf'
env_file = 'dev/env'
compose = 'dev/compose.yml'
requirements = 'dev/requirements'
addons_paths = ['addons', 'more']
db_service = 'db'
dev_prefix = 'shop_dev_'
test_prefix = 'shop_test_'
'''


def manifest(version):
    return f"{{'name': 'A module', 'version': {version!r}, 'depends': ['base']}}\n"


class SeriesGuardTests(unittest.TestCase):
    def setUp(self):
        self.scratch = Path(tempfile.mkdtemp(prefix='oasis-series-')).resolve()
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)
        source = self.scratch / 'source/odoo'
        (source / 'odoo').mkdir(parents=True)
        (source / 'odoo/release.py').write_text('version_info = (19, 0, 0, "final", 0)\n')
        (source / 'odoo-bin').touch()
        environment = self.scratch / 'environment'
        (environment / 'bin').mkdir(parents=True)
        (environment / 'pyvenv.cfg').write_text('home = /usr/bin\n')
        self.root = self.scratch / 'shop'
        (self.root / 'dev').mkdir(parents=True)
        (self.root / 'oasis-workspace.toml').write_text(WORKSPACE)
        (self.root / 'dev/odoo.conf').write_text('[options]\n')
        self.module('addons', 'shop_sale', '19.0.1.0.0')
        self.module('more', 'shop_extra', '1.0')
        bindir = self.scratch / 'bin'
        bindir.mkdir()
        self.log = self.scratch / 'calls.log'
        (bindir / 'docker').write_text('#!/bin/sh\nprintf "docker %s\\n" "$*" >> "$FAKE_LOG"\nexit 0\n')
        (bindir / 'docker').chmod(0o755)
        self.env = {key: value for key, value in os.environ.items() if not key.startswith(('GIT_', 'OASIS_', 'ODOO19_'))}
        self.env.update({'PATH': f'{bindir}:{os.environ["PATH"]}', 'FAKE_LOG': str(self.log),
                         'GIT_CEILING_DIRECTORIES': str(self.scratch), 'PYTHONDONTWRITEBYTECODE': '1',
                         'XDG_RUNTIME_DIR': str(self.scratch)})

    def module(self, addons, name, version):
        path = self.root / addons / name / '__manifest__.py'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(manifest(version))
        return path

    def reader(self):
        return subprocess.run([sys.executable, '-B', str(READER), str(self.root)], capture_output=True, text=True,
                              env=self.env)

    def oasis(self, *args):
        return subprocess.run([sys.executable, '-B', str(CLI), '--project', str(self.root), *args],
                              capture_output=True, text=True, env=self.env, stdin=subprocess.DEVNULL)

    def refusal(self, module, found, version, addons='addons'):
        # A supported series (15.0) is told to add its section (v0.15.0 S3); another one is not supported.
        workspace = self.root / 'oasis-workspace.toml'
        tail = (f'for Odoo {found} here, run oasis setup to add a [series."{found}"] section to {workspace}'
                if found == '15.0' else f'oasis does not support Odoo {found} (supported: 19.0, 15.0)')
        return (f'The module {module} declares Odoo {found} (version {version} in '
                f'{self.root / addons / module / "__manifest__.py"}), but {self.root} is configured for Odoo 19.0 by '
                f'{workspace}: run oasis in a checkout of an Odoo 19.0 branch, or set the '
                f'version of {module} to 19.0.x.y.z if it is an Odoo 19.0 module; {tail}.')

    def test_a_module_of_another_series_is_refused_by_every_reader(self):
        self.assertEqual(self.reader().returncode, 0, self.reader().stderr)
        self.module('more', 'old_sale', '15.0.1.0.0')
        message = f'ERROR: {self.refusal("old_sale", "15.0", "15.0.1.0.0", "more")}\n'
        result = self.reader()
        self.assertEqual((result.returncode, result.stdout, result.stderr), (2, '', message))
        # A shell tool (through common.sh) and a Python tool stop with the same refusal, before docker.
        for args in (('start', '--print-command'), ('list-databases',), ('module-info', 'shop_sale')):
            with self.subTest(args=args):
                result = self.oasis(*args)
                self.assertEqual((result.returncode, result.stdout, result.stderr), (2, '', message))
        self.assertFalse(self.log.exists())

    def test_the_first_offending_module_is_named(self):
        self.module('addons', 'b_old', '15.0.1.0.0')
        self.module('addons', 'a_old', '16.0.2.0.1')
        self.module('more', 'c_old', '14.0.1.0.0')
        result = self.reader()
        self.assertEqual((result.returncode, result.stderr),
                         (2, f'ERROR: {self.refusal("a_old", "16.0", "16.0.2.0.1")}\n'))

    def test_manifests_without_a_series_style_version_or_outside_the_addons_paths_are_ignored(self):
        for version in ('1.0', '1.0.0', '19.0.1.0', '19.0.1.0.0', '1.2.3.4.5', '7.0.1.0.0', '15.1.1.0.0',
                        '015.0.1.0.0', '15.0.1.0.0.0', 15.0, None):
            self.module('addons', 'mixed', version)
            with self.subTest(version=version):
                result = self.reader()
                self.assertEqual((result.returncode, result.stderr), (0, ''))
        (self.root / 'addons/mixed/__manifest__.py').unlink()
        # Not a module of an addons path: outside them, hidden, nested deeper, or not a literal manifest.
        self.module('other', 'old_sale', '15.0.1.0.0')
        self.module('addons/.old', 'old_sale', '15.0.1.0.0')
        (self.root / 'addons/.hidden').mkdir()
        (self.root / 'addons/.hidden/__manifest__.py').write_text(manifest('15.0.1.0.0'))
        self.module('addons/shop_sale', 'nested', '15.0.1.0.0')
        marker = self.scratch / 'executed'
        (self.root / 'addons/code').mkdir()
        (self.root / 'addons/code/__manifest__.py').write_text(
            f"{{'version': __import__('pathlib').Path({str(marker)!r}).touch() or '15.0.1.0.0'}}\n")
        (self.root / 'addons/broken').mkdir()
        (self.root / 'addons/broken/__manifest__.py').write_bytes(b"{'version': '15.0.1.0.0'\xff\n")
        result = self.reader()
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertFalse(marker.exists())

    def test_doctor_and_setup_run_and_report_it(self):
        self.module('addons', 'old_sale', '15.0.1.0.0')
        doctor = self.oasis('doctor')
        self.assertEqual((doctor.returncode, doctor.stderr), (1, ''))
        self.assertIn('PASS configuration=workspace\n', doctor.stdout)
        self.assertIn('FAIL module_series=15.0 module=old_sale expected=19.0\n  fix: run oasis in a checkout', doctor.stdout)
        setup = self.oasis('setup')
        self.assertEqual((setup.returncode, setup.stdout, setup.stderr),
                         (2, '', f'ERROR: {self.refusal("old_sale", "15.0", "15.0.1.0.0")}\n'))

    def guard_config(self):
        spec = importlib.util.spec_from_file_location('oasis_series_guard_config', READER)
        config = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(config)
        return config

    def test_a_manifest_of_the_configured_series_is_not_parsed(self):
        """The fast path: the version string is read with a narrow pattern, and only a series-style
        version of another series (or a manifest the pattern cannot tell) is parsed with literal_eval."""
        config = self.guard_config()
        parsed = []
        real = config.ast.literal_eval

        def literal_eval(text):
            parsed.append(text)
            return real(text)
        self.module('addons', 'plain', '1.0')
        (self.root / 'addons/double_quoted/__manifest__.py').parent.mkdir()
        (self.root / 'addons/double_quoted/__manifest__.py').write_text(
            '# -*- coding: utf-8 -*-\n{\n    "name": "Double",\n    "version" : "19.0.2.0.0",\n    "data": [],\n}\n')
        with unittest.mock.patch.object(config.ast, 'literal_eval', literal_eval):
            values = config.load(self.root)
            self.assertEqual(parsed, [])
            self.assertEqual(config.manifest_series(self.root / 'addons/shop_sale/__manifest__.py', '19.0'),
                             ('19.0', '19.0.1.0.0'))
            self.assertEqual(parsed, [])
            # Another series is confirmed by literal_eval, and refused as before.
            old = self.module('addons', 'old_sale', '15.0.1.0.0')
            with self.assertRaises(config.InvalidConfig) as refused:
                config.load(self.root)
            self.assertEqual(str(refused.exception), self.refusal('old_sale', '15.0', '15.0.1.0.0'))
            self.assertEqual(parsed, [old.read_text()])
            old.unlink()
            # A pattern that cannot tell (the key twice, here once in a comment; a value that is not one
            # plain string) falls back to literal_eval, which decides as before.
            for name, text, refused_version in (
                    ('commented', "{\n    # 'version': '19.0.1.0.0',\n    'version': '15.0.1.0.0',\n}\n", '15.0.1.0.0'),
                    ('prefixed', "{'version': u'15.0.1.0.0'}\n", '15.0.1.0.0'),
                    ('nested', "{'name': 'x', 'other': {'version': '15.0.1.0.0'}}\n", None)):
                with self.subTest(name=name):
                    parsed.clear()
                    path = self.root / 'addons' / name / '__manifest__.py'
                    path.parent.mkdir()
                    path.write_text(text)
                    if refused_version is None:
                        self.assertEqual(config.load(self.root)['ODOO_VERSION'], '19.0')
                    else:
                        with self.assertRaises(config.InvalidConfig) as refused:
                            config.load(self.root)
                        self.assertEqual(str(refused.exception), self.refusal(name, '15.0', refused_version))
                    self.assertEqual(parsed, [text])
                    path.unlink()
                    path.parent.rmdir()
        self.assertEqual(values['ODOO_VERSION'], '19.0')

    def test_a_manifest_with_an_unrelated_syntax_error_and_the_right_series_loads(self):
        broken = self.root / 'addons/half_written/__manifest__.py'
        broken.parent.mkdir()
        broken.write_text("{\n    'name': 'Half written',\n    'version': '19.0.1.0.0',\n    'depends': ['base'\n")
        result = self.reader()
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertIn('ODOO_VERSION=19.0\n', result.stdout)
        # With another series it cannot be confirmed, so it is ignored as before (not refused).
        broken.write_text(broken.read_text().replace('19.0.1.0.0', '15.0.1.0.0'))
        result = self.reader()
        self.assertEqual((result.returncode, result.stderr), (0, ''))

    def test_a_supported_series_is_told_to_add_its_section(self):
        # 15.0 is supported (tools/odoo_versions.py): the fix points to the series model (v0.15.0 S3).
        config = self.guard_config()
        self.module('addons', 'old_sale', '15.0.1.0.0')
        values = config.load(self.root, series_guard=False)
        mismatch = config.series_mismatch(values)
        self.assertEqual((mismatch['module'], mismatch['series'], mismatch['version']),
                         ('old_sale', '15.0', '15.0.1.0.0'))
        fix = ('run oasis in a checkout of an Odoo 19.0 branch, or set the version of old_sale to 19.0.x.y.z '
               'if it is an Odoo 19.0 module; for Odoo 15.0 here, run oasis setup to add a [series."15.0"] section to ')
        self.assertEqual(config.series_fix(mismatch, '19.0', values), fix + str(self.root / 'oasis-workspace.toml'))
        # Without the assignments (no workspace path known) the file is named by its name.
        self.assertEqual(config.series_fix(mismatch, '19.0'), fix + 'oasis-workspace.toml')


if __name__ == '__main__':
    unittest.main()
