"""Where `oasis setup` puts a new workspace (v0.16.0 S4.11): the project folder above a clone in
<project>/code/<repo> or <project>/codigo/<repo>, else the clone itself.

The fixture is tests/test_setup.py's (scratch directories, git with an empty configuration, a scratch machine
file and a fake uv); the clone lives in work/<project>/<folder>/shop.
"""
import oasis_test_env  # noqa: F401  first: XDG_CONFIG_HOME is scratch (tests/oasis_test_env.py)
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

import test_setup
from test_setup import DRY_RUN, MANIFEST, READER, WORKSPACE
from test_setup_prompt import on_terminal

CHECKOUT_FILE = ('# Written by oasis setup: the database namespace of this worktree; its directory name {name} gives '
                 '{raw}, over 20 characters.\n[tooling]\ncheckout_slug = \'{slug}\'\n')


@unittest.skipUnless(shutil.which('git'), 'git is required')
class ProjectFolderTests(unittest.TestCase):
    setUp_fixture = test_setup.SetupTests.setUp
    git = test_setup.SetupTests.git
    odoo_source = test_setup.SetupTests.odoo_source
    module = test_setup.SetupTests.module
    setup_cmd = test_setup.SetupTests.setup_cmd
    tree = test_setup.SetupTests.tree
    compose_name = test_setup.SetupTests.compose_name
    plan = test_setup.SetupTests.plan
    port_of = test_setup.SetupTests.port_of

    def setUp(self):
        self.setUp_fixture()

    def clone(self, project, folder):
        """A clone of the shop checkout at work/<project>/<folder>/shop."""
        self.project = self.scratch / 'work' / project
        self.checkout = self.project / folder / 'shop'
        self.module('shop_sale', MANIFEST)
        self.git(self.checkout, 'init', '-q')
        return self.project

    def json_plan(self, *args):
        result = self.setup_cmd('--plan', '--json', '--community', str(self.source), '--no-enterprise', *args)
        self.assertEqual((result.returncode, result.stderr), (0, ''), result.stdout)
        return json.loads(result.stdout)

    def question(self, folder, answer, origin):
        return {'id': 'workspace', 'text': f'Workspace directory of {self.checkout}: the project folder {self.project} '
                                           'or the clone',
                'options': [{'value': str(self.project), 'label': f'the project folder above {folder}/'},
                            {'value': str(self.checkout), 'label': 'the clone'}],
                'recommended': str(self.project), 'flag': '--workspace <dir>', 'answer': answer, 'origin': origin}

    def test_a_clone_under_code_or_codigo_proposes_the_project_folder(self):
        for folder in ('code', 'codigo'):
            with self.subTest(folder=folder):
                project = self.clone(f'shop-{folder}', folder)
                before = self.tree()
                plan = self.json_plan()
                self.assertEqual(plan['inferred']['workspace'], {'value': str(project), 'origin': 'new'})
                self.assertEqual(plan['questions'][0], self.question(folder, str(project), 'recommended (no terminal)'))
                self.assertTrue(plan['ready_to_apply'])
                result = self.setup_cmd('--community', str(self.source), '--no-enterprise')
                port = self.port_of(result.stdout)
                expected = self.plan(port, base='', directory=project).replace(
                    f'workspace: {project} (new)\n',
                    f'workspace: {project} (new; the project folder above {folder}/; --workspace {self.checkout} '
                    'keeps it in the clone)\n')
                self.assertEqual((result.returncode, result.stdout, result.stderr), (0, expected + DRY_RUN, ''))
                self.assertEqual(self.tree(), before)
                # --workspace <clone>, or the answer, keeps today's default: the workspace in the clone.
                for arguments in (('--workspace', str(self.checkout)), ('--answer', f'workspace={self.checkout}')):
                    result = self.setup_cmd('--community', str(self.source), '--no-enterprise', *arguments)
                    port = self.port_of(result.stdout)
                    self.assertEqual((result.returncode, result.stdout, result.stderr),
                                     (0, self.plan(port) + DRY_RUN, ''))
                    self.assertNotIn('workspace', [item['id'] for item in self.json_plan(*arguments)['questions']])
                # Applied: the workspace file in the project folder, nothing excluded in the clone.
                result = self.setup_cmd('--apply', '--community', str(self.source), '--no-enterprise')
                self.assertEqual((result.returncode, result.stderr), (0, ''), result.stdout)
                self.assertEqual((project / 'oasis-workspace.toml').read_text(), WORKSPACE.format(base=''))
                self.assertFalse((self.checkout / 'oasis-workspace.toml').exists())
                self.assertNotIn('oasis', (self.checkout / '.git/info/exclude').read_text())
                self.machine.unlink()

    def test_elsewhere_the_clone_stays_the_default(self):
        cases = (('src', None), ('code', '.git'), ('code', 'odoo-bin'), ('code', 'oasis-checkout.toml'))
        for index, (folder, marker) in enumerate(cases):
            with self.subTest(folder=folder, marker=marker):
                project = self.clone(f'other-{index}', folder)
                if marker == '.git':
                    (project / marker).mkdir()
                elif marker:
                    (project / marker).write_text('')
                plan = self.json_plan()
                self.assertEqual(plan['inferred']['workspace'], {'value': str(self.checkout), 'origin': 'new'})
                self.assertNotIn('workspace', [item['id'] for item in plan['questions']])

    def test_on_a_terminal_enter_takes_the_project_folder_and_the_clone_can_be_typed(self):
        project = self.clone('shop-project', 'code')
        prompt = (f'Workspace directory: Enter puts it in {project} (the project folder above code/), or type '
                  f'{self.checkout} to keep it in the clone: ')
        arguments = ['--project', str(self.checkout), 'setup', '--community', str(self.source), '--no-enterprise',
                     '--python', '3.12', '--answer', 'development=add']
        code, stdout, written = on_terminal(arguments, self.env, self.scratch, [(prompt, b'\n')])
        self.assertEqual(code, 0, written)
        self.assertIn(f'workspace: {project} (new; the project folder above code/; ', stdout)
        retry = f'Answer {project} or {self.checkout}, or Enter for {project}.\n'
        code, stdout, written = on_terminal(arguments, self.env, self.scratch,
                                            [(prompt, b'/elsewhere\n'), (retry + prompt, f'{self.checkout}\n'.encode())])
        self.assertEqual(code, 0, written)
        self.assertIn(f'workspace: {self.checkout} (new)\n', stdout)
        self.assertIn(f'create {self.checkout / ".oasis/config/odoo.conf"}', stdout)



@unittest.skipUnless(shutil.which('git'), 'git is required')
class CheckoutSlugTests(unittest.TestCase):
    """A linked worktree whose directory name gives a slug over 20 characters (v0.16.0 S4)."""
    setUp_fixture = test_setup.SetupTests.setUp
    git = test_setup.SetupTests.git
    odoo_source = test_setup.SetupTests.odoo_source
    module = test_setup.SetupTests.module
    setup_cmd = test_setup.SetupTests.setup_cmd
    tree = test_setup.SetupTests.tree
    existing_workspace = test_setup.SetupTests.existing_workspace
    assert_refused = test_setup.SetupTests.assert_refused

    def setUp(self):
        self.setUp_fixture()
        self.existing_workspace()
        self.main = self.checkout
        self.checkout = self.scratch / 'work' / 'shop-invoice-reconciliation-rework'
        self.git(self.main, 'worktree', 'add', '-q', '-b', 'feature', str(self.checkout))
        self.file = self.checkout / 'oasis-checkout.toml'

    def slug(self):
        result = subprocess.run([sys.executable, '-B', str(READER), str(self.checkout)], capture_output=True,
                                text=True, env=self.env)
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        return [line for line in result.stdout.splitlines() if line.startswith('CHECKOUT_SLUG=')]

    def test_setup_proposes_a_shortened_checkout_slug(self):
        line = (f'create {self.file}: checkout_slug invoice_reconciliati (the worktree directory name '
                f'{self.checkout.name} gives invoice_reconciliation_rework, 29 characters; a slug has at most 20)\n')
        before = self.tree()
        result = self.setup_cmd()
        self.assertEqual((result.returncode, result.stderr), (0, ''), result.stdout)
        self.assertIn(line, result.stdout)
        self.assertEqual(self.tree(), before)
        result = self.setup_cmd('--apply')
        self.assertEqual((result.returncode, result.stderr), (0, ''), result.stdout)
        self.assertEqual(self.file.read_text(), CHECKOUT_FILE.format(
            name=self.checkout.name, raw='invoice_reconciliation_rework', slug='invoice_reconciliati'))
        self.assertEqual(self.slug(), ['CHECKOUT_SLUG=invoice_reconciliati'])

    def test_a_slug_another_worktree_uses_gets_a_number_and_a_checkout_file_is_extended(self):
        other = self.scratch / 'work' / 'shop-other'
        self.git(self.main, 'worktree', 'add', '-q', '-b', 'other', str(other))
        (other / 'oasis-checkout.toml').write_text("[tooling]\ncheckout_slug = 'invoice_reconciliati'\n")
        self.file.write_text("odoo_version = '19.0'\n")
        result = self.setup_cmd('--apply')
        self.assertEqual((result.returncode, result.stderr), (0, ''), result.stdout)
        self.assertIn(f'add [tooling] checkout_slug invoice_reconcilia_2 to {self.file} (the worktree directory name ',
                      result.stdout)
        self.assertEqual(self.file.read_text(), "odoo_version = '19.0'\n\n" + CHECKOUT_FILE.format(
            name=self.checkout.name, raw='invoice_reconciliation_rework', slug='invoice_reconcilia_2'))
        self.assertEqual(self.slug(), ['CHECKOUT_SLUG=invoice_reconcilia_2'])

    def worktree(self, name):
        """A linked worktree of the main checkout at work/<name>, as the checkout under test."""
        self.checkout = self.scratch / 'work' / name
        self.git(self.main, 'worktree', 'add', '-q', '-b', f'branch-{len(name)}', str(self.checkout))
        return self.checkout

    def test_only_a_slug_over_20_characters_is_shortened(self):
        # A one-character slug and one starting with a digit are valid slugs (config.SLUG): nothing is proposed.
        for name, slug in (('shop-x', 'x'), ('shop-1fix', '1fix')):
            with self.subTest(name=name):
                self.worktree(name)
                result = self.setup_cmd()
                self.assertEqual((result.returncode, result.stderr), (0, ''), result.stdout)
                self.assertNotIn('checkout_slug', result.stdout)
                self.assertNotIn('over 20 characters', result.stdout)
                self.assertEqual(self.slug(), [f'CHECKOUT_SLUG={slug}'])
        # A name that gives no slug at all is refused at plan time with the derived-slug message, never proposed.
        checkout = self.worktree('shop-\u00f1\u00f1')
        before = self.tree()
        self.assert_refused(self.setup_cmd(), (
            f'Cannot derive a checkout slug from the worktree directory name {checkout.name}: it gives nothing, and a '
            'slug is 1 to 20 lowercase letters, digits or underscores, starting with a letter or digit; set '
            f'[tooling].checkout_slug in {checkout / "oasis-checkout.toml"}.'), before)
        self.assertNotIn('over 20 characters', self.setup_cmd('--plan', '--json').stdout)

    def test_a_checkout_file_with_its_own_tooling_table_is_never_edited(self):
        self.file.write_text("[tooling]\nenvironment = 'default'\n")
        before = self.tree()
        self.assert_refused(self.setup_cmd(), (
            f'The worktree directory name {self.checkout.name} gives the checkout slug invoice_reconciliation_rework '
            f'(29 characters; a slug has at most 20) and {self.file} has a [tooling] table, which setup never edits: '
            "add checkout_slug = 'invoice_reconciliati' to it, then run oasis setup again."), before)



@unittest.skipUnless(shutil.which('git'), 'git is required')
class MoveWorkspaceTests(unittest.TestCase):
    """A workspace created in the clone, moved to the project folder with --workspace (v0.16.0 S4.11)."""
    setUp_fixture = test_setup.SetupTests.setUp
    git = test_setup.SetupTests.git
    odoo_source = test_setup.SetupTests.odoo_source
    module = test_setup.SetupTests.module
    setup_cmd = test_setup.SetupTests.setup_cmd
    tree = test_setup.SetupTests.tree
    assert_refused = test_setup.SetupTests.assert_refused
    clone = ProjectFolderTests.clone

    def setUp(self):
        self.setUp_fixture()
        self.clone('shop-project', 'code')
        result = self.setup_cmd('--apply', '--workspace', str(self.checkout), '--community', str(self.source),
                                '--no-enterprise')
        self.assertEqual((result.returncode, result.stderr), (0, ''), result.stdout)
        self.old = self.checkout / 'oasis-workspace.toml'
        self.new = self.project / 'oasis-workspace.toml'
        self.exclude = self.checkout / '.git/info/exclude'
        self.log.unlink()

    def values(self):
        result = subprocess.run([sys.executable, '-B', str(READER), str(self.checkout)], capture_output=True,
                                text=True, env=self.env)
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        return dict(line.split('=', 1) for line in result.stdout.splitlines())

    def test_the_plan_moves_the_workspace_file_its_folder_and_the_exclude_entries(self):
        original = self.old.read_bytes()
        self.old.write_text(self.old.read_text().replace("logs = '.oasis/logs'", "logs = 'mylogs'"))
        before = self.tree()
        result = self.setup_cmd('--workspace', str(self.project))
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, (
            f'checkout: {self.checkout} (main)\n'
            f'workspace: {self.old} (existing; to move to {self.project})\n'
            f'move {self.old} to {self.new} (mode 0600), its relative paths rewritten: logs mylogs -> code/shop/mylogs\n'
            f'move {self.checkout / ".oasis"}/ to {self.project / ".oasis"}/\n'
            f'remove /oasis-workspace.toml and /.oasis/ from {self.exclude}\n' + DRY_RUN), ''))
        self.assertEqual(self.tree(), before)
        result = self.setup_cmd('--apply', '--workspace', str(self.project))
        self.assertEqual((result.returncode, result.stderr), (0, ''), result.stdout)
        self.assertIn(f'verified: {self.checkout} loads its configuration from {self.new}\n', result.stdout)
        self.assertEqual(self.new.read_bytes(), original.replace(b"logs = '.oasis/logs'", b"logs = 'code/shop/mylogs'"))
        self.assertEqual(self.new.stat().st_mode & 0o777, 0o600)
        self.assertFalse(self.old.exists())
        self.assertFalse((self.checkout / '.oasis').exists())
        self.assertNotIn('oasis', self.exclude.read_text())
        values = self.values()
        self.assertEqual(values['ODOO_CONFIG'], str(self.project / '.oasis/config/odoo.conf'))
        self.assertEqual(values['LOGS_DIR'], str(self.checkout / 'mylogs'))
        self.assertTrue((self.project / '.oasis/config/odoo.conf').is_file())
        # Moved: a second run plans nothing but the logs directory the rewritten path names.
        result = self.setup_cmd()
        self.assertEqual((result.returncode, result.stderr), (0, ''), result.stdout)
        self.assertIn(f'workspace: {self.new} (existing)\n', result.stdout)
        self.assertIn(f'kept the locks in {self.project / ".oasis/config/requirements"}: current\n', result.stdout)

    @unittest.skipIf(os.geteuid() == 0, 'root writes any file')
    def test_a_failed_move_undoes_every_change(self):
        self.exclude.chmod(0o444)
        self.addCleanup(self.exclude.chmod, 0o644)
        before = self.tree()
        result = self.setup_cmd('--apply', '--workspace', str(self.project))
        self.assertEqual((result.returncode, result.stderr),
                         (1, 'ERROR: Could not set up: Permission denied; every change was undone.\n'))
        self.assertTrue(result.stdout.endswith(f'remove /oasis-workspace.toml and /.oasis/ from {self.exclude}\n'))
        self.assertEqual(self.tree(), before)

    def test_a_path_through_the_layout_folder_is_rewritten_like_any_outside_path(self):
        # .oasis/../mylogs names <clone>/mylogs: normalized first, it is not in .oasis/, which moves along.
        self.old.write_text(self.old.read_text().replace("logs = '.oasis/logs'", "logs = '.oasis/../mylogs'"))
        result = self.setup_cmd('--workspace', str(self.project))
        self.assertEqual((result.returncode, result.stderr), (0, ''), result.stdout)
        self.assertIn(f'move {self.old} to {self.new} (mode 0600), its relative paths rewritten: logs .oasis/../mylogs '
                      '-> code/shop/mylogs\n', result.stdout)
        result = self.setup_cmd('--apply', '--workspace', str(self.project))
        self.assertEqual((result.returncode, result.stderr), (0, ''), result.stdout)
        self.assertIn("logs = 'code/shop/mylogs'\n", self.new.read_text())
        self.assertEqual(self.values()['LOGS_DIR'], str(self.checkout / 'mylogs'))

    def test_a_verification_failure_after_the_delete_brings_the_workspace_file_back(self):
        # config.load rejects the moved configuration (the series guard: a module of another series) once every
        # action ran, the delete of the clone's workspace file included: the rollback recreates it (its bytes and
        # mode 0600) and undoes the rest.
        self.module('shop_legacy', "{'name': 'Legacy', 'version': '15.0.1.0.0'}\n")
        original = self.old.read_bytes()
        self.assertEqual(self.old.stat().st_mode & 0o777, 0o600)
        before = self.tree()
        result = self.setup_cmd('--apply', '--workspace', str(self.project))
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertTrue(result.stderr.startswith('ERROR: Verification failed ('), result.stderr)
        self.assertIn('shop_legacy', result.stderr)
        self.assertTrue(result.stderr.endswith('; every change was undone.\n'), result.stderr)
        self.assertTrue(result.stdout.endswith(f'remove /oasis-workspace.toml and /.oasis/ from {self.exclude}\n'))
        self.assertEqual(self.tree(), before)
        self.assertEqual((self.old.read_bytes(), self.old.stat().st_mode & 0o777), (original, 0o600))
        self.assertFalse(self.new.exists())

    def test_a_move_that_cannot_be_made_is_refused(self):
        before = self.tree()
        self.assert_refused(self.setup_cmd('--workspace', str(self.checkout / 'shop_sale')),
                            f'Refusing --workspace {self.checkout / "shop_sale"}: it is not at or above the checkout '
                            f'{self.checkout}.', before)
        (self.project / '.oasis').mkdir()
        before = self.tree()
        self.assert_refused(self.setup_cmd('--workspace', str(self.project)),
                            f'Refusing to move {self.checkout / ".oasis"}/ to {self.project}: '
                            f'{self.project / ".oasis"} exists.', before)
        (self.project / '.oasis').rmdir()
        self.git(self.checkout, 'add', '-f', 'oasis-workspace.toml')
        before = self.tree()
        self.assert_refused(self.setup_cmd('--workspace', str(self.project)),
                            f'Refusing to move {self.old}: git tracks it; move it yourself.', before)



class DeleteGuardTests(unittest.TestCase):
    """The 'delete' change of a move (tools/setup.py Changes): it removes only the bytes the plan read, and its
    rollback ('recreate') brings them back with their mode."""

    def setUp(self):
        spec = importlib.util.spec_from_file_location('oasis_setup_changes', test_setup.ROOT / 'tools/setup.py')
        self.setup = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.setup)
        scratch = tempfile.TemporaryDirectory(prefix='oasis-delete-')
        self.addCleanup(scratch.cleanup)
        self.path = Path(scratch.name) / 'oasis-workspace.toml'
        self.path.write_bytes(b'workspace_version = 1\n')
        self.path.chmod(0o600)

    def test_a_file_changed_since_the_plan_is_refused_and_kept(self):
        changes = self.setup.Changes()
        with self.assertRaisesRegex(OSError, 'changed since the plan'):
            changes.apply(('delete', self.path, b'workspace_version = 2\n'))
        self.assertEqual(changes.rollback(), [])
        self.assertEqual((self.path.read_bytes(), self.path.stat().st_mode & 0o777), (b'workspace_version = 1\n', 0o600))

    def test_a_deleted_file_comes_back_with_its_bytes_and_mode(self):
        changes = self.setup.Changes()
        changes.apply(('delete', self.path, b'workspace_version = 1\n'))
        self.assertFalse(self.path.exists())
        self.assertEqual(changes.rollback(), [])
        self.assertEqual((self.path.read_bytes(), self.path.stat().st_mode & 0o777), (b'workspace_version = 1\n', 0o600))

if __name__ == '__main__':
    unittest.main()
