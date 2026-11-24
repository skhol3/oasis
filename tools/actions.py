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
                   terminal_only, follow, superseded_by}] in menu order
  checkout         what the menu headers show and the start / restart flow needs: {name (main or the
                   worktree slug), server: {state (running | stopped | unknown), pid, port, database,
                   error}, default_database (the last database the flow used in this checkout, else
                   the development database of its only module, else null), no_database: {start,
                   restart: the warning to show when no database is chosen}}
  last             {action, answers, label (`Repeat: <label> (<short answers>)`)}: the last action
                   run from a menu in this checkout (tools/runtime_state.py menu.json), only while it
                   is still in the catalog and its answers still fit its inputs; else null
Added keys never change the meaning of the earlier ones, so an older panel keeps working:
superseded_by names the action that replaces this one in the menus (server.start and server.restart
are replaced by server.run, the start / restart flow); front ends that know it do not list them.
An action's kind is `command` (argv runs an oasis command) or `log` (argv shows the end of
server_log); follow is true for the log action that keeps showing what the server writes (argv
is `tail -n 200 -f <server_log>`; the terminal menu runs it until Ctrl+C, the panel shows the end
of server_log and refreshes it while open), false for every other action. inputs are asked in order: {id, label, kind (choice | text | boolean), source
(modules | databases | null: where the choices come from), required, allow_new (a choice may also
be typed), pattern (a regular expression a typed value must match, or null), error (the message
when it does not), default (booleans: false), hint (what an empty answer means, or null), choices (a closed list of {value, label, warning}
for a choice without source, warning being what to show when it is chosen, or null)}. A choice's
default is the value an empty answer takes (null: nothing); a text input's default is only shown
(an empty answer leaves the option out, so the command applies its own rule).
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
import functools
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
# gc --older-than takes whole days.
DAYS_PATTERN = r'^[0-9]+$'
DAYS_ERROR = 'Days must be a whole number.'
# A port number, 1-65535 (start validates it the same way).
PORT_PATTERN = r'^(?:[1-9][0-9]{0,3}|[1-5][0-9]{4}|6[0-4][0-9]{3}|65[0-4][0-9]{2}|655[0-2][0-9]|6553[0-5])$'
PORT_ERROR = 'Port must be a number from 1 to 65535.'
RUN_ACTION = 'server.run'
SERVER_COMMANDS = ('start', 'restart')
NO_CONF_DATABASE = 'No database chosen: odoo.conf sets no db_name, so Odoo starts without a database.'
# Whether one of the packages is importable (argv[1:]); run by the environment's Python.
IMPORTABLE = ('import importlib.util, sys; '
              'sys.exit(0 if any(importlib.util.find_spec(name) for name in sys.argv[1:]) else 1)')
WAITING = 'Listing databases (this may start the database service)...'
LOG_LINES = '200'
HELP = '''Shows the oasis actions of this checkout as numbered menus in a terminal: choose a group, an
action and its inputs (modules from the checkout's addon roots, databases from list-databases,
which may start the database service). The exact command is shown before it runs; destructive
actions run only after you type the database name or yes, start / restart after y. The last action
run in this checkout is offered first (r). One action per run; the exit status is
the command's (following the server log runs until Ctrl+C, then exits 0). It needs a terminal on
stdin and exits 2 without one.
--catalog prints the actions as JSON (for the Gentle Shell panel) and runs nothing.
'''


@functools.cache
def sibling(name: str):
    """A packaged helper loaded from its file (python3 -I keeps the tools directory off sys.path)."""
    spec = importlib.util.spec_from_file_location(f'oasis_actions_{name}', Path(__file__).with_name(f'{name}.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def field(id, label, kind, *, source=None, required=True, allow_new=False, pattern=None, error=None,
          hint=None, default=None, choices=None):
    return {'id': id, 'label': label, 'kind': kind, 'source': source,
            'required': required if kind != 'boolean' else False, 'allow_new': allow_new,
            'pattern': pattern, 'error': error, 'default': False if kind == 'boolean' else default,
            'hint': hint, 'choices': choices}


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
           kind='command', follow=False, superseded_by=None):
    return {'id': id, 'group': id.split('.', 1)[0], 'label': label, 'kind': kind, 'command': command,
            'argv': list(template), 'inputs': list(inputs), 'destructive': confirm is not None,
            'confirm': confirm, 'user_run': user_run, 'terminal_only': terminal_only, 'follow': follow,
            'superseded_by': superseded_by}


def run_action(running: bool, default_database, dev: list[dict], port) -> dict:
    """The start / restart flow: restart when this checkout's server runs, else start --detach."""
    inputs = [
        field('database', 'Database', 'choice', source='databases', required=False, allow_new=True,
              pattern=DATABASE_PATTERN, error=DATABASE_ERROR, default=default_database,
              hint=f'Enter for {default_database}, - for none' if default_database else 'Enter for none'),
        field('dev', 'Dev mode', 'choice', required=False, default='', hint='Enter for off', choices=dev),
        field('port', 'HTTP port', 'text', required=False, pattern=PORT_PATTERN, error=PORT_ERROR,
              default=str(port) if port else None,
              hint=f'Enter for {port}' if port else 'Enter to let start choose'),
    ]
    template = [option('database', '-d'), option('dev', '--dev'), option('port', '--http-port')]
    if running:
        return action(RUN_ACTION, 'Start / restart the server', 'restart', template, inputs)
    return action(RUN_ACTION, 'Start / restart the server', 'start', ['--detach', *template], inputs)


def actions(values: dict, class_filter: bool, run: dict | None = None) -> list[dict]:
    """The catalog's actions in menu order, argv still without the entry point prefix; run is the
    start / restart flow (run_action), first."""
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
        *([run] if run else []),
        action('server.start', 'Start the server in the background', 'start',
               ['--detach', option('database', '-d')],
               [database(required=False, hint='Enter to start without -d')], superseded_by=RUN_ACTION),
        action('server.restart', 'Restart the server', 'restart', [option('database', '-d')],
               [database(required=False, hint='Enter to keep the database of the running server')],
               superseded_by=RUN_ACTION),
        action('server.stop', 'Stop the server', 'stop'),
        action('server.logs', 'Show the end of the server log', None, kind='log'),
        action('server.follow', 'Follow the server log', None, kind='log', follow=True),
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
        action('modules.overview', "Show a module's overview from source", 'module-info', [value('module')],
               [MODULE]),
        *tests,
        action('maintenance.create_database', 'Create a database', 'create-database', [value('database')],
               [new_database()]),
        action('maintenance.drop_database', 'Move a database to the trash', 'drop-database',
               [value('database'), flag('terminate', '--terminate')], [database(), TERMINATE], confirm='database'),
        action('maintenance.trash', 'List trash', 'trash'),
        action('maintenance.trash_restore', 'Restore from trash', 'trash', ['restore', value('trash')],
               [field('trash', 'Trash name (as listed by List trash)', 'text', pattern=DATABASE_PATTERN,
                      error=DATABASE_ERROR)]),
        action('maintenance.trash_empty', 'Empty trash', 'gc', ['--apply', '--trash', option('older_than', '--older-than')],
               [field('older_than', 'Dropped at least this many days ago', 'text', required=False,
                      pattern=DAYS_PATTERN, error=DAYS_ERROR, hint='Enter for 7')], confirm='yes'),
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


def conf_database(conf: str):
    """The db_name of odoo.conf, or None when it sets none (Odoo writes False) or cannot be read."""
    paths = sibling('odoo_addons_path')
    try:
        value = (paths.read_option(conf, 'db_name') or '').strip()
    except paths.ConfError:
        return None
    return value if value and value != 'False' else None


def start_port(values: dict, record):
    """The HTTP port start or restart uses without an explicit one, by start's rules: the running
    server's; else the odoo.conf http_port (8069 when absent) for the main checkout, the first free
    one of the next 50 for a linked worktree. None when it cannot be known now."""
    if record:
        return record['port']
    paths = sibling('odoo_addons_path')
    try:
        conf_port = int(paths.option_value(values['ODOO_CONFIG'], 'http_port') or 8069)
        interface = paths.option_value(values['ODOO_CONFIG'], 'http_interface')
    except paths.ConfError:
        return None
    if values.get('CHECKOUT_KIND') != 'linked':
        return conf_port
    state = sibling('runtime_state')
    try:
        return state.free_port(interface, conf_port + 1, conf_port + 50, set())
    except state.PortError:
        return None


def importable(python: str, packages: list[str]) -> bool:
    try:
        result = subprocess.run([python, '-c', IMPORTABLE, *packages], stdin=subprocess.DEVNULL,
                                capture_output=True, cwd='/', timeout=20)
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def dev_choices(config, values: dict) -> list[dict]:
    """The closed dev mode choices of the series (odoo_versions.py): off, all, each feature, and
    reload,xml when both exist; those that turn on reload warn when the environment's Python cannot
    import any of the packages it needs."""
    version = values['ODOO_VERSION']
    capability = config.versions().capability
    features, every = capability(version, 'dev_features'), capability(version, 'dev_all')
    packages = capability(version, 'dev_reload_packages')
    warning = None
    if 'reload' in features and not importable(values['PYTHON'], packages):
        warning = (f"reload needs {' or '.join(packages)} importable by {values['PYTHON']}; none is, so Odoo will "
                   'log a warning and disable reload.')
    listed = [('', 'off'), ('all', f"all ({', '.join(every)})"), *((name, name) for name in features)]
    if 'reload' in features and 'xml' in features:
        listed.append(('reload,xml', 'reload,xml'))
    return [{'value': value, 'label': label,
             'warning': warning if value and 'reload' in (every if value == 'all' else value.split(',')) else None}
            for value, label in listed]


def checkout_state(values: dict, root: Path, modules: list[str]):
    """(the catalog's checkout, the live server record or None, what the menus remember)."""
    state = sibling('runtime_state')
    record, error, memory = None, None, {'last': None, 'database': None}
    try:
        record = state.live_record(root)
        memory = state.read_menu(root)
    except state.StateError as exc:
        error = str(exc)
    if record is not None:
        server = {'state': 'running', 'pid': record['pid'], 'port': record['port'],
                  'database': state.recorded_database(record), 'error': None}
    else:
        server = {'state': 'unknown' if error else 'stopped', 'pid': None, 'port': None, 'database': None,
                  'error': error}
    slug = values.get('CHECKOUT_SLUG', '')
    default = memory['database']
    if default is None and len(modules) == 1:
        default = f"{values['DEV_PREFIX']}{slug + '_' if slug else ''}{modules[0]}"
    named = conf_database(values['ODOO_CONFIG'])
    start = f"No database chosen: Odoo will use odoo.conf's db_name ({named})." if named else NO_CONF_DATABASE
    restart = (f"No database chosen: restart keeps the database of the running server ({server['database']})."
               if server['database'] else start)
    checkout = {'name': slug or 'main', 'server': server, 'default_database': default,
                'no_database': {'start': start, 'restart': restart}}
    return checkout, record, memory


def answers_fit(item: dict, answers, modules: list[str]) -> bool:
    """Whether remembered answers still fit the action's inputs as they are now."""
    if not isinstance(answers, dict) or set(answers) != {entry['id'] for entry in item['inputs']}:
        return False
    for entry in item['inputs']:
        answer = answers[entry['id']]
        if entry['kind'] == 'boolean':
            if not isinstance(answer, bool):
                return False
            continue
        if not isinstance(answer, str):
            return False
        if entry['choices'] is not None:
            if answer not in [choice['value'] for choice in entry['choices']]:
                return False
        elif not answer:
            if entry['required']:
                return False
        elif entry['source'] == 'modules' and answer not in modules:
            return False
        elif entry['pattern'] and not re.fullmatch(entry['pattern'], answer):
            return False
    return True


def short_answers(item: dict, answers: dict) -> str:
    """Listed values as they are, other values after their input id, true booleans as their id."""
    parts = []
    for entry in item['inputs']:
        answer = answers.get(entry['id'])
        if answer is True:
            parts.append(entry['id'])
        elif isinstance(answer, str) and answer:
            parts.append(answer if entry['source'] else f"{entry['id']} {answer}")
    return ', '.join(parts)


def last_action(memory: dict, listed: list[dict], modules: list[str]):
    """The catalog's last: the remembered action while it still applies (never user-run,
    terminal-only or the live log), else None."""
    last = memory['last']
    item = next((entry for entry in listed if last and entry['id'] == last['action']), None)
    if item is None or item['user_run'] or item['terminal_only'] or item['follow']:
        return None
    if not answers_fit(item, last['answers'], modules):
        return None
    short = short_answers(item, last['answers'])
    return {'action': item['id'], 'answers': last['answers'],
            'label': f"Repeat: {item['label']}{f' ({short})' if short else ''}"}


def catalog(config, log_dirs, root: Path) -> dict:
    values = config.load(root)
    entrypoint = config.variable('ENTRYPOINT') or str(Path(__file__).resolve().parent.parent / 'oasis')
    prefix = [entrypoint, '--project', str(root)]
    server_log = str(log_dirs.server_log(root, values.get('CHECKOUT_KIND', ''), values.get('CHECKOUT_MAIN_ROOT', ''),
                                         values.get('LOGS_DIR', ''), values.get('CHECKOUT_SLUG', '')))
    class_filter = config.versions().capability(values['ODOO_VERSION'], 'test_class_filter')
    modules = addon_modules(values.get('ADDON_ROOTS', ''))
    checkout, record, memory = checkout_state(values, root, modules)
    run = run_action(record is not None, checkout['default_database'], dev_choices(config, values),
                     start_port(values, record))
    listed = []
    for item in actions(values, class_filter, run):
        if item['kind'] == 'log':
            item['argv'] = ['tail', '-n', LOG_LINES, *(['-f'] if item['follow'] else []), server_log]
        else:
            item['argv'] = [*prefix, item['command'], *item['argv']]
        listed.append(item)
    return {
        'catalog_version': CATALOG_VERSION,
        'project': str(root),
        'entrypoint': entrypoint,
        'server_log': server_log,
        'sources': {'modules': {'choices': modules},
                    'databases': {'argv': [*prefix, 'list-databases'], 'waiting': WAITING}},
        'groups': [{'id': id, 'label': label} for id, label in GROUPS],
        'actions': listed,
        'checkout': checkout,
        'last': last_action(memory, listed, modules),
    }


def header_lines(data: dict) -> list[str]:
    """The checkout, its server and the default database of the start / restart flow."""
    checkout = data['checkout']
    server = checkout['server']
    if server['state'] == 'running':
        line = f"server: running on port {server['port']} (pid {server['pid']})"
    elif server['state'] == 'stopped':
        line = 'server: stopped'
    else:
        line = f"server: unknown ({server['error']})" if server['error'] else 'server: unknown'
    return [f"checkout: {checkout['name']}", line, f"default database: {checkout['default_database'] or 'none'}"]


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
    def __init__(self, data: dict, program: str, remember=None):
        self.data = data
        self.program = program
        self.databases = None
        # Records the action that ran (runtime_state.remember with the project bound), or None.
        self.remember = remember

    def ask(self, prompt: str) -> str:
        print(prompt, end='', flush=True)
        line = sys.stdin.readline()
        if not line:
            print('\nNo input: nothing ran.', flush=True)
            raise Cancelled(1)
        return line.strip()

    def pick(self, title: str, labels: list[str], prompt: str, repeat: str | None = None) -> int | None:
        """A 0-based index chosen by number; q quits; with repeat (its label, listed first), r gives None."""
        if title:
            print(title)
        if repeat:
            print(f'  r) {repeat}')
        for number, label in enumerate(labels, 1):
            print(f'  {number}) {label}')
        while True:
            answer = self.ask(prompt)
            if answer == 'q':
                raise Cancelled(0)
            if repeat and answer == 'r':
                return None
            if answer.isdigit() and 1 <= int(answer) <= len(labels):
                return int(answer) - 1
            print(f"Choose a number from 1 to {len(labels)}, {'r ' if repeat else ''}or q.")

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

    def choose(self, item: dict) -> str:
        """A closed choice by number; Enter takes the default. Its warning, if any, is shown."""
        choices = item['choices']
        print(item['label'])
        for number, choice in enumerate(choices, 1):
            print(f"  {number}) {choice['label']}")
        prompt = f"{item['label']} (number{', ' + item['hint'] if item['hint'] else ''}): "
        while True:
            answer = self.ask(prompt)
            if not answer:
                chosen = next((choice for choice in choices if choice['value'] == item['default']), None)
                if chosen is not None:
                    break
            elif answer.isdigit() and 1 <= int(answer) <= len(choices):
                chosen = choices[int(answer) - 1]
                break
            print(f'Choose a number from 1 to {len(choices)}.')
        if chosen['warning']:
            print(f"Warning: {chosen['warning']}")
        return chosen['value']

    def answer(self, item: dict, answers: dict):
        label = item['label']
        if item['choices'] is not None:
            return self.choose(item)
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
                    # A choice's default is a value; a text input's only says what the command does.
                    return (item['default'] or '') if item['kind'] == 'choice' else ''
                print('A value is required.')
                continue
            if answer == '-' and not item['required'] and item['kind'] == 'choice' and item['default']:
                return 
            # A listed value is taken as written, even one made of digits (a database named 2024).
            if answer in listed:
                return answer
            if item['kind'] == 'choice' and answer.isdigit():
                # Otherwise a number picks from the list; it never becomes a name.
                if listed and 1 <= int(answer) <= len(listed):
                    return listed[int(answer) - 1]
                if not item['allow_new']:
                    print(f'Choose a number from 1 to {len(listed)}, or a name from the list.')
                elif listed:
                    print(f'Choose a number from 1 to {len(listed)}, or type a name.')
                else:
                    print(f'No {label.lower()} is listed: type a name.')
                continue
            if item['kind'] == 'choice' and not item['allow_new']:
                print(f'Choose a number from 1 to {len(listed)}, or a name from the list.')
                continue
            if item['pattern'] and not re.fullmatch(item['pattern'], answer):
                print(item['error'])
                continue
            return answer

    def run(self) -> int:
        print(f"{self.program} menu: {self.data['project']}")
        for line in header_lines(self.data):
            print(line)
        groups = self.data['groups']
        last = self.data.get('last')
        picked = self.pick('', [entry['label'] for entry in groups],
                           'Group (r to repeat, q to quit): ' if last else 'Group (q to quit): ',
                           last['label'] if last else None)
        answers = None
        if picked is None:
            chosen = next(entry for entry in self.data['actions'] if entry['id'] == last['action'])
            answers = dict(last['answers'])
        else:
            group = groups[picked]
            members = [entry for entry in self.data['actions']
                       if entry['group'] == group['id'] and not entry.get('superseded_by')]
            chosen = members[self.pick(group['label'], [entry['label'] for entry in members],
                                       'Action (q to quit): ')]
        if chosen['kind'] == 'log' and not Path(self.data['server_log']).is_file():
            print(f"No server log yet: {self.data['server_log']}")
            return 1
        if answers is None:
            answers = {}
            for item in chosen['inputs']:
                answers[item['id']] = self.answer(item, answers)
        else:
            # A repeat shows what its choices warn about, as when they were chosen.
            for item in chosen['inputs']:
                for choice in item['choices'] or []:
                    if choice['value'] == answers.get(item['id']) and choice['warning']:
                        print(f"Warning: {choice['warning']}")
        argv = build(chosen, answers)
        print('Command: ' + shlex.join(argv), flush=True)
        if chosen['follow']:
            # Until Ctrl+C, which ends tail too (the same process group): the normal way out.
            print(f"Following {self.data['server_log']}; press Ctrl+C to stop.", flush=True)
            try:
                status = subprocess.run(argv).returncode
            except KeyboardInterrupt:
                print('\nStopped following the server log.', flush=True)
                return 0
            return status if status >= 0 else 128 - status
        if chosen['confirm'] == 'database':
            if self.ask('Type the database name to confirm: ') != answers.get('database'):
                print('Not confirmed: nothing ran.')
                return 1
        elif chosen['confirm'] == 'yes':
            if self.ask('Type yes to confirm: ') != 'yes':
                print('Not confirmed: nothing ran.')
                return 1
        elif chosen['command'] in SERVER_COMMANDS:
            if not answers.get('database'):
                print(self.data['checkout']['no_database'][chosen['command']])
            if self.ask('Run this command? [y/N]: ').lower() not in ('y', 'yes'):
                print('Not confirmed: nothing ran.')
                return 1
        status = subprocess.run(argv).returncode
        if self.remember and not (chosen['user_run'] or chosen['terminal_only']):
            try:
                self.remember(chosen['id'], answers)
            except Exception as exc:  # noqa: BLE001 - the command already ran; only the memory failed
                print(f'Could not remember this action: {exc}', file=sys.stderr)
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
    state = sibling('runtime_state')
    try:
        return Terminal(data, program, lambda id, answers: state.remember(root, id, answers)).run()
    except Cancelled as exc:
        return exc.args[0]
    except KeyboardInterrupt:
        print('\nInterrupted: nothing more runs.')
        return 130


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
