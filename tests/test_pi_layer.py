"""The Gentle Shell (Pi) layer: package manifest and its node:test suite."""
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
PI_TESTS = sorted((ROOT / 'pi/tests').glob('*.test.ts'))


class PiLayerTests(unittest.TestCase):
    def test_manifest_declares_only_existing_extensions(self):
        manifest = json.loads((ROOT / 'package.json').read_text())
        self.assertIn('pi-package', manifest['keywords'])
        self.assertEqual(manifest['pi'], {'extensions': ['./pi/extensions/oasis.ts']})
        self.assertTrue((ROOT / 'pi/extensions/oasis.ts').is_file())
        self.assertFalse((ROOT / 'pi/extensions/odoo19.ts').exists())

    def test_test_summary_reads_only_the_project_log_locations(self):
        # oasis_test_summary hands the checkout's tools/config.py values and the real file system to
        # lib/tools.ts formatBackgroundRun, which decides (behavior in pi/tests/run-logs.test.ts).
        source = (ROOT / 'pi/extensions/oasis.ts').read_text()
        [summary] = re.findall(r'name: "oasis_test_summary",.*?\n  \}\);', source, re.S)
        summary = ' '.join(summary.split())
        self.assertIn('const root = await requireRoot(ctx.cwd);', summary)
        self.assertIn('const { config, error } = await profileConfig(root);', summary)
        self.assertIn('formatBackgroundRun(params.module, params.output, config, '
                      '{ realpath: realpathSync, readLog }, options, MAX_LINES)', summary)
        self.assertIn('import { existsSync, readFileSync, realpathSync } from "node:fs";', source)

    def test_extension_names_its_prompt_section_and_status_message_oasis(self):
        source = (ROOT / 'pi/extensions/oasis.ts').read_text()
        self.assertIn('export default function oasisLayer(pi: ExtensionAPI)', source)
        self.assertIn('sections.oasis = context;', source)
        self.assertIn('`${event.systemPrompt}\\n\\n<oasis>\\n${context}\\n</oasis>`', source)
        self.assertIn('customType: "oasis-status"', source)
        for legacy in ('sections.odoo19', '<odoo19>', '"odoo19-status"', 'odoo19Layer'):
            self.assertNotIn(legacy, source)
        # The aliases stay (S6): /odoo19 and the inactive odoo19_* tools.
        self.assertIn('pi.registerCommand("odoo19", ', source)
        self.assertIn('const alias = aliasOf(tool.name);', source)

    def test_agent_overlay_template_lists_only_registered_tools(self):
        overlay = json.loads((ROOT / 'pi/agent-overlays/oasis.json').read_text())
        tools = ['oasis_test_module', 'oasis_test_summary', 'oasis_find_module', 'oasis_model_info',
                 'oasis_view_info', 'oasis_xmlid_info', 'oasis_module_info',
                 'oasis_module_status', 'oasis_lint_module', 'oasis_check_environment']
        # The worker also updates modules; verify stays read-only, so it does not get that tool.
        worker = tools[:2] + ['oasis_update_module'] + tools[2:]
        self.assertEqual(overlay, {'gentle-ai-worker': {'add': worker},
                                   'gentle-ai-verify': {'add': tools}})
        for agent, entry in overlay.items():
            self.assertLessEqual(set(entry), {'add', 'remove'}, agent)
            for key, names in entry.items():
                self.assertIsInstance(names, list, f'{agent}.{key}')
                self.assertTrue(all(isinstance(name, str) for name in names), f'{agent}.{key}')
        source = (ROOT / 'pi/extensions/oasis.ts').read_text()
        registered = set(re.findall(r'\bname:\s*"(oasis_[A-Za-z0-9_]+)"', source))
        listed = {name for entry in overlay.values() for names in entry.values() for name in names}
        self.assertTrue(listed)
        self.assertLessEqual(listed, registered, 'overlay names a tool the extension does not register')
        # Active-capable: the layer activates only the names of its activation table, never the
        # inactive odoo19_* aliases.
        activation = (ROOT / 'pi/lib/activation.ts').read_text()
        [table] = re.findall(r'OASIS_TOOLS: readonly string\[\] = \[(.*?)\];', activation, re.S)
        active_capable = set(re.findall(r'"([A-Za-z0-9_]+)"', table))
        self.assertEqual(active_capable, registered)
        self.assertLessEqual(listed, active_capable, 'overlay names a tool the layer never activates')
        self.assertIn('registerWithAlias(', source)
        self.assertEqual(len(re.findall(r'\bregisterWithAlias\(\{', source)), len(registered))

    def test_action_panel_wiring(self):
        # The panel's decisions are tested with fakes in pi/tests/panel.test.ts (and menu.test.ts); the
        # extension only adapts Pi to them, which loads only inside Pi (S6).
        source = (ROOT / 'pi/extensions/oasis.ts').read_text()
        start = source.index('  // The action panel (alt+o or OASIS_MENU_KEY, and /oasis menu)')
        panel = source[start:source.index('  const COMMAND_DESCRIPTION =', start)]
        # The whole panel block: the adapter, menu() and the shortcut with its handler and notice.
        for part in ('const openPanel = actionPanel({', 'function menu(ctx: ExtensionContext): Promise<void> {',
                     'pi.registerShortcut(', 'handler: (ctx) => menu(ctx),', 'ctx.ui.notify(`oasis: ${shortcut.error}`'):
            self.assertIn(part, panel)
        # Results are custom entries: shown to the user, never sent to the model.
        self.assertNotIn('sendMessage', panel)
        self.assertNotIn('sendUserMessage', panel)
        flat = ' '.join(panel.split())
        self.assertIn('pi.registerEntryRenderer(MENU_ENTRY, renderMenuEntry);', flat)
        self.assertIn('appendEntry: (entry) => pi.appendEntry(MENU_ENTRY, entry),', flat)
        # The catalog comes from the core; argv runs as given, without a shell, in the directory the panel names.
        self.assertIn('catalogArgv: (root) => ["python3", "-B", OASIS, "--project", root, "menu", "--catalog"],', flat)
        self.assertIn('exec: (argv, cwd, purpose) => pi.exec(argv[0], argv.slice(1), '
                      '{ cwd, timeout: EXEC_TIMEOUTS[purpose] }),', flat)
        self.assertIn('new MenuPanel(catalog, header, tui, theme, keybindings, done)', flat)
        # S6: the header's server state comes from runtime_state; the live log reads only the end of server.log.
        self.assertIn('serverState: (root) => serverState(root),', flat)
        self.assertIn('new LogPanel(title, () => readTail(path), tui, theme, keybindings, () => done()),', flat)
        self.assertIn('overlay: true,', flat)
        self.assertIn('mode: ctx.mode, cwd: ctx.cwd,', flat)
        # alt+o unless OASIS_MENU_KEY says otherwise, and /oasis menu; no agent tool opens the panel.
        self.assertIn('const shortcut = menuShortcut(process.env.OASIS_MENU_KEY);', flat)
        self.assertIn('menu: (ctx) => menu(ctx),', source)
        tools = re.findall(r'registerWithAlias\(\{.*?\n  \}\);', source, re.S)
        self.assertTrue(tools)
        self.assertFalse([tool for tool in tools if 'menu(' in tool or 'openPanel' in tool])
        # The overlay is the layer's own component on the public Pi API; the logic has no Pi imports.
        panel_ui = (ROOT / 'pi/ui/menu-panel.ts').read_text()
        imports = set(re.findall(r'^import .*? from "([^"]+)";$', panel_ui, re.M | re.S))
        self.assertEqual(imports, {'@earendil-works/pi-coding-agent', '@earendil-works/pi-tui', '../lib/menu.ts'})
        for name, allowed in (('menu.ts', {'./output.ts', './tools.ts'}),
                              ('panel.ts', {'./heartbeat.ts', './menu.ts', './tools.ts'})):
            lib = (ROOT / 'pi/lib' / name).read_text()
            self.assertEqual(set(re.findall(r' from "([^"]+)";', lib)), allowed, name)

    def test_node_catalog_fixture_is_the_core_catalog(self):
        # pi/tests/menu.test.ts reads a copy of `oasis menu --catalog`; it must stay the core's output.
        if str(ROOT / 'tests') not in sys.path:
            sys.path.insert(0, str(ROOT / 'tests'))
        import test_menu

        class Catalog(test_menu.MenuFixture):
            def runTest(self):
                pass

        fixture = Catalog()
        fixture.setUp()
        try:
            result = fixture.oasis('menu', '--catalog')
            project = str(fixture.root.resolve())
        finally:
            fixture.doCleanups()
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        core = json.loads(result.stdout.replace(project, '/work/a project')
                          .replace(str((ROOT / 'oasis').resolve()), '/opt/oasis/oasis'))
        self.assertEqual(json.loads((ROOT / 'pi/tests/fixtures/catalog.json').read_text()), core)

    @unittest.skipUnless(shutil.which('node') and PI_TESTS, 'node or pi tests unavailable')
    def test_node_suite(self):
        result = subprocess.run(['node', '--test', *map(str, PI_TESTS)], cwd=ROOT,
                                capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stdout[-4000:] + result.stderr[-2000:])


if __name__ == '__main__':
    unittest.main()
