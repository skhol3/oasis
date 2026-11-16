"""The Gentle Shell (Pi) layer: package manifest and its node:test suite."""
import json
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
PI_TESTS = sorted((ROOT / 'pi/tests').glob('*.test.ts'))


class PiLayerTests(unittest.TestCase):
    def test_manifest_declares_only_existing_extensions(self):
        manifest = json.loads((ROOT / 'package.json').read_text())
        self.assertIn('pi-package', manifest['keywords'])
        self.assertEqual(manifest['pi'], {'extensions': ['./pi/extensions/odoo19.ts']})
        self.assertTrue((ROOT / 'pi/extensions/odoo19.ts').is_file())

    @unittest.skipUnless(shutil.which('node') and PI_TESTS, 'node or pi tests unavailable')
    def test_node_suite(self):
        result = subprocess.run(['node', '--test', *map(str, PI_TESTS)], cwd=ROOT,
                                capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stdout[-4000:] + result.stderr[-2000:])


if __name__ == '__main__':
    unittest.main()
