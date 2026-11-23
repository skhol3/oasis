#!/usr/bin/env python3
"""The oasis action catalog and the terminal menu (`oasis menu`): one table for both.

`oasis menu --catalog` prints the catalog as JSON for the Gentle Shell panel and runs nothing;
no other place lists the actions. `oasis menu` shows the same actions as numbered menus, asks the
inputs, shows the exact command, asks for confirmation of destructive actions and runs it. It
refuses to run without a terminal on stdin, so an agent cannot drive it.

Catalog (JSON, stable keys):
  catalog_version  1
  project          the checkout root
  entrypoint       the invoked entry point (`oasis`, or `odoo19` through its alias)
  server_log       the checkout's server.log (start --detach), whether or not it exists yet
  sources          modules: {choices: [addon modules of the checkout]};
                   databases: {argv: the list-databases command, waiting: a message to show while
                   it runs, since it may start the database service}
  groups           [{id, label}] in menu order
  actions          [{id, group, label, kind, command, argv, inputs, destructive, confirm, user_run,
                   terminal_only}] in menu order
An action's kind is `command` (argv runs an oasis command) or `log` (argv shows the end of
server_log). inputs are asked in order: {id, label, kind (choice | text | boolean), source
(modules | databases | null: where the choices come from), required, allow_new (a choice may also
be typed), pattern (a regular expression a typed value must match, or null), error (the message
when it does not), default (booleans: false), hint (what an empty answer means, or null)}.
confirm is `database` (type the chosen database name), `yes` (type yes) or null; destructive is
true exactly when confirm is set. user_run actions are for the user only (never an agent);
terminal_only actions need a terminal (init-dev-database asks for passwords).

argv is a template; fill it in order (build below):
  "text"                        the word itself
  {"input": id}                 the input's value; nothing when it is empty
  {"input": id, "option": "-x"} -x and the value; nothing when it is empty
  {"input": id, "flag": "-x"}   -x when the boolean input is true
  {"compact": "--compact"}      the word when the caller shows compact output (the panel)
"""
import importlib.util
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

CATALOG_VERSION = 1
GROUPS = (('server', 'Server'), ('modules', 'Modules'), ('tests', 'Tests'),
          ('maintenance', 'Databases and maintenance'))
# The same rules as test-module --only and the database guards of common.sh.
CLASS_PATTERN = r'^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)?$'
CLASS_ERROR = '--only takes a test class or Class.method.'
DATABASE_PATTERN = r'^[A-Za-z0-9_]+$'
DATABASE_ERROR = 'Database name must use only letters, numbers, and underscores.'
MODULE_NAME = re.compile(r'[A-Za-z0-9_]+')
WAITING = 'Listing databases (this may start the database service)...'
LOG_LINES = '200'
HELP = '''Shows the oasis actions of this checkout as numbered menus in a terminal: choose a group, an
action and its inputs (modules from the checkout's addon roots, databases from list-databases,
which may start the database service). The exact command is shown before it runs; destructive
actions run only after you type the database name or yes. One action per run; the exit status is
the command's. It needs a terminal on stdin and exits 2 without one.
--catalog prints the actions as JSON (for the Gentle Shell panel) and runs nothing.
'''


def sibling(name: str):
    """A packaged helper loaded from its file (python3 -I keeps the tools directory off sys.path)."""
    spec = importlib.util.spec_from_file_location(f'oasis_actions_{name}', Path(__file__).with_name(f'{name}.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def field(id, label, kind, *, source=None, required=True, allow_new=False, pattern=None, error=None,
          hint=None):
    return {'id': id, 'label': label, 'kind': kind, 'source': source,
            'required': required if kind != 'boolean' else False, 'allow_new': allow_new,
            'pattern': pattern, 'error': error, 'default': False if kind == 'boolean' else None,
            'hint': hint}


def database(required=True, hint=None):
    return field('database', 'Database', 'choice', source='databases', required=required, allow_new=True,
                 pattern=DATABASE_PATTERN, error=DATABASE_ERROR, hint=hint)


def new_database():
    return field('database', 'New database name', 'text', pattern=DATABASE_PATTERN, error=DATABASE_ERROR)


def only(required=True):
    return field('only', 'Test class (Class or Class.method)', 'text', required=required, pattern=CLASS_PATTERN,
                 error=CLASS_ERROR, hint=None if required else 'Enter for every test of the module')


MODULE = field('module', 'Module', 'choice', source='modules')
DEMO = field('demo', 'Load demo data', 'boolean')
TERMINATE = field('terminate', 'Close its open sessions first (--terminate)', 'boolean')
COMPACT = {'compact': '--compact'}


def value(id):
    return {'input': id}


def option(id, name):
    return {'input': id, 'option': name}


def flag(id, name):
    return {'input': id, 'flag': name}


def action(id, label, command, template=(), inputs=(), *, confirm=None, user_run=False, terminal_only=False,
           kind='command'):
    return {'id': id, 'group': id.split('.', 1)[0], 'label': label, 'kind': kind, 'command': command,
            'argv': list(template), 'inputs': list(inputs), 'destructive': confirm is not None,
            'confirm': confirm, 'user_run': user_run, 'terminal_only': terminal_only}


def actions(values: dict, class_filter: bool) -> list[dict]:
    """The catalog's actions in menu order, argv still without the entry point prefix."""
    slug = values.get('CHECKOUT_SLUG', '')
    default_dev = f"{values['DEV_PREFIX']}{slug + '_' if slug else ''}<module>"
    tests = [action('tests.module', 'Test a module', 'test-module', [COMPACT, value('module')], [MODULE])]
    if class_filter:
        tests.append(action('tests.class', 'Test one class or method', 'test-module',
                            [COMPACT, option('only', '--only'), value('module')], [MODULE, only()]))
        tests.append(action('tests.reuse', 'Test reusing the test database', 'test-module',
                            [COMPACT, '--reuse', option('only', '--only'), value('module')],
                            [MODULE, only(required=False)]))
    else:
        tests.append(action('tests.reuse', 'Test reusing the test database', 'test-module',
                            [COMPACT, '--reuse', value('module')], [MODULE]))
    return [
        action('server.start', 'Start the server in the background', 'start',
               ['--detach', option('database', '-d')],
               [database(required=False, hint='Enter to start without -d')]),
        action('server.stop', 'Stop the server', 'stop'),
        action('server.logs', 'Show the end of the server log', None, kind='log'),
        action('server.status', 'Show the server and database service status', 'status'),
        action('server.stop_database', 'Stop the database service', 'stop', ['--database'], confirm='yes'),
        action('modules.install', 'Install a module', 'install-module',
               [flag('demo', '--with-demo'), value('module'), value('database')],
               [MODULE, database(required=False, hint=f'Enter for {default_dev}'), DEMO]),
        action('modules.update', 'Update a module', 'update-module', [COMPACT, value('module'), value('database')],
               [MODULE, database()]),
        action('modules.status', "Show a module's state", 'module-status', [value('module'), value('database')],
               [MODULE, database()]),
        action('modules.init_dev', 'Create a development database with role accounts', 'init-dev-database',
               [flag('demo', '--with-demo'), value('module'), value('database')],
               [MODULE, new_database(), DEMO], terminal_only=True),
        *tests,
        action('maintenance.create_database', 'Create a database', 'create-database', [value('database')],
               [new_database()]),
        action('maintenance.drop_database', 'Drop a database', 'drop-database',
               [value('database'), flag('terminate', '--terminate')], [database(), TERMINATE], confirm='database'),
        action('maintenance.gc', 'List leftover test databases', 'gc'),
        action('maintenance.gc_apply', 'Drop leftover test databases', 'gc', ['--apply'], confirm='yes'),
        action('maintenance.doctor', 'Check the environment (doctor)', 'doctor'),
        action('maintenance.migrate_plan', 'Show the workspace migration plan', 'migrate', ['--plan']),
        action('maintenance.migrate', 'Migrate to the workspace file', 'migrate', ['--apply'], confirm='yes',
               user_run=True),
        action('maintenance.worktree', 'Create a linked worktree', 'worktree-init',
               [value('feature'), value('branch')],
               [field('feature', 'Feature name', 'text'), field('branch', 'Branch', 'text')], user_run=True),
    ]


def addon_modules(roots: str) -> list[str]:
    found = set()
    for root in filter(None, roots.split('\n')):
        directory = Path(root)
        if not directory.is_dir():
            continue
        for child in directory.iterdir():
            if MODULE_NAME.fullmatch(child.name) and (child / '__manifest__.py').is_file():
                found.add(child.name)
    return sorted(found)


def catalog(config, log_dirs, root: Path) -> dict:
    values = config.load(root)
    entrypoint = config.variable('ENTRYPOINT') or str(Path(__file__).resolve().parent.parent / 'oasis')
    prefix = [entrypoint, '--project', str(root)]
    server_log = str(log_dirs.server_log(root, values.get('CHECKOUT_KIND', ''), values.get('CHECKOUT_MAIN_ROOT', ''),
                                         values.get('LOGS_DIR', ''), values.get('CHECKOUT_SLUG', '')))
    class_filter = config.versions().capability(values['ODOO_VERSION'], 'test_class_filter')
    listed = []
    for item in actions(values, class_filter):
        if item['kind'] == 'log':
            item['argv'] = ['tail', '-n', LOG_LINES, server_log]
        else:
            item['argv'] = [*prefix, item['command'], *item['argv']]
        listed.append(item)
    return {
        'catalog_version': CATALOG_VERSION,
        'project': str(root),
        'entrypoint': entrypoint,
        'server_log': server_log,
        'sources': {'modules': {'choices': addon_modules(values.get('ADDON_ROOTS', ''))},
                    'databases': {'argv': [*prefix, 'list-databases'], 'waiting': WAITING}},
        'groups': [{'id': id, 'label': label} for id, label in GROUPS],
        'actions': listed,
    }


def build(item: dict, answers: dict, compact: bool = False) -> list[str]:
    """The argv of an action from its template and the answers (see the module docstring)."""
    argv = []
    for token in item['argv']:
        if isinstance(token, str):
            argv.append(token)
        elif 'compact' in token:
            if compact:
                argv.append(token['compact'])
        elif 'flag' in token:
            if answers.get(token['input']) is True:
                argv.append(token['flag'])
        else:
            answer = answers.get(token['input']) or ''
            if answer:
                argv.extend([token['option'], answer] if 'option' in token else [answer])
    return argv


class Cancelled(Exception):
    """The user quit or the input ended; the value is the exit status."""


class Terminal:
    def __init__(self, data: dict, program: str):
        self.data = data
        self.program = program
        self.databases = None

    def ask(self, prompt: str) -> str:
        print(prompt, end='', flush=True)
        line = sys.stdin.readline()
        if not line:
            print('\nNo input: nothing ran.', flush=True)
            raise Cancelled(1)
        return line.strip()

    def pick(self, title: str, labels: list[str], prompt: str) -> int:
        """A 0-based index chosen by number; q quits."""
        if title:
            print(title)
        for number, label in enumerate(labels, 1):
            print(f'  {number}) {label}')
        while True:
            answer = self.ask(prompt)
            if answer == 'q':
                raise Cancelled(0)
            if answer.isdigit() and 1 <= int(answer) <= len(labels):
                return int(answer) - 1
            print(f'Choose a number from 1 to {len(labels)}, or q.')

    def choices(self, source: str) -> list[str]:
        if source == 'modules':
            return self.data['sources']['modules']['choices']
        if self.databases is None:
            listing = self.data['sources']['databases']
            print(listing['waiting'], flush=True)
            # stdin stays out of it: `compose exec` would read what the user types next.
            result = subprocess.run(listing['argv'], stdin=subprocess.DEVNULL, capture_output=True, text=True)
            if result.returncode != 0:
                print(f'Cannot list the databases (exit {result.returncode}):')
                print(result.stderr, end='')
                self.databases = []
            else:
                self.databases = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        return self.databases

    def answer(self, item: dict, answers: dict):
        label = item['label']
        if item['kind'] == 'boolean':
            while True:
                answer = self.ask(f'{label}? [y/N]: ').lower()
                if answer in ('', 'n', 'no', 'y', 'yes'):
                    return answer in ('y', 'yes')
                print('Answer y or n.')
        parts = []
        listed = []
        if item['kind'] == 'choice':
            listed = self.choices(item['source'])
            if not listed and not item['allow_new']:
                print(f'No {label.lower()}s found in this checkout.')
                raise Cancelled(1)
            if listed:
                print(label)
                for number, choice in enumerate(listed, 1):
                    print(f'  {number}) {choice}')
            elif item['source'] == 'databases':
                print('No databases found.')
            parts.append('number or name' if listed else 'name')
        if item['hint']:
            parts.append(item['hint'])
        elif not item['required']:
            parts.append('Enter to skip')
        prompt = f"{label} ({', '.join(parts)}): " if parts else f'{label}: '
        while True:
            answer = self.ask(prompt)
            if not answer:
                if not item['required']:
                    return ''
                print('A value is required.')
                continue
            if item['kind'] == 'choice' and answer.isdigit():
                # A number picks from the list; it never becomes a name.
                if listed and 1 <= int(answer) <= len(listed):
                    return listed[int(answer) - 1]
                if not item['allow_new']:
                    print(f'Choose a number from 1 to {len(listed)}, or a name from the list.')
                elif listed:
                    print(f'Choose a number from 1 to {len(listed)}, or type a name.')
                else:
                    print(f'No {label.lower()} is listed: type a name.')
                continue
            if answer in listed:
                return answer
            if item['kind'] == 'choice' and not item['allow_new']:
                print(f'Choose a number from 1 to {len(listed)}, or a name from the list.')
                continue
            if item['pattern'] and not re.fullmatch(item['pattern'], answer):
                print(item['error'])
                continue
            return answer

    def run(self) -> int:
        print(f"{self.program} menu: {self.data['project']}")
        groups = self.data['groups']
        group = groups[self.pick('', [entry['label'] for entry in groups], 'Group (q to quit): ')]
        members = [entry for entry in self.data['actions'] if entry['group'] == group['id']]
        chosen = members[self.pick(group['label'], [entry['label'] for entry in members], 'Action (q to quit): ')]
        if chosen['kind'] == 'log' and not Path(self.data['server_log']).is_file():
            print(f"No server log yet: {self.data['server_log']}")
            return 1
        answers = {}
        for item in chosen['inputs']:
            answers[item['id']] = self.answer(item, answers)
        argv = build(chosen, answers)
        print('Command: ' + shlex.join(argv), flush=True)
        if chosen['confirm'] == 'database':
            if self.ask('Type the database name to confirm: ') != answers.get('database'):
                print('Not confirmed: nothing ran.')
                return 1
        elif chosen['confirm'] == 'yes':
            if self.ask('Type yes to confirm: ') != 'yes':
                print('Not confirmed: nothing ran.')
                return 1
        status = subprocess.run(argv).returncode
        return status if status >= 0 else 128 - status


def main(arguments: list[str]) -> int:
    config = sibling('config')
    usage = f'Usage: {config.usage_name()} menu [--catalog]'
    if arguments in (['--help'], ['-h']):
        print(usage + '\n' + HELP, end='')
        return 0
    if arguments not in ([], ['--catalog']):
        print(usage, file=sys.stderr)
        return 2
    program = config.program_name()
    if not arguments and not sys.stdin.isatty():
        print(f'{program} menu needs a terminal (stdin is not a TTY); run it yourself, or print the actions '
              'as JSON with --catalog.', file=sys.stderr)
        return 2
    root = config.selected_root()
    if root is None:
        print(f'ERROR: {config.PROJECT_ROOT_REQUIRED}', file=sys.stderr)
        return 2
    log_dirs = sibling('log_dirs')
    try:
        data = catalog(config, log_dirs, root)
    except (ValueError, log_dirs.LogLocationError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 2
    if arguments:
        print(json.dumps(data, indent=2))
        return 0
    try:
        return Terminal(data, program).run()
    except Cancelled as exc:
        return exc.args[0]
    except KeyboardInterrupt:
        print('\nInterrupted: nothing more runs.')
        return 130


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
