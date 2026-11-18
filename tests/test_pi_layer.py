"""The Gentle Shell (Pi) layer: package manifest and its node:test suite."""
import json
from pathlib import Path
import re
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

    def test_agent_overlay_template_lists_only_registered_tools(self):
        overlay = json.loads((ROOT / 'pi/agent-overlays/oasis.json').read_text())
        tools = ['odoo19_test_module', 'odoo19_find_module', 'odoo19_model_info',
                 'odoo19_module_status', 'odoo19_lint_module', 'odoo19_check_environment']
        self.assertEqual(overlay, {'gentle-ai-worker': {'add': tools},
                                   'gentle-ai-verify': {'add': tools}})
        for agent, entry in overlay.items():
            self.assertLessEqual(set(entry), {'add', 'remove'}, agent)
            for key, names in entry.items():
                self.assertIsInstance(names, list, f'{agent}.{key}')
                self.assertTrue(all(isinstance(name, str) for name in names), f'{agent}.{key}')
        source = (ROOT / 'pi/extensions/odoo19.ts').read_text()
        registered = set(re.findall(r'\bname:\s*"(odoo19_[A-Za-z0-9_]+)"', source))
        listed = {name for entry in overlay.values() for names in entry.values() for name in names}
        self.assertTrue(listed)
        self.assertLessEqual(listed, registered, 'overlay names a tool the extension does not register')

    @unittest.skipUnless(shutil.which('node') and PI_TESTS, 'node or pi tests unavailable')
    def test_node_suite(self):
        result = subprocess.run(['node', '--test', *map(str, PI_TESTS)], cwd=ROOT,
                                capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stdout[-4000:] + result.stderr[-2000:])


if __name__ == '__main__':
    unittest.main()
