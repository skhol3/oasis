"""tools/audit_dependencies.py runs with the project environment's Python, 3.7 and later (v0.16.0 S4.3).

`importlib.metadata.packages_distributions` and `sys.stdlib_module_names` exist only from Python
3.10, and `importlib.metadata` only from 3.8: without them the audit computes the top-level module
to distribution mapping from the installed distributions (top_level.txt, else RECORD and the other
file lists) and the standard library names from the interpreter's library directories. The same
synthetic project and site directory give the same output on the current Python, on a 3.9 and a 3.8
interpreter when `uv python find` has one, and with each fallback forced on the current Python.
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

HELPER = Path(__file__).resolve().parents[1] / 'tools' / 'audit_dependencies.py'

COFFEE = '''import os
import json.decoder
import sqlite3
from odoo import models
from odoo.addons.roast import helpers
from . import bag
import fakedeclared
import fakeinferred.sub
from fakeegg import thing
import dateutil.parser
import notinstalled_xyz
'''

EXPECTED = '''scope=coffee
declared_distributions=2
external_imports=5
import=dateutil distribution=python-dateutil status=declared installed=missing occurrences=1
  addons/coffee/__init__.py:10
import=fakedeclared distribution=Fake-Declared status=declared installed=1.2 occurrences=1
  addons/coffee/__init__.py:7
import=fakeegg distribution=Fake-Egg status=undeclared installed=2.0 occurrences=1
  addons/coffee/__init__.py:9
import=fakeinferred distribution=fake_inferred status=undeclared installed=0.3 occurrences=1
  addons/coffee/__init__.py:8
import=notinstalled_xyz distribution=unmapped status=undeclared installed=unknown occurrences=1
  addons/coffee/__init__.py:11
undeclared_dependencies=3
'''

# Run main() with the 3.9 shape forced on the current Python: no packages_distributions and no
# sys.stdlib_module_names, as an interpreter older than 3.10 has.
FORCE_39 = '''import importlib.metadata, sys
del importlib.metadata.packages_distributions
del sys.stdlib_module_names
sys.path.insert(0, sys.argv[1])
sys.argv = [sys.argv[2], *sys.argv[3:]]
import audit_dependencies
raise SystemExit(audit_dependencies.main())
'''

# Run main() with the 3.7 shape forced on the current Python: no importlib.metadata at all.
FORCE_37 = '''import sys
sys.modules['importlib.metadata'] = None
del sys.stdlib_module_names
sys.path.insert(0, sys.argv[1])
sys.argv = [sys.argv[2], *sys.argv[3:]]
import audit_dependencies
assert audit_dependencies.metadata is None
raise SystemExit(audit_dependencies.main())
'''


def find_python(minor):
    """A Python `minor` interpreter from `uv python find`, or None when uv has none."""
    uv = shutil.which('uv')
    if not uv:
        return None
    env = {key: value for key, value in os.environ.items() if key not in ('VIRTUAL_ENV', 'UV_PYTHON')}
    with tempfile.TemporaryDirectory() as scratch:
        try:
            found = subprocess.run([uv, 'python', 'find', '--no-project', '--system', minor],
                                   text=True, capture_output=True, cwd=scratch, env=env, timeout=60)
        except (OSError, subprocess.TimeoutExpired):
            return None
    path = found.stdout.strip()
    if found.returncode or not path:
        return None
    check = subprocess.run([path, '-S', '-c', 'import sys; print("%d.%d" % sys.version_info[:2])'],
                           text=True, capture_output=True)
    return path if check.stdout.strip() == minor else None


def write_site(site):
    """Three synthetic distributions: one with top_level.txt, one with only RECORD, one egg-info."""
    declared = site / 'fake_declared-1.2.dist-info'
    declared.mkdir(parents=True)
    (declared / 'METADATA').write_text('Metadata-Version: 2.1\nName: Fake-Declared\nVersion: 1.2\n')
    (declared / 'top_level.txt').write_text('fakedeclared\n')
    inferred = site / 'fake_inferred-0.3.dist-info'
    inferred.mkdir()
    (inferred / 'METADATA').write_text('Metadata-Version: 2.1\nName: fake_inferred\nVersion: 0.3\n')
    (inferred / 'RECORD').write_text('fakeinferred/__init__.py,,\nfakeinferred/sub.py,,\n'
                                     'fake_inferred-0.3.dist-info/METADATA,,\n'
                                     'fake_inferred-0.3.dist-info/RECORD,,\n../../bin/fake-tool,,\n')
    egg = site / 'Fake_Egg-2.0-py3.9.egg-info'
    egg.mkdir()
    (egg / 'PKG-INFO').write_text('Metadata-Version: 1.1\nName: Fake-Egg\nVersion: 2.0\n')
    (egg / 'top_level.txt').write_text('fakeegg\n')
    # The installed files: Python 3.12+ leaves RECORD entries that do not exist out of `files`.
    for module in ('fakedeclared/__init__.py', 'fakeinferred/__init__.py', 'fakeinferred/sub.py',
                   'fakeegg/__init__.py'):
        (site / module).parent.mkdir(exist_ok=True)
        (site / module).write_text('')


class AuditDependenciesTests(unittest.TestCase):
    def setUp(self):
        self.scratch = Path(tempfile.mkdtemp(prefix='oasis-audit-'))
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)
        self.project = self.scratch / 'project'
        addons = self.project / 'addons'
        for name in ('coffee', 'roast'):
            (addons / name).mkdir(parents=True)
            (addons / name / '__manifest__.py').write_text("{'name': '%s'}\n" % name)
        (addons / 'coffee/__init__.py').write_text(COFFEE)
        requirements = self.project / 'dev/requirements'
        requirements.mkdir(parents=True)
        (requirements / 'dev.in').write_text('fake-declared>=1.0\npython-dateutil\n')
        self.site = self.scratch / 'site'
        write_site(self.site)
        self.arguments = ['--project-root', str(self.project), '--requirements-dir', str(requirements),
                          '--addon-root', str(addons), 'coffee']
        # -S: no site-packages, so only the synthetic site directory (PYTHONPATH) is installed.
        self.env = {'PATH': os.environ.get('PATH', '/usr/bin:/bin'), 'PYTHONPATH': str(self.site),
                    'PYTHONDONTWRITEBYTECODE': '1', 'LC_ALL': 'C.UTF-8'}

    def run_helper(self, python, *prefix):
        result = subprocess.run([python, '-B', '-S', *prefix, *self.arguments], text=True,
                                capture_output=True, cwd=self.scratch, env=self.env)
        return result.returncode, result.stdout, result.stderr

    def test_current_python_maps_imports_to_distributions(self):
        self.assertEqual(self.run_helper(sys.executable, str(HELPER)), (1, EXPECTED, ''))

    def test_python_39_and_38_give_the_same_output(self):
        for minor in ('3.9', '3.8'):
            with self.subTest(python=minor):
                python = find_python(minor)
                if python is None:
                    self.skipTest(f'uv python find {minor} found no interpreter')
                self.assertEqual(self.run_helper(python, str(HELPER)), (1, EXPECTED, ''))

    def test_forced_fallback_without_packages_distributions_gives_the_same_output(self):
        self.assertEqual(self.run_helper(sys.executable, '-c', FORCE_39, str(HELPER.parent), str(HELPER)),
                         (1, EXPECTED, ''))

    def test_forced_fallback_without_importlib_metadata_gives_the_same_output(self):
        self.assertEqual(self.run_helper(sys.executable, '-c', FORCE_37, str(HELPER.parent), str(HELPER)),
                         (1, EXPECTED, ''))


class FallbackUnitTests(unittest.TestCase):
    """The fallback functions themselves, on the current Python."""

    def setUp(self):
        spec = importlib.util.spec_from_file_location('audit_dependencies_under_test', HELPER)
        self.audit = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.audit)
        self.site = Path(tempfile.mkdtemp(prefix='oasis-audit-site-'))
        self.addCleanup(shutil.rmtree, self.site, ignore_errors=True)
        write_site(self.site)

    def test_fallback_mapping_matches_packages_distributions(self):
        import importlib.metadata
        distributions = list(importlib.metadata.distributions(path=[str(self.site)]))
        mapping = self.audit.top_level_mapping(distributions)
        self.assertEqual(mapping, {'fakedeclared': ['Fake-Declared'], 'fakeinferred': ['fake_inferred'],
                                   'fakeegg': ['Fake-Egg']})
        # The same rules as importlib.metadata.packages_distributions over every installed distribution.
        self.assertEqual(self.audit.top_level_mapping(importlib.metadata.distributions()),
                         importlib.metadata.packages_distributions())

    def test_path_scan_reads_names_versions_and_files_without_importlib_metadata(self):
        scanned = self.audit.scan_distributions([str(self.site), str(self.site / 'absent')])
        self.assertEqual(self.audit.top_level_mapping(scanned),
                         {'fakedeclared': ['Fake-Declared'], 'fakeinferred': ['fake_inferred'],
                          'fakeegg': ['Fake-Egg']})
        self.assertEqual(sorted((dist.metadata['Name'], dist.version) for dist in scanned),
                         [('Fake-Declared', '1.2'), ('Fake-Egg', '2.0'), ('fake_inferred', '0.3')])

    def test_stdlib_fallback_covers_the_importable_standard_library(self):
        names = self.audit.scan_stdlib_module_names()
        for name in ('os', 'json', 'sqlite3', 'datetime', 'sys', 'collections', '_thread', 'ssl'):
            self.assertIn(name, names)
        importable = {name for name in sys.stdlib_module_names if importlib.util.find_spec(name) is not None}
        self.assertEqual(importable - names, set())
        for name in ('fakedeclared', 'fakeinferred', 'fakeegg', 'pip', 'site-packages'):
            self.assertNotIn(name, names)


if __name__ == '__main__':
    unittest.main()
