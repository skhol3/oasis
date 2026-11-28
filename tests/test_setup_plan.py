"""`oasis setup --plan --json`, answers without a terminal and the problems the plan anticipates (v0.16.0 S3).

The fixture is tests/test_setup.py's: scratch directories, git with an empty configuration, a scratch machine
file and a fake uv. The problems of an Odoo 15.0 checkout use a fake ldconfig and pkg-config on PATH, so
nothing reads the real machine's libraries.
"""
import oasis_test_env  # noqa: F401  first: XDG_CONFIG_HOME is scratch (tests/oasis_test_env.py)
import json
from pathlib import Path
import shutil
import tempfile
import unittest

import test_setup
from test_setup import CREATE, DRY_RUN
from test_setup_prompt import on_terminal

OPEN_PLAN = ('nothing changed: answer the open questions above (docs/setup.md#questions-and-answers), then run '
             'with --apply to set up\n')
RELEASE_15 = "version_info = (15, 0, 0, 'final', 0, '')\n"
REQUIREMENTS_15 = "cryptography==2.6.1\npython-ldap==3.4.0 ; sys_platform != 'win32'\npsycopg2==2.8.6\n"
MANIFEST_15 = ("{'name': 'Shop Sale', 'version': '15.0.1.0.0', 'depends': ['sale'],\n"
               " 'external_dependencies': {'python': ['cryptography>=3.3.1', 'phonenumbers', 'json']}}\n")
# ldconfig -p of a machine with OpenLDAP 2.6 (no libldap_r), and of one with OpenLDAP 2.4.
LDCONFIG_26 = '\tlibldap.so.2 (libc6,x86-64) => /usr/lib/libldap.so.2\n'
LDCONFIG_24 = ('\tlibldap_r-2.4.so.2 (libc6,x86-64) => /usr/lib/libldap_r-2.4.so.2\n'
               '\tlibldap-2.4.so.2 (libc6,x86-64) => /usr/lib/libldap-2.4.so.2\n')
# The recommended answers of the environment questions of a new 15.0 workspace (v0.20.0 S1), as an agent relays them.
CREATE_15 = ('--answer', 'environment=create', '--answer', 'python=3.9')



def development_question(workspace, answer, origin):
    """The question development of a new workspace (v0.16.0 S6) as the JSON plan lists it."""
    return {'id': 'development',
            'text': f"create-database needs a [development] table in {workspace}: add one with administrator_login = "
                    "'admin' (its password: Odoo's default, or ODOO_ADMIN_PASSWORD of the env file)?",
            'options': [{'value': 'add', 'label': "add [development] with administrator_login = 'admin'"},
                        {'value': 'none', 'label': 'none: no [development] table (create-database then needs one '
                                                   'added by hand)'}],
            'recommended': 'add', 'flag': '--answer development=<add|none>', 'answer': answer, 'origin': origin}


class PlanJsonTests(unittest.TestCase):
    setUp = test_setup.SetupTests.setUp
    git = test_setup.SetupTests.git
    odoo_source = test_setup.SetupTests.odoo_source
    module = test_setup.SetupTests.module
    setup_cmd = test_setup.SetupTests.setup_cmd
    tree = test_setup.SetupTests.tree
    write_machine = test_setup.SetupTests.write_machine
    compose_name = test_setup.SetupTests.compose_name
    plan = test_setup.SetupTests.plan
    port_of = test_setup.SetupTests.port_of
    assert_refused = test_setup.SetupTests.assert_refused

    def json_plan(self, *args):
        result = self.setup_cmd('--plan', '--json', *args)
        self.assertEqual((result.returncode, result.stderr), (0, ''), result.stdout)
        self.assertEqual(result.stdout.count('\n'), 1)
        return json.loads(result.stdout)

    def answers(self, document):
        """An answers file outside the scratch tree that tree() compares."""
        directory = Path(tempfile.mkdtemp(prefix='oasis-answers-'))
        self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
        path = directory / 'answers.json'
        path.write_text(json.dumps(document))
        return path

    def test_the_json_plan_lists_the_inferred_values_the_changes_and_the_questions(self):
        before = self.tree()
        plan = self.json_plan('--community', str(self.source), '--no-enterprise')
        self.assertEqual(self.tree(), before)
        self.assertFalse(self.log.exists())
        environment = self.checkout / '.oasis/venv'
        port = plan['inferred']['db_port']['value']
        self.assertEqual({key: plan[key] for key in ('format', 'version', 'checkout', 'complete', 'open',
                                                     'ready_to_apply')},
                         {'format': 'oasis-setup-plan', 'version': 1, 'checkout': str(self.checkout),
                          'complete': True, 'open': ['environment', 'python'], 'ready_to_apply': False})
        self.assertEqual(plan['inferred'], {
            'checkout': {'value': str(self.checkout), 'origin': 'main'},
            'series': {'value': '19.0', 'origin': 'from the module manifests'},
            'community': {'value': str(self.source), 'origin': 'from --community'},
            'enterprise': {'value': None, 'origin': 'from --no-enterprise'},
            'workspace': {'value': str(self.checkout), 'origin': 'new'},
            'name': {'value': 'shop', 'origin': 'from the checkout name'},
            'environment': {'value': str(environment), 'origin': 'new'},
            'python': {'value': '3.12', 'origin': 'the default of Odoo 19.0'},
            'db_port': {'value': port, 'origin': 'a free port'}})
        # The lines are the human plan, byte for byte.
        self.assertEqual(plan['lines'], self.plan(port).splitlines())
        config = self.checkout / '.oasis/config'
        changes = {(change['kind'], change['path']): change['summary'] for change in plan['changes']}
        self.assertEqual(changes[('create', str(config / '.env'))],
                         f'create {config / ".env"} (mode 0600): ODOO_DB_USER oasis_shop and a generated '
                         'ODOO_DB_PASSWORD')
        self.assertEqual(changes[('create', str(self.checkout / 'oasis-workspace.toml'))],
                         f'create {self.checkout / "oasis-workspace.toml"} (mode 0600)')
        self.assertEqual(changes[('mkdir', str(config))], f'create the directory {config}/')
        self.assertEqual(plan['changes'][-2:], [
            {'kind': 'compile', 'path': str(config / 'requirements'),
             'summary': f'compile {config / "requirements"}/runtime.txt, dev.txt and lock.sha256 with Python 3.12 '
                        '(uv pip compile)'},
            {'kind': 'environment', 'path': str(environment),
             'summary': f'create the environment {environment} with Python 3.12 (uv venv) and sync dev.txt '
                        '(uv pip sync)'}])
        self.assertNotIn('ODOO_DB_PASSWORD=', json.dumps(plan))
        # v0.20.0 S1: without a terminal, the environment and its Python are open questions with their recommended
        # answers (the plan shows what those would create); development takes its recommended answer.
        self.assertEqual(plan['questions'], [
            {'id': 'environment', 'text': f'Python environment for Odoo 19.0: create {environment}, or use an '
                                          'existing environment', 'options': [
                {'value': 'create', 'label': f'create {environment}'}],
             'recommended': 'create', 'flag': '--answer environment=create | --environment <dir>', 'answer': None,
             'origin': None},
            {'id': 'python', 'text': f'Python of the new environment {environment}', 'options': [
                {'value': python, 'label': f'Python {python}'} for python in ('3.10', '3.11', '3.12', '3.13', '3.14')],
             'recommended': '3.12', 'flag': '--python <x.y>', 'answer': None, 'origin': None},
            development_question(self.checkout / 'oasis-workspace.toml', 'add', 'recommended (no terminal)')])
        # Answered as an agent relays them: ready to apply, each answer with where it came from.
        plan = self.json_plan('--community', str(self.source), '--no-enterprise', *CREATE)
        self.assertEqual((plan['open'], plan['ready_to_apply']), ([], True))
        self.assertEqual([(question['id'], question['answer'], question['origin']) for question in plan['questions']],
                         [('environment', 'create', 'from --answer'), ('python', '3.12', 'from --answer python'),
                          ('development', 'add', 'recommended (no terminal)')])
        self.assertEqual(plan['inferred']['python'], {'value': '3.12', 'origin': 'from --answer python'})
        # v0.16.0 S6: the answer none leaves the table out; an answer is reported with where it came from.
        plan = self.json_plan('--community', str(self.source), '--no-enterprise', *CREATE, '--answer',
                              'development=none')
        self.assertEqual(plan['questions'][-1],
                         development_question(self.checkout / 'oasis-workspace.toml', 'none', 'from --answer'))
        self.assertNotIn('  [development]', plan['lines'])
        self.assertEqual((plan['open'], plan['ready_to_apply']), ([], True))

    def test_without_an_answer_the_plan_lists_the_open_question_and_apply_names_its_flag(self):
        before = self.tree()
        refusal = f'No Odoo Community source for 19.0 in the machine file {self.machine}: pass --community <dir>.'
        text = self.setup_cmd('--no-enterprise')
        self.assertEqual((text.returncode, text.stdout, text.stderr),
                         (0, f'checkout: {self.checkout} (main)\nopen question community: {refusal}\n' + OPEN_PLAN, ''))
        plan = self.json_plan('--no-enterprise')
        self.assertEqual((plan['complete'], plan['ready_to_apply'], plan['open'], plan['changes']),
                         (False, False, ['community'], []))
        self.assertEqual(plan['inferred']['series'], {'value': '19.0', 'origin': 'from the module manifests'})
        self.assertEqual(plan['questions'], [
            {'id': 'community', 'text': 'Odoo Community source for 19.0 (absolute path)', 'options': [],
             'recommended': None, 'flag': '--community <dir>', 'answer': None, 'origin': None}])
        self.assertEqual(self.tree(), before)
        self.assert_refused(self.setup_cmd('--apply', '--no-enterprise'), refusal, before)
        # A source found near the checkout is the recommended option, never chosen alone.
        found = self.odoo_source(self.scratch / 'work' / 'odoo')
        before = self.tree()
        plan = self.json_plan('--no-enterprise')
        self.assertEqual(plan['questions'][0]['options'], [{'value': str(found), 'label': 'found near the checkout'}])
        self.assertEqual(plan['questions'][0]['recommended'], str(found))
        self.assertEqual(self.tree(), before)

    def test_an_answers_file_or_answer_flags_answer_as_the_flags_do(self):
        port = self.port_of(self.setup_cmd('--community', str(self.source), '--no-enterprise').stdout)
        before = self.tree()
        path = self.answers({'community': str(self.source), 'enterprise': 'none', 'environment': 'create',
                             'python': '3.12'})
        for arguments in (('--answers', str(path)),
                          ('--answer', f'community={self.source}', '--answer', 'enterprise=none', *CREATE)):
            with self.subTest(arguments=arguments):
                result = self.setup_cmd(*arguments)
                self.assertEqual((result.returncode, result.stdout, result.stderr), (0, self.plan(port) + DRY_RUN, ''))
        self.assertEqual(self.tree(), before)
        self.assert_refused(self.setup_cmd('--answers', str(path), '--community', str(self.source)),
                            f'The question community is answered twice: by --community and by --answers {path}.',
                            before)
        unknown = self.answers({'colour': 'blue'})
        self.assert_refused(self.setup_cmd('--answers', str(unknown)),
                            f'--answers {unknown}: unknown question colour (setup asks series, community, enterprise, '
                            'environment, python, workspace, series_exceptions, python_ldap, development and requirement:<name>).',
                            before)
        for content in ('[1]', '{"community": 1}', 'not json'):
            with self.subTest(content=content):
                unknown.write_text(content)
                self.assert_refused(self.setup_cmd('--answers', str(unknown)),
                                    f'--answers {unknown} must be a JSON object of question ids and text answers.',
                                    before)
        self.assert_refused(self.setup_cmd('--answer', 'community'),
                            '--answer community: use --answer <question id>=<value>.', before)

    def test_an_answer_to_a_question_setup_does_not_ask_is_refused(self):
        self.setup_cmd('--community', str(self.source), '--no-enterprise')
        before = self.tree()
        for answer in ('python_ldap=yes', 'requirement:phonenumbers=add'):
            with self.subTest(answer=answer):
                question = answer.partition('=')[0]
                for mode in ((), ('--apply',), ('--json',)):
                    self.assert_refused(
                        self.setup_cmd('--community', str(self.source), '--no-enterprise', '--answer', answer, *mode),
                        f'--answer: setup does not ask {question} for this checkout; nothing changed: drop it.',
                        before)

    def use_15(self, ldconfig=LDCONFIG_26):
        """An Odoo 15.0 checkout whose source pins python-ldap 3.4.0 and cryptography 2.6.1, whose module needs
        cryptography>=3.3.1 and phonenumbers, on a machine with that ldconfig (and pkg-config's OpenLDAP 2.6.8)."""
        (self.source / 'odoo' / 'release.py').write_text(RELEASE_15)
        (self.source / 'requirements.txt').write_text(REQUIREMENTS_15)
        self.module('shop_sale', MANIFEST_15)
        (self.bindir / 'ldconfig').write_text(f'#!/bin/sh\nprintf %s {json.dumps(ldconfig)}\n')
        (self.bindir / 'pkg-config').write_text('#!/bin/sh\n[ "$*" = "--modversion ldap" ] && echo 2.6.8 && exit 0\n'
                                                'exit 1\n')
        for name in ('ldconfig', 'pkg-config'):
            (self.bindir / name).chmod(0o755)

    def test_an_odoo_15_plan_anticipates_python_ldap_and_the_module_requirements(self):
        self.use_15()
        before = self.tree()
        requirements = self.checkout / '.oasis/config/requirements'
        overrides, runtime = requirements / 'overrides.txt', requirements / 'runtime.in'
        plan = self.json_plan('--community', str(self.source), '--no-enterprise', *CREATE_15)
        self.assertEqual(self.tree(), before)
        self.assertEqual((plan['complete'], plan['ready_to_apply']), (True, False))
        self.assertEqual(plan['open'], ['python_ldap', 'requirement:cryptography', 'requirement:phonenumbers'])
        questions = {question['id']: question for question in plan['questions']}
        self.assertEqual(questions['python_ldap'], {
            'id': 'python_ldap',
            'text': ("Odoo 15.0 pins python-ldap==3.4.0, which does not build against this machine's OpenLDAP 2.6.8 "
                     f'(no libldap_r): pin python-ldap==3.4.4 in {overrides}?'),
            'options': [{'value': 'yes', 'label': 'pin python-ldap==3.4.4 (uv pip compile --override)'},
                        {'value': 'no', 'label': "keep Odoo's pin: its build may fail"}],
            'recommended': 'yes', 'flag': '--answer python_ldap=<yes|no>', 'answer': None, 'origin': None})
        self.assertEqual(questions['requirement:cryptography'], {
            'id': 'requirement:cryptography',
            'text': ('The module shop_sale requires cryptography>=3.3.1 (external_dependencies), but the Odoo 15.0 '
                     f'requirements pin cryptography==2.6.1: override it with cryptography==3.3.1 in {overrides}?'),
            'options': [{'value': 'override', 'label': 'pin cryptography==3.3.1 (uv pip compile --override)'},
                        {'value': 'skip', 'label': "keep Odoo's pin: the module may not install"}],
            'recommended': 'override', 'flag': '--answer requirement:cryptography=<override|skip>', 'answer': None,
            'origin': None})
        self.assertEqual(questions['requirement:phonenumbers'], {
            'id': 'requirement:phonenumbers',
            'text': ('The module shop_sale requires phonenumbers (external_dependencies), which no requirement of '
                     f'{runtime} lists: add it there?'),
            'options': [{'value': 'add', 'label': 'add phonenumbers to runtime.in'},
                        {'value': 'skip', 'label': 'leave it out: the module will not install without it'}],
            'recommended': 'add', 'flag': '--answer requirement:phonenumbers=<add|skip>', 'answer': None,
            'origin': None})
        # The human plan lists them too; --apply refuses before any change, naming each flag.
        text = self.setup_cmd('--community', str(self.source), '--no-enterprise', *CREATE_15)
        self.assertEqual(text.returncode, 0)
        self.assertTrue(text.stdout.endswith(
            f'open question python_ldap: {questions["python_ldap"]["text"]} Answer with --answer python_ldap=<yes|no> '
            '(recommended: yes).\n'
            f'open question requirement:cryptography: {questions["requirement:cryptography"]["text"]} Answer with '
            '--answer requirement:cryptography=<override|skip> (recommended: override).\n'
            f'open question requirement:phonenumbers: {questions["requirement:phonenumbers"]["text"]} Answer with '
            '--answer requirement:phonenumbers=<add|skip> (recommended: add).\n' + OPEN_PLAN), text.stdout)
        self.assertEqual(text.stdout.splitlines()[:-4], plan['lines'])
        refused = self.setup_cmd('--apply', '--community', str(self.source), '--no-enterprise', *CREATE_15,
                                 '--answer', 'python_ldap=yes')
        self.assertEqual((refused.returncode, refused.stdout), (2, ''))
        self.assertEqual(refused.stderr, (
            f'ERROR: open question requirement:cryptography: {questions["requirement:cryptography"]["text"]} Answer '
            'with --answer requirement:cryptography=<override|skip> (recommended: override).\n'
            f'ERROR: open question requirement:phonenumbers: {questions["requirement:phonenumbers"]["text"]} Answer '
            'with --answer requirement:phonenumbers=<add|skip> (recommended: add).\n'
            'ERROR: nothing changed: answer the open questions, then run oasis setup --apply again.\n'))
        self.assertEqual(self.tree(), before)
        self.assertFalse(self.log.exists())
        invalid = self.setup_cmd('--answer', 'python_ldap=maybe', '--community', str(self.source), '--no-enterprise')
        self.assert_refused(invalid, 'Invalid answer maybe for python_ldap: answer yes or no.', before)
        # Answered: the pins go to a new overrides.txt, the missing requirement to the new runtime.in.
        answers = self.answers({'python_ldap': 'yes', 'requirement:cryptography': 'override',
                                'requirement:phonenumbers': 'add'})
        applied = self.setup_cmd('--apply', '--community', str(self.source), '--no-enterprise', *CREATE_15,
                                 '--answers', str(answers))
        self.assertEqual((applied.returncode, applied.stderr), (0, ''), applied.stdout)
        self.assertIn(f'create {overrides}: python-ldap==3.4.4, cryptography==3.3.1 (uv pip compile --override)\n',
                      applied.stdout)
        self.assertIn(f'create {runtime}: -r {self.source}/requirements.txt, setuptools<81, phonenumbers\n',
                      applied.stdout)
        self.assertEqual(overrides.read_text(), (
            "# Written by oasis setup: pins that replace Odoo's, given to uv pip compile as --override for "
            'runtime.txt and dev.txt.\n'
            "# Odoo 15.0's python-ldap==3.4.0 does not build against OpenLDAP 2.6 (no libldap_r).\n"
            'python-ldap==3.4.4\n'
            '# The module shop_sale requires cryptography>=3.3.1 (external_dependencies).\n'
            'cryptography==3.3.1\n'))
        self.assertTrue(runtime.read_text().endswith(
            '# The module shop_sale requires it (external_dependencies).\nphonenumbers\n'))
        self.assertIn(f'uv pip compile --python-version 3.9 --override overrides.txt runtime.in -o runtime.txt '
                      f'(in {requirements})\n', self.log.read_text())

    def test_no_python_ldap_question_with_libldap_r_or_without_the_pin(self):
        self.use_15(LDCONFIG_24)
        plan = self.json_plan('--community', str(self.source), '--no-enterprise', *CREATE_15,
                              '--answer', 'requirement:cryptography=skip', '--answer', 'requirement:phonenumbers=skip')
        self.assertEqual((plan['open'], plan['ready_to_apply']), ([], True))
        self.assertNotIn('python_ldap', [question['id'] for question in plan['questions']])
        self.assertEqual([(question['id'], question['answer'], question['origin']) for question in plan['questions']
                          if question['id'].startswith('requirement:')],
                         [('requirement:cryptography', 'skip', 'from --answer'),
                          ('requirement:phonenumbers', 'skip', 'from --answer')])
        self.use_15()
        (self.source / 'requirements.txt').write_text('python-ldap==3.4.4\ncryptography==3.4.8\nphonenumbers\n')
        plan = self.json_plan('--community', str(self.source), '--no-enterprise', *CREATE_15)
        self.assertEqual((plan['open'], plan['ready_to_apply']), ([], True))

    def test_on_a_terminal_an_anticipated_problem_is_asked_and_enter_takes_the_recommended_answer(self):
        self.use_15()
        before = self.tree()
        status, stdout, terminal = on_terminal(
            ['--project', str(self.checkout), 'setup', '--community', str(self.source), '--no-enterprise',
             '--python', '3.9', '--answer', 'requirement:cryptography=skip', '--answer', 'requirement:phonenumbers=skip',
             '--answer', 'development=add'],
            self.env, self.scratch, [('(yes/no) [Enter: yes]: ', b'maybe\n'), ('Answer yes or no, or Enter for yes.\n', b'\n')])
        self.assertEqual(status, 0, terminal)
        self.assertIn('python-ldap==3.4.0, which does not build', terminal)
        overrides = self.checkout / '.oasis/config/requirements/overrides.txt'
        self.assertIn(f'create {overrides}: python-ldap==3.4.4 (uv pip compile --override)\n', stdout)
        self.assertTrue(stdout.endswith(DRY_RUN), stdout)
        self.assertEqual(self.tree(), before)

    def test_an_import_name_setup_does_not_know_gets_no_recommended_answer(self):
        # cv2 is the module opencv-python provides: setup never proposes an import name as a distribution.
        self.module('shop_vision', "{'name': 'Shop Vision', 'version': '19.0.1.0.0', 'depends': ['sale'],\n"
                                   " 'external_dependencies': {'python': ['cv2', 'yaml']}}\n")
        before = self.tree()
        runtime = self.checkout / '.oasis/config/requirements/runtime.in'
        flags = ('--community', str(self.source), '--no-enterprise', *CREATE)
        plan = self.json_plan(*flags)
        self.assertEqual((plan['open'], plan['ready_to_apply']), (['requirement:cv2', 'requirement:pyyaml'], False))
        questions = {question['id']: question for question in plan['questions']}
        cv2 = {'id': 'requirement:cv2',
               'text': ('The module shop_vision requires cv2 (external_dependencies), which no requirement of '
                        f'{runtime} lists, and setup cannot tell whether cv2 is the name of its distribution or only '
                        'the module it imports: add cv2 there as written?'),
               'options': [{'value': 'add', 'label': 'add cv2 to runtime.in: cv2 is the name of its distribution'},
                           {'value': 'skip', 'label': 'leave it out: add the distribution that provides cv2 to the '
                                                      'requirements yourself, or the module will not install'}],
               'recommended': None, 'flag': '--answer requirement:cv2=<add|skip>', 'answer': None, 'origin': None}
        self.assertEqual(questions['requirement:cv2'], cv2)
        # A translated import name keeps its recommended answer.
        self.assertEqual((questions['requirement:pyyaml']['recommended'], questions['requirement:pyyaml']['options'][0]),
                         ('add', {'value': 'add', 'label': 'add pyyaml to runtime.in'}))
        text = self.setup_cmd(*flags)
        self.assertEqual(text.returncode, 0)
        self.assertIn(f'open question requirement:cv2: {cv2["text"]} Answer with --answer requirement:cv2=<add|skip> '
                      '(no recommended answer).\n', text.stdout)
        refused = self.setup_cmd('--apply', *flags, '--answer', 'requirement:pyyaml=add')
        self.assertEqual((refused.returncode, refused.stdout), (2, ''))
        self.assertTrue(refused.stderr.startswith(
            f'ERROR: open question requirement:cv2: {cv2["text"]} Answer with --answer requirement:cv2=<add|skip> '
            '(no recommended answer).\n'), refused.stderr)
        self.assertEqual(self.tree(), before)
        # add writes it as written, as the answer says; skip leaves it out of runtime.in.
        added = self.setup_cmd(*flags, '--answer', 'requirement:cv2=add', '--answer', 'requirement:pyyaml=add')
        self.assertIn(f'create {runtime}: -r {self.source}/requirements.txt, cv2, pyyaml\n', added.stdout)
        applied = self.setup_cmd('--apply', *flags, '--answer', 'requirement:cv2=skip', '--answer',
                                 'requirement:pyyaml=add')
        self.assertEqual((applied.returncode, applied.stderr), (0, ''), applied.stdout)
        self.assertIn(f'create {runtime}: -r {self.source}/requirements.txt, pyyaml\n', applied.stdout)
        self.assertTrue(runtime.read_text().endswith(
            '# The module shop_vision requires it (external_dependencies).\npyyaml\n'))
        self.assertNotIn('cv2', runtime.read_text())

    def test_on_a_terminal_a_question_without_a_recommended_answer_needs_one(self):
        self.module('shop_vision', "{'name': 'Shop Vision', 'version': '19.0.1.0.0',\n"
                                   " 'external_dependencies': {'python': ['cv2']}}\n")
        before = self.tree()
        status, stdout, terminal = on_terminal(
            ['--project', str(self.checkout), 'setup', '--community', str(self.source), '--no-enterprise',
             '--python', '3.12', '--answer', 'development=add'],
            self.env, self.scratch, [('as written? (add/skip): ', b'\n'), ('Answer add or skip.\n', b'skip\n')])
        self.assertEqual(status, 0, terminal)
        self.assertNotIn('Enter', terminal)
        runtime = self.checkout / '.oasis/config/requirements/runtime.in'
        self.assertIn(f'create {runtime}: -r {self.source}/requirements.txt\n', stdout)
        self.assertTrue(stdout.endswith(DRY_RUN), stdout)
        self.assertEqual(self.tree(), before)

    def test_a_kept_overrides_file_is_never_edited_python_ldap_gets_a_warning_and_a_conflict_no_question(self):
        self.use_15()
        requirements = self.checkout / '.oasis/config/requirements'
        requirements.mkdir(parents=True)
        overrides = requirements / 'overrides.txt'
        overrides.write_text('# mine\n')
        flags = ('--community', str(self.source), '--no-enterprise', *CREATE_15)
        before = self.tree()
        plan = self.json_plan(*flags)
        self.assertEqual(plan['open'], ['requirement:phonenumbers'])
        self.assertEqual([question['id'] for question in plan['questions'] if question['answer'] is None],
                         ['requirement:phonenumbers'])
        warning = ("WARN: Odoo 15.0 pins python-ldap==3.4.0, which does not build against this machine's OpenLDAP "
                   f'2.6.8 (no libldap_r): add python-ldap==3.4.4 to {overrides} yourself (setup keeps that file)')
        self.assertIn(warning, plan['lines'])
        self.assertIn(f'kept {overrides}', plan['lines'])
        self.assertEqual(self.tree(), before)
        for question in ('python_ldap', 'requirement:cryptography'):
            with self.subTest(question=question):
                self.assert_refused(self.setup_cmd(*flags, '--answer', f'{question}=yes'),
                                    f'--answer: setup does not ask {question} for this checkout; nothing changed: '
                                    'drop it.', before)
        applied = self.setup_cmd('--apply', *flags, '--answer', 'requirement:phonenumbers=add')
        self.assertEqual((applied.returncode, applied.stderr), (0, ''), applied.stdout)
        self.assertIn(warning + '\n', applied.stdout)
        self.assertEqual(overrides.read_text(), '# mine\n')
        self.assertTrue((requirements / 'runtime.in').read_text().endswith('phonenumbers\n'))

    def test_the_json_plan_of_an_existing_workspace_says_what_it_keeps_and_where_it_came_from(self):
        applied = self.setup_cmd('--apply', '--community', str(self.source), '--no-enterprise', *CREATE)
        self.assertEqual(applied.returncode, 0, applied.stderr)
        before = self.tree()
        plan = self.json_plan()
        config = self.checkout / '.oasis/config'
        self.assertEqual(plan['inferred'], {
            'checkout': {'value': str(self.checkout), 'origin': 'main'},
            'workspace': {'value': str(self.checkout), 'origin': 'existing'},
            'series': {'value': '19.0', 'origin': 'from the workspace file'},
            'db_port': {'value': self.port_of(applied.stdout), 'origin': f'from {config / "odoo.conf"}'},
            'environment': {'value': str(self.checkout / '.oasis/venv'), 'origin': 'existing'},
            'python': {'value': '3.12', 'origin': 'from the workspace file'}})
        self.assertEqual({key: plan[key] for key in ('complete', 'ready_to_apply', 'open', 'questions', 'changes')},
                         {'complete': True, 'ready_to_apply': True, 'open': [], 'questions': [], 'changes': []})
        text = self.setup_cmd()
        self.assertEqual((text.returncode, text.stderr), (0, ''))
        self.assertEqual(plan['lines'], text.stdout.splitlines()[:len(plan['lines'])])
        self.assertEqual(plan['lines'][-1], f'kept the environment {self.checkout / ".oasis/venv"}')
        self.assertEqual(self.tree(), before)

    def test_an_environment_answer_adopts_it_as_environment_does(self):
        environment = test_setup.SetupTests.existing_environment(self, 'shop', '3.12.3')
        flags = ('--community', str(self.source), '--no-enterprise')
        before = self.tree()
        answered = self.json_plan(*flags, '--answer', f'environment={environment}')
        given = self.json_plan(*flags, '--environment', str(environment))
        self.assertEqual(answered, given)
        self.assertEqual((answered['inferred']['environment'], answered['inferred']['python']),
                         ({'value': str(environment), 'origin': 'from --environment'},
                          {'value': '3.12', 'origin': 'from the adopted environment'}))
        self.assertEqual(answered['lines'][-1], f'adopt the environment {environment} (from --environment): Python 3.12 '
                                                '(its pyvenv.cfg); setup never creates, syncs or deletes it')
        self.assertEqual(self.setup_cmd(*flags, '--answer', f'environment={environment}').stdout,
                         self.setup_cmd(*flags, '--environment', str(environment)).stdout)
        self.assert_refused(self.setup_cmd(*flags, '--environment', str(environment), '--answer',
                                           f'environment={environment}'),
                            'The question environment is answered twice: by --environment and by --answer.', before)
        self.assert_refused(self.setup_cmd(*flags, '--answer', f'environment={self.scratch / "none"}'),
                            '--environment requires an absolute existing directory.',
                            before)
        self.assertFalse((self.scratch / 'python-ran').exists())

    def test_json_never_applies_and_help_names_the_new_options(self):
        result = self.setup_cmd('--apply', '--json')
        self.assertEqual(result.returncode, 2)
        self.assertTrue(result.stderr.startswith('Usage: '))
        self.assertFalse(self.log.exists())
        help_text = self.setup_cmd('--help').stdout
        for option in ('--json', '--answers <file.json>', '--answer <id>=<value>', 'python_ldap'):
            self.assertIn(option, help_text)


if __name__ == '__main__':
    unittest.main()
