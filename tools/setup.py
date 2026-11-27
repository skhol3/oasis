#!/usr/bin/env python3
"""Set up a checkout for oasis (`oasis setup`, v0.14.0 S1, S6, S7, S9, S10).

Tier A in the agent policy (tools/policy.py): --apply writes the project's and the machine's
configuration, creating only what is missing, so an agent runs it alone. Without --apply it prints
the plan and changes nothing. It infers what it can (the checkout, the Odoo series from the module
manifests, the source from the machine file), asks on a terminal what it cannot (every answer also
has a flag and an id for --answer/--answers; without a terminal a missing answer is an open question
of the plan and --apply refuses naming its flag, v0.16.0 S3), adopts what exists
and never overwrites: an existing workspace file, odoo.conf, compose file, environment file,
requirement inputs, locks and environment are kept, and only the missing pieces are created.
Without a workspace file, the workspace is the checkout itself: oasis-workspace.toml at its root
and config/, data/, logs/ and the environment under .oasis/, both excluded in .git/info/exclude
(never the tracked .gitignore); --workspace <dir> chooses another directory at or above the
checkout. The Odoo source goes to the machine file, never to a new workspace file. The locks are
compiled with tools/locks.py, as bootstrap does, then the environment is created with uv and
synced. A new environment file (mode 0600) holds the database account (v0.16.0 S2): ODOO_DB_USER
oasis_<name> and a random ODOO_DB_PASSWORD (secrets.token_urlsafe), or the db_user and db_password a
kept odoo.conf sets; the compose service and Odoo both read it (tools/db_account.py), odoo.conf stays
password-free, and the password is never printed. An existing environment file gets the same account
written to the variables it assigns an empty value (as older setups wrote them), every other byte kept,
mode 0600; one that assigns neither is left unchanged with a WARN line. A kept odoo.conf whose db_user
and db_password the environment file holds (or now gets) loses those lines only, every other byte kept:
the account moves to the single file; when the file holds other values or lacks them, the plan warns and
both files are kept.

In a checkout of a series its workspace file has no section for (v0.15.0 S5), setup appends a
[series."<x.y>"] section to that file (a version 1 file becomes version 2, that line only) and plans
the files of that series, adopting a folder that already holds them (series_plan).

--environment <dir> (v0.15.0 S7) adopts an existing environment instead of creating one: its Python is
read from its pyvenv.cfg (never run) and must be one the series supports; setup never creates, syncs or
deletes it, and a rollback never touches it. The project's own requirement files in an adopted series
folder (requirements-extra.txt, requirements-overrides.txt) are referenced, never copied or edited:
runtime.in includes the first with -r after Odoo's requirements, and <requirements>/overrides.txt
includes the second, which tools/locks.py passes to uv pip compile as --override. A new runtime.in also
requires what the series needs that its source's requirements do not list (v0.15.0 S9:
odoo_versions.py runtime_requirements, setuptools<81 on 15.0), before the project's own.

When setup would create the environment (v0.15.0 S8: a new workspace, or a new series section) without
--environment or --python, a terminal asks to create it or to adopt an existing one (then as --environment),
and the Python of a new one among those the series supports; --python <x.y> answers that without asking.
Without a terminal nothing is asked and the plan is the same as before. Every question comes before any
change: end of input refuses (exit 2), Ctrl-C exits 130, and nothing is changed.

v0.16.0 S3 (docs/setup.md#questions-and-answers): --plan --json prints the plan as one JSON object
(plan_document); --answer <id>=<value> and --answers <file.json> answer the questions by id (answered);
a new runtime.in gets the questions of the problems tools/known_problems.py anticipates (anticipated):
python-ldap against OpenLDAP 2.6 and the modules' external_dependencies. v0.16.0 S6: a new workspace file asks
the question development (development_choice) and gets [development] with administrator_login = 'admin' unless
the answer is none; the next steps name start-database, never the docker compose command with the env file.
"""
import configparser
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import secrets
import socket
import subprocess
import sys
import tomllib

VALUE_OPTIONS = ('--series', '--community', '--enterprise', '--workspace', '--name', '--config-dir', '--environment',
                 '--python', '--answers')
REPEATED_OPTIONS = ('--exception', '--answer')
FLAG_OPTIONS = ('--apply', '--plan', '--no-enterprise', '--json')
# Options of the plan itself, accepted with an existing configuration too (the answers become flags first).
PLAN_OPTIONS = ('--apply', '--plan', '--json')
# Options that only answer the questions of a new configuration (an existing one is only filled in).
SOURCE_OPTIONS = ('--community', '--enterprise', '--no-enterprise')
# Options that only apply when setup adds a series section to an existing workspace file, and every
# option accepted then.
SECTION_OPTIONS = ('--exception', '--config-dir')
SERIES_PLAN_OPTIONS = (*PLAN_OPTIONS, '--environment', '--python', *SOURCE_OPTIONS, *SECTION_OPTIONS)
# The project's own requirement files that an adopted series folder may hold (S7): its extra requirements
# (runtime.in includes them with -r) and its pins that replace Odoo's (overrides.txt includes them).
PROJECT_REQUIREMENTS = ('requirements-extra.txt', 'requirements-overrides.txt')
# A pyvenv.cfg Python version: `version = 3.8.20` (venv), `version_info = 3.12.1` (uv, virtualenv).
PYVENV_VERSION = re.compile(r'([0-9]+)\.([0-9]+)(?:[.+a-z].*)?')
# The workspace_version line a version 1 file must have, once, to be converted (only the 1 changes).
VERSION_LINE = re.compile(r'(?m)^(workspace_version[ \t]*=[ \t]*)(1)([ \t]*(?:#[^\r\n]*)?\r?)$')
SECTION_COMMENT = ('# Added by oasis setup: what differs for the Odoo {series} checkouts '
                   '(docs/setup.md#another-odoo-series).\n')
COMPOSE_NAMES = ('compose.yml', 'compose.yaml', 'docker-compose.yml', 'docker-compose.yaml')
# The checkout file setup writes for a linked worktree whose directory name gives a slug over 20 characters.
CHECKOUT_SLUG = ('# Written by oasis setup: the database namespace of this worktree; its directory name {name} gives '
                 '{raw}, over 20 characters.\n[tooling]\ncheckout_slug = {slug}\n')
NAME = re.compile(r'[a-z][a-z0-9_]{1,19}')
NAME_RULE = '2 to 20 lowercase letters, digits or underscores, starting with a letter'
PORTS = range(5432, 5532)
# The port an odoo.conf without db_port connects to: PostgreSQL's default.
POSTGRES_PORT = 5432
LAYOUT = '.oasis'
EXCLUDES = ('/oasis-workspace.toml', f'/{LAYOUT}/')
DIRECTORY_MODE = 0o700
DRY_RUN = 'dry run: nothing changed; run with --apply to set up'
OPEN_PLAN = ('nothing changed: answer the open questions above (docs/setup.md#questions-and-answers), then run with '
             '--apply to set up')
# The questions setup asks (v0.16.0 S3): the ones a flag answers, and those of the problems it anticipates.
QUESTION_FLAGS = {'series': '--series', 'community': '--community', 'environment': '--environment',
                  'python': '--python', 'workspace': '--workspace'}
QUESTION_ID = re.compile(r'series|community|enterprise|environment|python|workspace|series_exceptions|python_ldap'
                         r'|development|requirement:[a-z0-9][a-z0-9-]*')
QUESTION_IDS = ('series, community, enterprise, environment, python, workspace, series_exceptions, python_ldap, '
                'development and requirement:<name>')
# The [development] table of a new workspace (v0.16.0 S6, the question development): init-dev-database needs its
# administrator_login; the administrator's password is generated (tools/dev_users.py). An existing workspace without
# one gets a next step that names these lines.
DEVELOPMENT = {'administrator_login': 'admin'}
DEVELOPMENT_COMMENT = ('# The administrator of the databases init-dev-database creates; its password is generated '
                       '(docs/dev-database.md).\n')
# A clone in <project>/code/<repo> or <project>/codigo/<repo> gets <project> as its recommended workspace (v0.16.0
# S4.11), unless <project> holds one of these: then it is not a project folder of its own.
CODE_FOLDERS = ('code', 'codigo')
PROJECT_MARKERS = ('.git', 'oasis-checkout.toml', '.odoo19-agent.toml', '__manifest__.py', 'odoo-bin')
WORKSPACE_HEADER = ('# Written by oasis setup. Paths are relative to this file, addons_paths to each checkout;\n'
                    '# the Odoo source comes from the machine file (docs/workspace-file.md#machine-file).\n')
MACHINE_HEADER = ('# Written by oasis setup: the Odoo source of each series on this machine '
                  '(docs/workspace-file.md#machine-file).\n')
ENV_FILE = ('# Written by oasis setup: the PostgreSQL account of the compose service and of Odoo '
            '(docs/setup.md#the-database-account).\n# No oasis command needs it read, copied or typed. Never commit '
            'this file.\n{user}\n{password}\n')
# An env file value docker compose reads as written: unquoted, else in single quotes (no interpolation).
PLAIN_VALUE = re.compile(r'''[^\s'"#$\\]+''')
# An option line of odoo.conf (at the start of the line; an indented line continues the option above).
OPTION_LINE = re.compile(r'([^\s;#=:\[][^=:]*?)\s*[=:]')
CONF = '''; Written by oasis setup. Path-free: oasis passes --addons-path and --data-dir on the command line.
; db_user and db_password stay empty: oasis passes ODOO_DB_USER and ODOO_DB_PASSWORD of {env_file} to Odoo as PGUSER and PGPASSWORD.
[options]
db_host = 127.0.0.1
db_port = {port}
db_user =
db_password =
'''
COMPOSE = '''# Written by oasis setup: the PostgreSQL service of this workspace. oasis runs it as
# docker compose --env-file <env_file> -f <this file>; the account comes from the environment file.
name: {name}
services:
  {service}:
    image: postgres:{postgres}
    environment:
      POSTGRES_DB: postgres
      POSTGRES_USER: ${{ODOO_DB_USER}}
      POSTGRES_PASSWORD: ${{ODOO_DB_PASSWORD}}
      ODOO_DB_USER: ${{ODOO_DB_USER}}
      ODOO_DB_PASSWORD: ${{ODOO_DB_PASSWORD}}
    ports:
      - '127.0.0.1:{port}:5432'
    volumes:
      - db:/var/lib/postgresql/data
    healthcheck:
      test: ['CMD-SHELL', 'pg_isready -U "$${{POSTGRES_USER}}" -d postgres']
      interval: 2s
      retries: 30
volumes:
  db:
'''
RUNTIME_IN = '# Written by oasis setup: the requirements of the Odoo source.\n-r {source}/requirements.txt\n'
DEV_IN = ('# Written by oasis setup: the runtime requirements within their lock; add development tools '
          'below.\n-c runtime.txt\n-r runtime.in\n'
          '# HttpCase browser tests (tours) need it: without it Odoo skips them and the run still passes.\n'
          'websocket-client\n')
# What the series needs that its source's requirements do not list (odoo_versions.py runtime_requirements,
# v0.15.0 S9): each below a comment with its reason.
RUNTIME_SERIES = '# {reason}\n{requirement}\n'
RUNTIME_EXTRA = "# The project's own requirements (oasis setup found them in the series folder).\n-r {extra}\n"
OVERRIDES_TXT = ("# Written by oasis setup: the project's pins that replace Odoo's, given to uv pip compile as "
                 '--override for runtime.txt and dev.txt.\n-r {overrides}\n')
OVERRIDES_PINS = ("# Written by oasis setup: pins that replace Odoo's, given to uv pip compile as --override for "
                  'runtime.txt and dev.txt.\n')
# An answered anticipated problem (v0.16.0 S3): a pin of overrides.txt, a requirement of runtime.in.
ANSWERED_PIN = '# {reason}\n{pin}\n'
RUNTIME_MODULE = '# The module {module} requires it (external_dependencies).\n{requirement}\n'
HELP = '''
Sets up the checkout (--project, else the git top level of the current directory) for oasis.
Without --apply it prints the plan and changes nothing; --plan asks for that plan explicitly and
can never apply. With --apply it creates only what is missing and keeps everything that exists:
  - the machine file's [series."<x.y>"] entry with the Odoo source (--community, --enterprise or
    --no-enterprise; asked on a terminal), when the machine file has none; an existing entry is
    used and never edited;
  - oasis-workspace.toml (no source keys; database prefixes from the checkout's name or --name),
    by default at the checkout's root with config/, data/, logs/ and the environment under .oasis/,
    both excluded from git in .git/info/exclude; --workspace <dir> puts them in <dir>, which must
    be at or above the checkout; for a clone at <project>/code/<repo> or <project>/codigo/<repo>
    (<project> holding no .git, oasis-checkout.toml, legacy profile, __manifest__.py or odoo-bin)
    the question workspace recommends <project> (applied without a terminal) and offers the clone;
    an existing workspace file is adopted, and one setup created in the clone moves with
    --workspace <dir> above it (the file, its relative paths rewritten, .oasis/ and the clone's
    exclude entries; verified once moved, every change undone on failure);
  - a path-free, password-free odoo.conf, a compose file with the PostgreSQL service, the environment
    file with the generated account (ODOO_DB_USER oasis_<name> and a random ODOO_DB_PASSWORD, or the
    db_user and db_password a kept odoo.conf sets; mode 0600, never printed), which the service and
    every Odoo command read, runtime.in (the source's requirements, and what the series needs besides
    them: setuptools<81 on 15.0) and dev.in; a kept environment file gets the account in the variables it
    assigns an empty value, every other byte kept, mode 0600 (one that assigns neither is left unchanged,
    with a WARN line);
  - the move of a kept odoo.conf's db_user and db_password to the environment file: removed from odoo.conf
    (those lines only) when the environment file holds the same values; otherwise a WARN line, and both
    files are kept;
  - the locks (uv pip compile, as bootstrap --apply) and the Python environment (uv venv, uv pip sync).
The series comes from the module manifests (<series>.x.y.z), else from the machine file's single series,
else --series. It ends with the next steps; the database service step is start-database, which names
no env file (an agent harness may refuse a command that names one).

In a checkout of a series the existing workspace file has no section for (its oasis-checkout.toml
odoo_version, else its module manifests, the modules of --exception <module> left out), it appends a
[series."<x.y>"] section to that file (a workspace_version 1 file becomes 2, that line only) and
creates that series' missing files: by default in <config folder>/<x.y>/, or in a folder that already
holds its odoo.conf or compose file (<config folder>/odoo-<major>/, ...; --config-dir <dir> names one),
which is adopted: the data_dir its kept odoo.conf sets becomes the section's data_dir, and an existing
logs/<folder name> next to the folder's parent (logs/odoo-15 for config/odoo-15) its logs; otherwise
they go to <data_dir>/<x.y> and <logs>/<x.y>. --exception (repeatable) writes series_exceptions. A
kept odoo.conf or compose file on a port another series of the workspace uses is refused; a failed verification, compile or uv venv then
undoes every change, the workspace file's included. When that folder holds requirements-extra.txt or
requirements-overrides.txt, a new runtime.in includes the first after the Odoo requirements and a new
requirements/overrides.txt includes the second (uv pip compile --override); those files are never
copied or edited.

--environment <dir> (a new workspace, or a new series section) uses an existing environment, an absolute
directory with a pyvenv.cfg whose version is a Python the series supports (read, never run): setup
never creates, syncs or deletes it, and bootstrap --apply syncs it to the locks. Until then, doctor
--environment --full reports packages that do not match the locks as WARN locked_environment=drifted
(an environment setup or bootstrap creates is marked .oasis-created, and its drift is a FAIL).

When setup would create the Python environment (a new workspace, or a new series section) and neither
--environment nor --python is given, it asks on a terminal: Enter creates it, or the absolute path of an
existing environment uses that one, exactly as --environment does; for a new one it then asks its Python
among those the series supports (Enter: the default; any other answer is asked again). --python <x.y>
gives that Python without asking: one the series supports, never with --environment, and refused when
the environment already exists. Without a terminal nothing is asked and the environment gets the
configuration's Python. End of input or Ctrl-C at a question changes nothing (exit 2 or 130).

Questions and answers (docs/setup.md#questions-and-answers): every question has a flag, and
--answer <id>=<value> (repeatable) or --answers <file.json> (a JSON object {"<id>": "<value>"}) answers
it by its id: series, community, enterprise (a path or none), environment (create or a path), python,
workspace (the project folder or the clone), series_exceptions (add or no), python_ldap (yes or no),
development (add or none) and requirement:<name>. Without a terminal and without an answer, a question
whose answer setup cannot go without (series, community, enterprise) or one of an anticipated problem
is an open question: the plan lists it with its flag and --apply refuses, changing nothing; the
environment and its Python take the recommended answers, as before, and so does development.
A new workspace file gets the [development] table init-dev-database needs (the question development:
add, recommended, writes administrator_login = 'admin', whose password init-dev-database generates;
none leaves it out); a workspace file without one gets a next step that names its exact lines.
--plan --json prints the plan as one JSON object (inferred values and their origin, changes, questions; never a password).
Anticipated problems (a new runtime.in only): Odoo 15.0's python-ldap==3.4.0 on a machine with
OpenLDAP 2.6 without libldap_r (python_ldap: pin python-ldap==3.4.4 in a new overrides.txt), and each
external_dependencies python requirement of the checkout's modules that the requirements do not list
(add it to runtime.in; no recommended answer for a name that may be only an import name, such as cv2)
or that an Odoo pin does not satisfy (pin the lowest version it accepts in a new overrides.txt). uv 0.13 and later run with UV_LEGACY_TAR_BACKEND=1 (old source archives).

In any checkout, modules whose manifest declares another series are the question series_exceptions:
add (recommended) lists them in a [series."<x.y>"] section (a version 1 file becomes version 2), no
refuses as the series guard does; open without an answer. A linked worktree whose directory name gives
a checkout slug over 20 characters gets an oasis-checkout.toml with checkout_slug cut to 20 (_<n> when
another checkout uses it); a checkout file with its own [tooling] table is never edited.
'''


class Refused(Exception):
    """A refusal before any change: exit 2 with the message."""


class Interrupted(Exception):
    """Ctrl-C at a question, before any change: exit 130."""


def sibling(name: str):
    """A packaged helper loaded from its file (python3 -I keeps the tools directory off sys.path)."""
    spec = importlib.util.spec_from_file_location(f'oasis_setup_{name}', Path(__file__).with_name(f'{name}.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


config, migrate, locks, db_account = sibling('config'), sibling('migrate'), sibling('locks'), sibling('db_account')
known_problems, environment_origin = sibling('known_problems'), sibling('environment_origin')


def usage() -> str:
    return (f'Usage: {config.usage_name()} setup [--series <x.y>] [--community <dir>] '
            '[--enterprise <dir> | --no-enterprise] [--workspace <dir>] [--name <name>] '
            '[--exception <module>]... [--config-dir <dir>] [--environment <dir> | --python <x.y>] '
            '[--answer <id>=<value>]... [--answers <file.json>] [--apply | --plan [--json]]')


def parse_arguments(arguments: list[str]) -> dict | None:
    """The options in argument order, or None for a usage error (no abbreviations)."""
    options, index = {}, 0
    while index < len(arguments):
        argument = arguments[index]
        key, equals, value = argument.partition('=')
        if argument in FLAG_OPTIONS and argument not in options:
            options[argument] = True
        elif equals and key in REPEATED_OPTIONS:
            options.setdefault(key, []).append(value)
        elif argument in REPEATED_OPTIONS and index + 1 < len(arguments):
            index += 1
            options.setdefault(argument, []).append(arguments[index])
        elif equals and key in VALUE_OPTIONS and key not in options:
            options[key] = value
        elif argument in VALUE_OPTIONS and argument not in options and index + 1 < len(arguments):
            index += 1
            options[argument] = arguments[index]
        else:
            return None
        index += 1
    if ('--apply' in options and ('--plan' in options or '--json' in options)) or (
            '--enterprise' in options and '--no-enterprise' in options):
        return None
    return options


def answered(options: dict) -> dict:
    """{question id: (answer, where it came from)} of --answers and --answer (v0.16.0 S3), both removed from
    options; an answer to a question a flag answers becomes that flag (refused when the flag is given too), and
    environment=create is kept as an answer."""
    answers = {}
    if '--answers' in options:
        path = options.pop('--answers')
        try:
            document = json.loads(Path(path).read_text(encoding='utf-8'))
        except (OSError, UnicodeError, ValueError):
            document = None
        if not isinstance(document, dict) or not all(isinstance(value, str) for value in document.values()):
            raise Refused(f'--answers {path} must be a JSON object of question ids and text answers.')
        answers = {key: (value, f'--answers {path}') for key, value in document.items()}
    for item in options.pop('--answer', []):
        key, equals, value = item.partition('=')
        if not equals or not key:
            raise Refused(f'--answer {item}: use --answer <question id>=<value>.')
        if key in answers:
            raise Refused(f'The question {key} is answered twice: by {answers[key][1]} and by --answer.')
        answers[key] = (value, '--answer')
    for key, (value, source) in list(answers.items()):
        if not QUESTION_ID.fullmatch(key):
            raise Refused(f'{source}: unknown question {key} (setup asks {QUESTION_IDS}).')
        if key == 'enterprise':
            flags, flag, given = (('--enterprise', '--no-enterprise'), '--no-enterprise' if value == 'none'
                                  else '--enterprise', True if value == 'none' else value)
        elif key == 'environment' and value == 'create':
            flags, flag, given = ('--environment',), None, None
        elif key in QUESTION_FLAGS:
            flags, flag, given = (QUESTION_FLAGS[key],), QUESTION_FLAGS[key], value
        else:
            continue
        clash = next((other for other in flags if other in options), None)
        if clash is not None:
            raise Refused(f'The question {key} is answered twice: by {clash} and by {source}.')
        if flag is not None:
            options[flag] = given
            del answers[key]
    return answers


class Open(Exception):
    """A question setup cannot go on without, with neither a terminal nor an answer: the plan stops there and
    lists it (v0.16.0 S3); --apply refuses with its refusal."""


class Questions:
    """What setup cannot infer: asked on a terminal, else an open question of the plan naming the flag that
    answers it (v0.16.0 S3). It also holds what the plan inferred so far and every question it met, answered
    or open, for --json: a plan that stops at an open question still reports them."""

    def __init__(self, answers=None, interactive=None):
        self.interactive = (sys.stdin.isatty() and sys.stderr.isatty()) if interactive is None else interactive
        self.answers = answers or {}
        self.used = set()
        self.lines, self.inferred, self.listed, self.refusals = [], {}, [], {}

    def infer(self, key: str, value, origin: str):
        self.inferred[key] = {'value': value if value is None or isinstance(value, int) else str(value),
                              'origin': origin}

    def met(self, question: dict, answer, origin, refusal: str = ''):
        self.listed.append({**question, 'answer': answer, 'origin': origin})
        if answer is None:
            self.refusals[question['id']] = refusal

    def open(self) -> list[str]:
        return [question['id'] for question in self.listed if question['answer'] is None]

    def ask(self, prompt: str, refusal: str, question: dict | None = None) -> str:
        """The answer, stripped. End of input refuses with refusal and Ctrl-C raises Interrupted: every
        question comes before any change, so either leaves everything as it was. Without a terminal, a
        question is open (Open) and anything else refused."""
        if not self.interactive:
            if question is not None:
                self.met(question, None, None, refusal)
                raise Open(refusal)
            raise Refused(refusal)
        sys.stderr.write(prompt)
        sys.stderr.flush()
        try:
            line = sys.stdin.readline()
        except KeyboardInterrupt:
            raise Interrupted() from None
        if not line:
            raise Refused(refusal)
        return line.strip()

    def say(self, text: str):
        sys.stderr.write(text)
        sys.stderr.flush()

    def choose(self, question: dict) -> str | None:
        """The answer to a question of an anticipated problem (v0.16.0 S3): --answer or --answers, else asked
        on a terminal (Enter: the recommended one, when it has one), else None: an open question that --apply
        refuses."""
        values = [option['value'] for option in question['options']]
        listed = ', '.join(values[:-1]) + f' or {values[-1]}'
        recommended = question['recommended']
        if question['id'] in self.answers:
            answer, source = self.answers[question['id']]
            self.used.add(question['id'])
            if answer not in values:
                raise Refused(f'Invalid answer {answer} for {question["id"]}: answer {listed}.')
            self.met(question, answer, f'from {source.split()[0]}')
            return answer
        refusal = (f'{question["text"]} Answer with {question["flag"]} '
                   + (f'(recommended: {recommended}).' if recommended is not None else '(no recommended answer).'))
        if not self.interactive:
            self.met(question, None, None, refusal)
            return None
        while True:
            answer = self.ask(f'{question["text"]} ({"/".join(values)})'
                              + (f' [Enter: {recommended}]: ' if recommended is not None else ': '),
                              f'No answer for {question["id"]} (end of input): nothing changed; pass '
                              f'{question["flag"]}.') or recommended
            if answer in values:
                return answer
            self.say(f'Answer {listed}, or Enter for {recommended}.\n' if recommended is not None
                     else f'Answer {listed}.\n')


# -- inference -------------------------------------------------------------------------------------

def modules(root: Path) -> list[tuple[str, str | None]]:
    """(addon root relative to root, declared series or None) of every module manifest directly in
    root or one directory below it; hidden directories are skipped. The series is read as the series
    guard reads it (config.manifest_series: a series-style version of a known or plausible series)."""
    found = []
    for manifest in sorted([*root.glob('*/__manifest__.py'), *root.glob('*/*/__manifest__.py')]):
        if any(part.startswith('.') for part in manifest.relative_to(root).parts):
            continue
        declared = config.manifest_series(manifest)
        found.append((manifest.parent.parent.relative_to(root).as_posix(), declared[0] if declared else None))
    return found


def checkout_kind(root: Path) -> tuple[str, Path | None]:
    try:
        kind, _top, main = config.git_checkout(root)
    except config.GitFailed as exc:
        if config.dot_git(root) is None:
            return 'none', None
        raise Refused(f'Cannot read the git checkout {root}: {exc}.') from exc
    return kind, main


def read_machine() -> tuple[Path, bytes | None, dict]:
    """The machine file's path, its bytes (None when absent) and its document, checked like oasis
    reads it (trust and every key)."""
    path = config.machine_file()
    if path is None:
        raise Refused('Cannot place the machine file: there is no home directory; set XDG_CONFIG_HOME.')
    if not os.path.lexists(path):
        return path, None, {}
    try:
        config.machine_series(config.versions().supported()[0])
        raw = path.read_bytes()
        return path, raw, tomllib.loads(raw.decode('utf-8'))
    except config.InvalidConfig as exc:
        raise Refused(str(exc)) from exc
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise Refused(f'Cannot read {path}.') from exc


def choose_series(root, options, machine_document, questions) -> tuple[str, str]:
    supported = config.versions().supported()

    def checked(series, refusal=None):
        if series not in supported:
            raise Refused(refusal or f'Unsupported series {series}; supported: {", ".join(supported)}.')
        return series
    if '--series' in options:
        return checked(options['--series']), 'from --series'
    declared = sorted({series for _root, series in modules(root) if series})
    if len(declared) > 1:
        raise Refused(f'The module manifests of {root} declare several Odoo series ({", ".join(declared)}); '
                      'pass --series <x.y>.')
    if declared:
        return checked(declared[0], f'The module manifests of {root} declare Odoo {declared[0]}, which oasis '
                                    f'does not support (supported: {", ".join(supported)}).'), 'from the module manifests'
    tables = machine_document.get('series', {})
    if len(tables) == 1:
        return next(iter(tables)), 'from the machine file'
    answer = questions.ask(f'Odoo series (supported: {", ".join(supported)}): ',
                           f'Cannot infer the Odoo series of {root}: no module manifest declares one and the '
                           f'machine file has no single series; pass --series <x.y> (supported: {", ".join(supported)}).',
                           {'id': 'series', 'text': 'Odoo series of the checkout',
                            'options': [{'value': item, 'label': f'Odoo {item}'} for item in supported],
                            'recommended': None, 'flag': '--series <x.y>'})
    return checked(answer), 'answered'


def suggested_source(root: Path, series: str) -> Path | None:
    """An Odoo source of the series near the checkout, only ever offered, never chosen."""
    for ancestor in list(root.parents)[:4]:
        for candidate in (ancestor / 'odoo', ancestor / 'source' / 'odoo', ancestor / 'src' / 'odoo',
                          ancestor / series / 'odoo', ancestor / series / 'source' / 'odoo'):
            if config.release_is(candidate / 'odoo' / 'release.py', series):
                return candidate
    return None


def adopted_environment(value: str, series: str) -> tuple[Path, str]:
    """(the environment --environment names, resolved; its Python "3.<minor>"): read from its pyvenv.cfg
    (`version`, else `version_info`), never by running it, and within the series' range (S7)."""
    path = Path(value).resolve()
    cfg = path / 'pyvenv.cfg'
    if not cfg.is_file():
        raise Refused(f'--environment {path} is not a Python environment (no pyvenv.cfg).')
    try:
        text = cfg.read_text(encoding='utf-8')
    except (OSError, UnicodeError) as exc:
        raise Refused(f'Cannot read {cfg}.') from exc
    found = {}
    for line in text.splitlines():
        key, equals, written = line.partition('=')
        if equals:
            found.setdefault(key.strip(), written.strip())
    match = next((match for key in ('version', 'version_info')
                  if (match := PYVENV_VERSION.fullmatch(found.get(key, '')))), None)
    if match is None:
        raise Refused(f'--environment {path} has no Python version in its pyvenv.cfg (version or version_info).')
    python = f'{int(match.group(1))}.{int(match.group(2))}'
    if not config.versions().python_supported(series, python):
        low, high = config.versions().capability(series, 'python')
        raise Refused(f'--environment {path} has Python {python}, which Odoo {series} does not support '
                      f'({low} to {high}).')
    return path, python


def series_pythons(series: str) -> list[str]:
    """Every Python "3.<minor>" the series supports, oldest first (tools/odoo_versions.py python)."""
    low, high = (int(bound.split('.')[1]) for bound in config.versions().capability(series, 'python'))
    return [f'3.{minor}' for minor in range(low, high + 1)]


def chosen_python(options: dict, series: str) -> str | None:
    """The --python of the environment setup creates (S8), one the series supports, or None without it."""
    if '--python' not in options:
        return None
    value = options['--python']
    if not config.versions().python_supported(series, value):
        low, high = config.versions().capability(series, 'python')
        raise Refused(f'--python {value} is not a Python Odoo {series} supports ({low} to {high}).')
    return value


def environment_choice(options: dict, questions: Questions, series: str, environment: Path, default: str):
    """(the adopted environment or None, the Python of a new one or None) for the environment setup would
    create at environment with Python default (S8). --python is refused when that environment exists (it is
    kept: setup creates none). On a terminal, without --environment or --python, setup asks: Enter creates
    it, else the answer is adopted exactly as --environment adopts one (adopted_environment); for a new one
    it asks its Python among those the series supports (Enter: default), again after any other answer.
    Without a terminal nothing is asked: (None, None), the configuration's own Python."""
    exists = (environment / 'pyvenv.cfg').is_file()
    if '--python' in options and exists:
        raise Refused(f'--python {options["--python"]}: the environment {environment} exists and is kept; setup '
                      'creates no environment, so drop --python.')
    if exists or '--environment' in options or '--python' in options:
        if not exists:
            questions.used.add('environment')  # environment=create with --python: it is created
        return None, None
    pythons = series_pythons(series)
    create = questions.answers.get('environment')
    questions.used.add('environment')
    asked = [({'id': 'environment', 'text': f'Python environment for Odoo {series}: create {environment}, or use an '
                                            'existing environment',
               'options': [{'value': 'create', 'label': f'create {environment}'}], 'recommended': 'create',
               'flag': '--environment <dir>'}, 'create'),
             ({'id': 'python', 'text': f'Python of the new environment {environment}',
               'options': [{'value': python, 'label': f'Python {python}'} for python in pythons],
               'recommended': default, 'flag': '--python <x.y>'}, default)]
    if not questions.interactive:
        # Without a terminal the recommended answers apply, as before v0.16.0: the configuration's own Python.
        for question, answer in asked:
            questions.met(question, answer, f'from {create[1].split()[0]}' if create and question['id'] == 'environment'
                          else 'recommended (no terminal)')
        return None, None
    refusal = (f'No answer for the Python environment of Odoo {series} (end of input): nothing changed; pass '
               '--environment <dir> or --python <x.y>.')
    answer = '' if create else questions.ask(
        f'Python environment for Odoo {series}: Enter creates {environment}, or type the absolute path of an existing '
        'environment to use instead: ', refusal)
    if answer:
        if not os.path.isabs(answer) or not os.path.isdir(answer):
            raise Refused('--environment requires an absolute existing directory.')
        return adopted_environment(answer, series), None
    listed = ', '.join(pythons)
    while True:
        answer = questions.ask(f'Python of the new environment {environment}, one of {listed} [Enter: {default}]: ',
                               refusal)
        if not answer or answer in pythons:
            return None, answer or default
        questions.say(f'{answer} is not a Python Odoo {series} supports; answer one of {listed}, or Enter for '
                      f'{default}.\n')


def development_choice(questions: Questions, workspace: Path) -> bool:
    """Whether a new workspace file gets the [development] table init-dev-database needs (v0.16.0 S6): the question
    development, add (recommended; applied without a terminal and without an answer, as the environment's
    recommended answers are) or none."""
    login = migrate.toml_string(DEVELOPMENT['administrator_login'])
    question = {'id': 'development',
                'text': f'init-dev-database needs a [development] table in {workspace}: add one with '
                        f'administrator_login = {login} (its password is generated)?',
                'options': [{'value': 'add', 'label': f'add [development] with administrator_login = {login}'},
                            {'value': 'none', 'label': 'none: no [development] table (init-dev-database then needs '
                                                       'one added by hand)'}],
                'recommended': 'add', 'flag': '--answer development=<add|none>'}
    if question['id'] in questions.answers:
        return questions.choose(question) == 'add'
    if not questions.interactive:
        questions.met(question, 'add', 'recommended (no terminal)')
        return True
    answer = questions.choose(question)
    questions.met(question, answer, 'answered')
    return answer == 'add'


def directory_answer(value: str, label: str) -> Path:
    if not value or not os.path.isabs(value) or not os.path.isdir(value):
        raise Refused(f'{label} requires an absolute existing directory.')
    return Path(value).resolve()


def community_source(value: str, label: str, series: str) -> Path:
    path = directory_answer(value, label)
    if not config.release_is(path / 'odoo' / 'release.py', series):
        raise Refused(f'{label} {path} is not an Odoo {series} source (no odoo/release.py that declares it).')
    return path


def choose_sources(root, series, options, machine, questions):
    """(community, enterprise or None, its origins, the plan lines and actions of the machine entry)."""
    path, raw, document = machine
    table = f'[series.{json.dumps(series)}]'
    if series in document.get('series', {}):
        _path, values = config.machine_series(series)
        if 'community' not in values:
            raise Refused(f'The machine file {path} has {table} without community; setup never edits an '
                          'existing entry: add community there yourself.')
        for key, flag in (('community', '--community'), ('enterprise', '--enterprise'), ('enterprise', '--no-enterprise')):
            # Only a flag that disagrees with the entry is refused: --no-enterprise against an entry with
            # Enterprise, a path against an entry without that key or with another path.
            if flag not in options:
                continue
            if (key in values if flag == '--no-enterprise'
                    else key not in values or str(Path(options[flag]).resolve()) != values[key]):
                state = f'already sets {key} for {series}' if key in values else f'has {table} without {key}'
                raise Refused(f'The machine file {path} {state}; setup never edits an existing entry: drop {flag}, '
                              'or change the machine file yourself.')
        if not config.release_is(Path(values['community']) / 'odoo' / 'release.py', series):
            raise Refused(f'The machine file {path} sets community {values["community"]} for {series}, which is '
                          f'not an Odoo {series} source.')
        origin = 'from the machine file'
        return (Path(values['community']), Path(values['enterprise']) if 'enterprise' in values else None,
                (origin, origin), [f'kept {path}: {table} gives the Odoo source'], [], values.get('environments'))
    if '--community' in options:
        community, community_origin = community_source(options['--community'], '--community', series), 'from --community'
    else:
        found = suggested_source(root, series)
        answer = questions.ask(
            f'Odoo Community source for {series} (absolute path)' + (f' [Enter: {found}]' if found else '') + ': ',
            f'No Odoo Community source for {series} in the machine file {path}: pass --community <dir>'
            + (f'; found {found}, a suggestion only: pass it to use it' if found else '') + '.',
            {'id': 'community', 'text': f'Odoo Community source for {series} (absolute path)',
             'options': [{'value': str(found), 'label': 'found near the checkout'}] if found else [],
             'recommended': str(found) if found else None, 'flag': '--community <dir>'})
        community, community_origin = community_source(answer or str(found or ''), 'The answer', series), 'answered'
    if '--enterprise' in options:
        enterprise, enterprise_origin = directory_answer(options['--enterprise'], '--enterprise'), 'from --enterprise'
    elif '--no-enterprise' in options:
        enterprise, enterprise_origin = None, 'from --no-enterprise'
    else:
        answer = questions.ask(f'Odoo Enterprise source for {series} (absolute path, empty for none): ',
                               f'Enterprise or not for {series}: pass --enterprise <dir> or --no-enterprise.',
                               {'id': 'enterprise', 'text': f'Odoo Enterprise source for {series} (absolute path, or none)',
                                'options': [{'value': 'none', 'label': 'no Odoo Enterprise source'}],
                                'recommended': None, 'flag': '--enterprise <dir> | --no-enterprise'})
        enterprise = directory_answer(answer, 'The answer') if answer else None
        enterprise_origin = 'answered'
    entry = f'{table}\ncommunity = {migrate.toml_string(str(community))}\n'
    if enterprise is not None:
        entry += f'enterprise = {migrate.toml_string(str(enterprise))}\n'
    if raw is None:
        if path.parent.exists() and migrate.untrusted(path.parent):
            raise Refused(f'Refusing to write {path}: {migrate.untrusted(path.parent)}.')
        text = MACHINE_HEADER + entry
        lines = [f'create {path} (mode 0600):'] + [f'  {line}' for line in text.splitlines()]
        actions = [*directories(path.parent, set()), ('create', path, text.encode(), 0o600)]
        new = text.encode()
    else:
        separator = b'' if not raw.strip() else b'\n' if raw.endswith(b'\n') else b'\n\n'
        new = raw + separator + entry.encode()
        lines = [f'add {table} to {path}:'] + [f'  {line}' for line in entry.splitlines()]
        actions = [('extend', path, raw, new)]
    expected = {'community': str(community), **({'enterprise': str(enterprise)} if enterprise else {})}
    try:
        if tomllib.loads(new.decode('utf-8')).get('series', {}).get(series) != expected:
            raise ValueError
    except (ValueError, UnicodeError):
        raise Refused(f'Cannot add {table} to {path}: edit it yourself.') from None
    return community, enterprise, (community_origin, enterprise_origin), lines, actions, None


def project_folder(root: Path) -> Path | None:
    """<project> for a clone at <project>/code/<repo> or <project>/codigo/<repo> (CODE_FOLDERS) whose <project>
    holds no PROJECT_MARKERS and is trusted, else None."""
    folder = root.parent
    project = folder.parent
    if folder.name not in CODE_FOLDERS or project == folder:
        return None
    if any(os.path.lexists(project / marker) for marker in PROJECT_MARKERS) or migrate.untrusted(project):
        return None
    return project


def workspace_choice(root: Path, questions: Questions) -> Path:
    """The directory of a new workspace without --workspace (v0.16.0 S4.11): the clone itself, or, for a clone in
    a project folder (project_folder), the question workspace: that folder (recommended; without a terminal it
    applies, as the environment's recommended answers do) or the clone."""
    project = project_folder(root)
    if project is None:
        return root
    question = {'id': 'workspace', 'text': f'Workspace directory of {root}: the project folder {project} or the clone',
                'options': [{'value': str(project), 'label': f'the project folder above {root.parent.name}/'},
                            {'value': str(root), 'label': 'the clone'}],
                'recommended': str(project), 'flag': '--workspace <dir>'}
    if not questions.interactive:
        questions.met(question, str(project), 'recommended (no terminal)')
        return project
    while True:
        answer = questions.ask(f'Workspace directory: Enter puts it in {project} (the project folder above '
                               f'{root.parent.name}/), or type {root} to keep it in the clone: ',
                               f'No answer for the workspace directory (end of input): nothing changed; pass '
                               f'--workspace {project} or --workspace {root}.') or str(project)
        if answer in (str(project), str(root)):
            questions.met(question, answer, 'answered')
            return Path(answer)
        questions.say(f'Answer {project} or {root}, or Enter for {project}.\n')


def directories(target: Path, planned: set) -> list:
    """mkdir actions for target and its missing parents, outermost first, each planned once."""
    missing = []
    for directory in (target, *target.parents):
        if directory.exists() or directory in planned:
            break
        missing.append(directory)
    planned.update(missing)
    return [('mkdir', directory) for directory in reversed(missing)]


def free_port(taken=()) -> int:
    for port in PORTS:
        if port in taken:
            continue
        with socket.socket() as probe:
            try:
                probe.bind(('127.0.0.1', port))
            except OSError:
                continue
            return port
    raise Refused(f'No free port from {PORTS[0]} to {PORTS[-1]} on 127.0.0.1 for PostgreSQL.')


def git_exclude(root: Path) -> tuple[Path, list[str]]:
    """The checkout's info/exclude file and the EXCLUDES git does not ignore yet."""
    env = migrate.git_env()
    try:
        result = subprocess.run(['git', '-C', str(root), 'rev-parse', '--path-format=absolute', '--git-path',
                                 'info/exclude'], capture_output=True, text=True, env=env, timeout=30)
        if result.returncode != 0 or not result.stdout.strip():
            raise OSError(result.stderr.strip())
        missing = []
        for pattern in EXCLUDES:
            ignored = subprocess.run(['git', '-C', str(root), 'check-ignore', '-q', '--no-index', '--',
                                      pattern.lstrip('/')], capture_output=True, env=env, timeout=30)
            if ignored.returncode not in (0, 1):
                raise OSError('git check-ignore failed')
            if ignored.returncode == 1:
                missing.append(pattern)
    except (OSError, subprocess.SubprocessError) as exc:
        raise Refused(f'Cannot read the git exclude file of {root}: {exc}.') from exc
    return Path(result.stdout.strip()), missing


# -- plan ------------------------------------------------------------------------------------------

def make_plan(root: Path, options: dict, questions: Questions) -> dict:
    """Every line to print, every change to make and the steps after them; nothing is written."""
    kind, main = checkout_kind(root)
    lines = questions.lines
    lines.append(f'checkout: {root} ({"outside git" if kind == "none" else kind})')
    questions.infer('checkout', root, 'outside git' if kind == 'none' else kind)
    actions, planned = [], set()
    workspace = config.workspace_file(root)
    machine = read_machine()
    if workspace is not None and '--workspace' in options and workspace.parent == root:
        return move_plan(root, workspace, Path(options['--workspace']).resolve(), options, questions)
    if workspace is not None:
        target = section_target(root, workspace, options)
        if target is not None:
            return series_plan(root, kind, options, questions, workspace, machine, target, lines)
        checkout, slug_line, slug_action = slug_change(root, kind, main)
        try:
            document, base, workspace, name, origins, refusal = config.layered_configuration(root, checkout=checkout)
        except config.InvalidConfig as exc:
            raise Refused(str(exc)) from exc
        lines.append(f'workspace: {workspace} (existing)')
        if slug_line is not None:
            lines.append(slug_line)
            actions.append(slug_action)
        questions.infer('workspace', workspace.parent, 'existing')
        questions.infer('series', document['tooling']['version'], 'from the workspace file')
        try:
            values, missing_source = config.assignments(document, root, base, workspace, name,
                                                        missing_source=refusal), False
        except config.InvalidConfig as exc:
            if str(exc) != refusal:
                raise Refused(str(exc)) from exc
            values, missing_source = None, True
        for option in options:
            if option not in PLAN_OPTIONS and not (missing_source and option in SOURCE_OPTIONS):
                raise Refused(f'{option}: {root} is already configured by {workspace}; setup only fills what is '
                              'missing.')
        if missing_source:
            series = document['tooling']['version']
            community, enterprise, origin, machine_lines, machine_actions, _envs = choose_sources(
                root, series, options, machine, questions)
            lines += [f'community: {community} ({origin[0]})', f'enterprise: {enterprise or "none"} ({origin[1]})',
                      *machine_lines]
            infer_sources(questions, community, enterprise, origin)
            actions += machine_actions
            document['tooling']['community'] = str(community)
            if enterprise is not None and 'enterprise' not in document['tooling']:
                document['tooling']['enterprise'] = str(enterprise)
            try:
                values = config.assignments(document, root, base, workspace, name)
            except config.InvalidConfig as exc:
                raise Refused(str(exc)) from exc
        elif origins['ODOO_SOURCE_FROM'] == 'machine':
            lines.append(f'kept {machine[0]}: [series.{json.dumps(document["tooling"]["version"])}] gives the '
                         'Odoo source')
        found = other_series(values)
        if found:
            values = with_exceptions(root, workspace, values, found, questions, lines, actions, checkout)
        directory, new = workspace.parent, False
    else:
        for option in SECTION_OPTIONS:
            if option in options:
                raise Refused(f'{option}: {root} has no workspace file; it only applies when setup adds a '
                              '[series."<x.y>"] section to one.')
        if kind == 'linked':
            raise Refused(f'{root} is a linked worktree of {main}: run {config.program_name()} setup in the main '
                          'checkout.')
        directory, note = root, ''
        if '--workspace' in options:
            directory = Path(options['--workspace']).resolve()
            if not root.is_relative_to(directory):
                raise Refused(f'Refusing --workspace {directory}: it is not at or above the checkout {root}.')
        else:
            directory = workspace_choice(root, questions)
            if directory != root:
                note = (f'; the project folder above {root.parent.name}/; --workspace {root} keeps it in the '
                        'clone')
        workspace = directory / config.WORKSPACE_NAME
        reason = migrate.untrusted(directory)
        if reason:
            raise Refused(f'Refusing to write {workspace}: {reason}.')
        questions.infer('workspace', directory, 'new')
        series, series_origin = choose_series(root, options, machine[2], questions)
        questions.infer('series', series, series_origin)
        roots = sorted({addon_root for addon_root, _series in modules(root)} or {'.'},
                       key=lambda item: (item != '.', item))
        # The series guard of the configuration about to be written, before any other question (S11): the
        # modules of another series are the question series_exceptions (v0.16.0 S4).
        early = {'ODOO_VERSION': series, 'PROJECT_ROOT': str(root), 'WORKSPACE_ROOT': str(directory),
                 'ADDON_ROOTS': '\n'.join(str((root / item).resolve()) for item in roots)}
        found = other_series(early)
        exceptions = (exceptions_question(questions, root, found, series, workspace,
                                          config.series_refusal(found[0], early, propose=False)) if found else [])
        adopted = adopted_environment(options['--environment'], series) if '--environment' in options else None
        chosen, origin_environment = chosen_python(options, series), 'from --environment'
        community, enterprise, origin, machine_lines, machine_actions, environments = choose_sources(
            root, series, options, machine, questions)
        infer_sources(questions, community, enterprise, origin)
        if '--name' in options:
            name = options['--name']
            if not NAME.fullmatch(name):
                raise Refused(f'Invalid --name {name}: use {NAME_RULE}.')
            questions.infer('name', name, 'from --name')
        else:
            name = re.sub(r'[^a-z0-9]+', '_', root.name.lower()).strip('_')
            if not NAME.fullmatch(name):
                raise Refused(f'Cannot derive database prefixes from the checkout name {root.name}: pass --name '
                              f'<name> ({NAME_RULE}).')
            questions.infer('name', name, 'from the checkout name')
        lines += [f'series: {series} ({series_origin})', f'community: {community} ({origin[0]})',
                  f'enterprise: {enterprise or "none"} ({origin[1]})', f'workspace: {directory} (new{note})',
                  *machine_lines]
        actions += machine_actions
        layout = f'{LAYOUT}/' if directory == root else ''
        development = False

        def configured(adopted, chosen):
            """(the workspace file's text, the values it gives) with that adopted environment or Python."""
            python = config.versions().capability(series, 'python_default')
            environment = f'{environments}/{name}' if environments else f'{layout}venv'
            # An adopted environment (S7), or a new one with another Python (S8): [tooling].environment with the
            # series' default Python, else the default named environment with its own (python_version is
            # derived, never a [tooling] key).
            if adopted is not None:
                environment, chosen = relative(adopted[0], directory), adopted[1]
            named = None
            if chosen is not None and chosen != python:
                named, python = {'path': environment, 'python': chosen}, chosen
            tooling = {'environment': environment,
                       'config': f'{layout}config/odoo.conf', 'env_file': f'{layout}config/.env',
                       'compose': f'{layout}config/compose.yml', 'requirements': f'{layout}config/requirements',
                       'addons_paths': roots, 'db_service': 'db', 'dev_prefix': f'{name}_dev_',
                       'test_prefix': f'{name}_test_', 'logs': f'{layout}logs', 'data_dir': f'{layout}data'}
            if named is not None:
                del tooling['environment']
            # Modules of another series (series_exceptions) need a [series."<x.y>"] section: version 2.
            version = 2 if exceptions else 1
            text = (WORKSPACE_HEADER + f'workspace_version = {version}\nodoo_version = {migrate.toml_string(series)}\n\n'
                    + migrate.toml_table('tooling', tooling)
                    + ('\n' + DEVELOPMENT_COMMENT + migrate.toml_table('development', DEVELOPMENT)
                       if development else '')
                    + ('\n' + migrate.toml_table('environments.default', named) if named is not None else '')
                    + ('\n' + SECTION_COMMENT.format(series=series) + migrate.toml_table(
                        f'series.{json.dumps(series)}', {'series_exceptions': exceptions}) if exceptions else ''))
            sources = {'community': str(community), **({'enterprise': str(enterprise)} if enterprise else {})}
            document = {'workspace_version': version, 'odoo_version': series,
                        'tooling': {**tooling, **sources, 'environment': environment, 'version': series,
                                    'python_version': python,
                                    **({'series_exceptions': exceptions} if exceptions else {})}}
            try:
                return text, config.assignments(document, root, directory, workspace, '')
            except config.InvalidConfig as exc:
                raise Refused(str(exc)) from exc
        text, values = configured(adopted, chosen)
        python_origin = 'from --python' if chosen is not None else f'the default of Odoo {series}'
        if adopted is None:
            answered_now, chosen_now = environment_choice(options, questions, series,
                                                          Path(values['PROJECT_ENVIRONMENT']), values['PYTHON_VERSION'])
            if answered_now is not None or chosen_now is not None:
                adopted, chosen, origin_environment = answered_now, chosen_now, 'answered'
                python_origin = 'answered'
                text, values = configured(adopted, chosen)
        development = development_choice(questions, workspace)
        if development:
            text, values = configured(adopted, chosen)
        lines.append(f'create {workspace} (mode 0600):')
        lines += [f'  {line}' if line else '' for line in text.splitlines()]
        actions.append(('create', workspace, text.encode(), 0o600))
        new = True
        if directory == root and kind == 'main':
            exclude, missing = git_exclude(root)
            if missing:
                lines.append(f'exclude {" and ".join(missing)} in {exclude} (this clone only; .gitignore unchanged)')
                addition = ''.join(f'{pattern}\n' for pattern in missing).encode()
                if exclude.exists():
                    original = exclude.read_bytes()
                    actions.append(('extend', exclude, original,
                                    original + (b'\n' if original and not original.endswith(b'\n') else b'') + addition))
                else:
                    actions += [*directories(exclude.parent, planned), ('create', exclude, addition, 0o644)]
    guarded(values)
    # setup creates the logs directory only when the workspace file sets logs (a new one always does); without the
    # key the tools create the default one, logs next to the workspace file, when they first write to it.
    plan = {'root': root, 'workspace': workspace, 'values': values, 'lines': lines, 'actions': actions,
            'after': [], 'created': set(), 'new': new, 'questions': questions,
            'python_origin': python_origin if new else 'from the workspace file',
            'logs_set': new or 'logs' in document['tooling']}
    if new and adopted is not None:
        plan['adopted_environment'] = adopted[1]
        plan['adopted_origin'] = origin_environment
    gaps(plan, directory, planned)
    return plan


# -- a workspace created in the clone, moved above it (v0.16.0 S4.11) ------------------------------

def moved_paths(document: dict, root: Path, target: Path) -> list[tuple[str, str, str]]:
    """(key, value, new value) of every relative path of the workspace file in root that the move to target must
    rewrite to keep resolving: the SERIES_PATHS of [tooling] and of the [series] tables, and the path of each
    [environments] table; those in .oasis/, which moves along, are kept (normalized first: .oasis/../x is outside it),
    and addons_paths resolve from the checkout."""
    tables = [document.get('tooling', {}), *document.get('series', {}).values()]
    found = [(key, table.get(key)) for table in tables if isinstance(table, dict) for key in config.SERIES_PATHS]
    environments = document.get('environments')
    found += [('path', table.get('path')) for table in (environments.values() if isinstance(environments, dict) else ())
              if isinstance(table, dict)]
    moved = []
    for key, value in found:
        if (not isinstance(value, str) or not value or os.path.isabs(value)
                or Path(os.path.normpath(value)).parts[:1] == (LAYOUT,)):
            continue
        new = Path(os.path.relpath(os.path.normpath(root / value), target)).as_posix()
        if (key, value, new) not in moved:
            moved.append((key, value, new))
    return moved


def move_plan(root: Path, workspace: Path, target: Path, options: dict, questions: Questions) -> dict:
    """The plan that moves a workspace setup created in the clone (oasis-workspace.toml at root) to target, a
    directory above it, with --workspace: the file (its relative paths rewritten, moved_paths), .oasis/ and the
    exclude entries of the clone; the configuration is verified once moved (apply_plan), and any failure undoes
    every change. Nothing else is created: a later setup run fills what is missing."""
    lines = questions.lines
    for option in options:
        if option not in (*PLAN_OPTIONS, '--workspace'):
            raise Refused(f'{option}: {root} is already configured by {workspace}; setup only fills what is '
                          'missing.')
    if not root.is_relative_to(target):
        raise Refused(f'Refusing --workspace {target}: it is not at or above the checkout {root}.')
    if target == root:
        raise Refused(f'--workspace {target}: {root} is already configured by {workspace}; setup only fills what is '
                      'missing.')
    layout, destination = root / LAYOUT, target / config.WORKSPACE_NAME
    reason = migrate.untrusted(target)
    for path in (destination, *((target / LAYOUT,) if os.path.lexists(layout) else ())):
        if os.path.lexists(path):
            raise Refused(f'Refusing to move {workspace if path == destination else f"{layout}/"} to {target}: {path} '
                          'exists.')
    if reason:
        raise Refused(f'Refusing to write {destination}: {reason}.')
    tracked = subprocess.run(['git', '-C', str(root), 'ls-files', '--error-unmatch', '--', config.WORKSPACE_NAME],
                             capture_output=True, env=migrate.git_env(), timeout=30)
    if tracked.returncode == 0:
        raise Refused(f'Refusing to move {workspace}: git tracks it; move it yourself.')
    try:
        raw = workspace.read_bytes()
        text, document = raw.decode('utf-8'), config.checked_workspace(workspace)
    except (OSError, UnicodeError) as exc:
        raise Refused(f'Cannot read {workspace}.') from exc
    except config.InvalidConfig as exc:
        raise Refused(str(exc)) from exc
    moved, expected = moved_paths(document, root, target), copy.deepcopy(document)
    for key, value, new in moved:
        pattern = re.compile(rf'''(?m)^([ \t]*{re.escape(key)}[ \t]*=[ \t]*)(?:'{re.escape(value)}'|"{re.escape(value)}")''')
        text = pattern.sub(lambda match: match.group(1) + migrate.toml_string(new), text)
        for table in [expected.get('tooling', {}), *expected.get('series', {}).values(),
                      *(expected.get('environments') or {}).values()]:
            if isinstance(table, dict) and table.get(key) == value:
                table[key] = new
    try:
        same = tomllib.loads(text) == expected
    except tomllib.TOMLDecodeError:
        same = False
    if not same:
        raise Refused(f'Cannot rewrite the relative paths of {workspace} for {target}: move it yourself.')
    lines += [f'workspace: {workspace} (existing; to move to {target})',
              f'move {workspace} to {destination} (mode {workspace.stat().st_mode & 0o777:04o})'
              + (', its relative paths rewritten: ' + ', '.join(f'{key} {value} -> {new}' for key, value, new in moved)
                 if moved else '')]
    actions = [('create', destination, text.encode(), workspace.stat().st_mode & 0o777)]
    if os.path.lexists(layout):
        lines.append(f'move {layout}/ to {target / LAYOUT}/')
        actions.append(('rename', layout, target / LAYOUT))
    exclude, _missing = git_exclude(root)
    if exclude.is_file():
        original = exclude.read_bytes()
        kept = [line for line in original.splitlines(keepends=True) if line.rstrip(b'\r\n').decode('utf-8', 'replace')
                not in EXCLUDES]
        if len(kept) != len(original.splitlines()):
            removed = [pattern for pattern in EXCLUDES if pattern.encode() in original.splitlines()]
            lines.append(f'remove {" and ".join(removed)} from {exclude}')
            actions.append(('extend', exclude, original, b''.join(kept)))
    actions.append(('delete', workspace, raw))
    questions.infer('workspace', target, 'moved')
    return {'root': root, 'workspace': destination, 'values': None, 'lines': lines, 'actions': actions, 'after': [],
            'created': set(), 'new': False, 'questions': questions, 'python_origin': 'from the workspace file'}


# -- another series in an existing workspace file (v0.15.0 S5) ------------------------------------

def section_target(root: Path, workspace: Path, options: dict) -> tuple[str, str, dict] | None:
    """(series, where it came from, the checked workspace document) when root is a checkout of a series
    the workspace file has no section for, else None: every other case, an invalid configuration
    included, is the existing configuration's (make_plan refuses it as before). The series is the
    checkout file's odoo_version, else the one its module manifests declare (config.detected_series,
    the series_exceptions of every section and the --exception modules left out), also for a version 1
    file; manifests of several series are left to the existing refusal."""
    if (root / config.PROFILE_NAME).is_file():
        return None
    try:
        document = config.checked_workspace(workspace)
        declared = config.checkout_file(root).get('odoo_version', config.MISSING)
        if declared is config.MISSING:
            series = config.detected_series(root, document, workspace, options.get('--exception', ()))
            origin = 'from the module manifests'
        elif isinstance(declared, str) and declared in config.versions().CAPABILITIES:
            series, origin = declared, f'from {root / config.CHECKOUT_NAME}'
        else:
            return None
    except config.InvalidConfig:
        return None
    configured = (config.declared_series(document, workspace) if document['workspace_version'] == 2
                  else [document['odoo_version']])
    if series is None or series in configured:
        return None
    return series, origin, document


def as_version2(document: dict) -> dict:
    """A copy of a checked document read as workspace_version 2 (a version 1 file's [series] tables,
    which it does not read, left out): what its series would get once converted."""
    view = copy.deepcopy(document)
    if view['workspace_version'] == 1:
        view.pop('series', None)
    view['workspace_version'] = 2
    return view


def series_folder(document: dict, workspace: Path, series: str, options: dict) -> tuple[Path, Path | None, str]:
    """(the default folder of the series' files, relative as written or absolute; the folder to adopt,
    resolved, or None; where it came from). The default is <folder of [tooling].config>/<x.y>; a
    folder next to it named for the series (<x.y>, odoo-<major>, odoo<major>, odoo-<x.y>, odoo<x.y>,
    <major>) that holds an odoo.conf or a compose file is adopted, or the --config-dir folder."""
    view, base = as_version2(document), workspace.parent
    current = config.series_tooling(view, workspace, document['odoo_version']).get('config')
    placed = config.series_tooling(view, workspace, series).get('config')
    if not isinstance(current, str) or not current or not isinstance(placed, str) or not placed:
        raise Refused('Invalid tooling path: config.')
    parent = Path(current).parent if placed == current else Path(placed).parent.parent
    if str(parent) == '.':
        parent = Path('config')
    if '--config-dir' in options:
        return parent / series, Path(options['--config-dir']).resolve(), 'from --config-dir'
    major = series.split('.')[0]
    found = []
    for name in (series, f'odoo-{major}', f'odoo{major}', f'odoo-{series}', f'odoo{series}', major):
        folder = (base / parent / name).resolve()
        holds = folder.is_dir() and any((folder / item).is_file() for item in ('odoo.conf', *COMPOSE_NAMES))
        if holds and folder not in found:
            found.append(folder)
    if len(found) > 1:
        raise Refused(f'Several folders hold Odoo {series} files: {", ".join(map(str, found))}; pass --config-dir '
                      '<dir>.')
    return parent / series, (found[0] if found else None), 'found'


def relative(path: Path, base: Path) -> str:
    """A path for the workspace file: relative to its directory when below it, else absolute."""
    return path.relative_to(base).as_posix() if path.is_relative_to(base) else str(path)


def series_section(document, workspace, series, exceptions, sources, environments, options, adopted=None,
                   python=None):
    """The [series."<series>"] values (in config.SERIES_KEYS order), the adoption plan lines and the adopted
    folder (or None): only
    what [tooling] would otherwise share with the default series. The per-series files go to the
    series folder (series_folder), the environment next to [tooling]'s (<environment>-<x.y>, or
    <environments>/<name><major> with the machine file's environments), logs and data_dir to
    <logs>/<x.y> and <data_dir>/<x.y>, the prefixes to <name><major>_dev_ and _test_ (<name> from the
    default series' dev_prefix, its own major left out). A source that [tooling] sets is overridden
    with this series' (sources: community and enterprise or None). An adopted environment (adopted: its
    path and Python, S7) is the section's environment, with python when it is not the series' default; so is
    python, the Python of the environment setup creates (S8), and a series that would otherwise use the default
    named environment with another Python gets that environment's path in the section. An
    adopted folder gives data_dir from its kept odoo.conf's data_dir (conf_data_dir) and logs from an existing
    logs/<folder name> next to the folder's parent, when that logs folder is inside the workspace directory."""
    view, base, default = as_version2(document), workspace.parent, document['odoo_version']
    old = config.series_tooling(view, workspace, default)
    new = config.series_tooling(view, workspace, series)

    def varies(key):
        return key in new and new.get(key) != old.get(key)
    section, lines = {}, []
    community, enterprise = sources
    if 'community' in old and not varies('community'):
        section['community'] = str(community)
    if 'enterprise' in old and not varies('enterprise'):
        value = str(enterprise) if enterprise is not None else False
        if value != old['enterprise']:
            section['enterprise'] = value
    dev = old.get('dev_prefix')
    if not isinstance(dev, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]+_dev_', dev):
        raise Refused('Unsafe tooling database prefixes.')
    name, own = dev[:-len('_dev_')], default.split('.')[0]
    if name.endswith(own) and name[:-len(own)].rstrip('_'):
        name = name[:-len(own)].rstrip('_')
    name += series.split('.')[0]
    environment = old.get('environment')
    if environment is None and isinstance(view.get('environments'), dict):
        named = view['environments'].get('default')
        environment = named.get('path') if isinstance(named, dict) else None
        varying = config.placed(environment, series) != config.placed(environment, default)
        # A default named environment whose Python the series does not support: the series gets its own
        # path (the machine file's environments, else that path with {series} replaced) and, without a named
        # environment, its python_default.
        unsupported = (varying and isinstance(environment, str) and environment
                       and not config.versions().python_supported(series, named.get('python')))
        if unsupported and not environments:
            section['environment'] = config.placed(environment, series)
    else:
        varying, unsupported = varies('environment'), False
    if (not varying or unsupported) and environments:
        section['environment'] = f'{environments}/{name}'
    elif not varying and isinstance(environment, str) and environment:
        section['environment'] = (Path(environment).parent / f'{Path(environment).name}-{series}').as_posix()
    if adopted is not None:
        section['environment'] = relative(adopted[0], base)
        if adopted[1] != config.versions().capability(series, 'python_default'):
            section['python'] = adopted[1]
    elif python is not None:
        # Without an environment in the section, the series uses the default named environment and its
        # python (config.series_document), which the section's python does not change: the section names
        # that environment's path when another Python is chosen.
        named = view.get('environments', {}).get('default') if isinstance(view.get('environments'), dict) else None
        own = (named.get('python') if 'environment' not in section and old.get('environment') is None
               and isinstance(named, dict) else None)
        if own is None or python != own:
            if own is not None:
                section['environment'] = config.placed(environment, series)
            if python != config.versions().capability(series, 'python_default'):
                section['python'] = python
    folder, adopted, origin = series_folder(document, workspace, series, options)
    files = {'config': 'odoo.conf', 'compose': 'compose.yml', 'env_file': '.env', 'requirements': 'requirements'}
    if adopted is not None:
        compose = next((item for item in COMPOSE_NAMES if (adopted / item).is_file()), 'compose.yml')
        files['compose'] = compose
        held = [(key, item) for key, item in files.items()
                if ((adopted / item).is_dir() if key == 'requirements' else (adopted / item).is_file())]
        listed = [*(item + ('/' if key == 'requirements' else '') for key, item in held),
                  *(name for name in PROJECT_REQUIREMENTS if (adopted / name).is_file())]
        lines.append(f'adopt {adopted} ({origin}): ' + (', '.join(listed) or 'no files yet'))
        for key, item in files.items():
            if key in dict(held) or not varies(key):
                section[key] = relative(adopted / item, base)
    else:
        for key, item in files.items():
            if not varies(key):
                written = old.get(key)
                if isinstance(written, str) and written and key != 'requirements':
                    item = Path(written).name
                section[key] = (folder / item).as_posix()
    # A key that only repeats what the series already gets from [tooling] is left out.
    for key in list(section):
        if key in files and varies(key) and (base / section[key]).resolve() == (base / new[key]).resolve():
            del section[key]
    section['dev_prefix'], section['test_prefix'] = f'{name}_dev_', f'{name}_test_'
    database, test = old.get('test_database'), old.get('test_prefix')
    if (isinstance(database, str) and isinstance(test, str) and database.startswith(test)
            and not varies('test_database')):
        section['test_database'] = f'{name}_test_' + database[len(test):]
    for key, directory in (('logs', 'logs'), ('data_dir', 'data')):
        if not varies(key):
            written = old.get(key)
            section[key] = (f'{written.rstrip("/")}/{series}' if isinstance(written, str) and written
                            else f'{directory}/{series}')
    if adopted is not None:
        # An adopted folder keeps its data and logs where they are (L18): the data_dir its kept odoo.conf
        # sets, and a logs/<folder name> folder next to the folder's parent (config/odoo-15 gives
        # logs/odoo-15) when that folder is inside the workspace directory: a --config-dir folder elsewhere
        # (/home/user/legacy15) never makes setup look at /home/logs/legacy15.
        data = conf_data_dir(adopted / files['config']) if (adopted / files['config']).is_file() else None
        if data is not None:
            section['data_dir'] = relative(data, base)
            lines.append(f'data_dir: {data} (data_dir from {adopted / files["config"]})')
        logs = adopted.parent.parent / 'logs' / adopted.name
        if logs.is_relative_to(base.resolve()) and logs.is_dir():
            section['logs'] = relative(logs, base)
            lines.append(f'logs: {logs} (named for {adopted})')
        for key in ('logs', 'data_dir'):
            if key in section and varies(key) and (base / section[key]).resolve() == (base / new[key]).resolve():
                del section[key]
    if exceptions:
        section['series_exceptions'] = exceptions
    return {key: section[key] for key in config.SERIES_KEYS if key in section}, lines, adopted


def effective(document: dict, workspace: Path, series: str) -> list:
    """What a checked document gives a checkout of series, for every environment it may select: the
    derived [tooling] and the environment name, or the refusal (series_exceptions [] left out, which
    version 2 adds)."""
    environments = document.get('environments')
    found = []
    for selected in [None, *(environments if isinstance(environments, dict) else ())]:
        try:
            derived, name = config.series_document(copy.deepcopy(document), workspace, selected, series)
        except config.InvalidConfig as exc:
            found.append(str(exc))
            continue
        tooling = derived['tooling']
        if tooling.get('series_exceptions') == []:
            del tooling['series_exceptions']
        found.append((tooling, name))
    return found


def extended_workspace(workspace: Path, document: dict, series: str, section: dict, exceptions_of: str | None = None):
    """(the new bytes, the original ones, the plan lines, the checked new document) of the workspace
    file with the section appended and, for version 1, its workspace_version line changed to 2. The
    result must parse to the same document with only those changes, pass the workspace checks, and
    give every series it configured the same configuration (but the series_exceptions of exceptions_of, the series
    whose section setup adds for them); otherwise it is refused."""
    table = f'[series.{json.dumps(series)}]'
    try:
        raw = workspace.read_bytes()
        text = raw.decode('utf-8')
    except (OSError, UnicodeError) as exc:
        raise Refused(f'Cannot read {workspace}.') from exc
    lines = []
    if document['workspace_version'] == 1:
        found = list(VERSION_LINE.finditer(text))
        if len(found) != 1:
            raise Refused(f'Cannot convert {workspace} to workspace_version 2: no single line workspace_version = 1; '
                          f'set workspace_version = 2 yourself, then run {config.program_name()} setup again.')
        text = text[:found[0].start(2)] + '2' + text[found[0].end(2):]
        lines.append(f'change workspace_version = 1 to workspace_version = 2 in {workspace} (that line only)')
    addition = SECTION_COMMENT.format(series=series) + migrate.toml_table(f'series.{json.dumps(series)}', section)
    separator = '' if not text.strip() else '\n' if text.endswith('\n') else '\n\n'
    lines += [f'add {table} to {workspace}:', *(f'  {line}' if line else '' for line in addition.splitlines())]
    expected = copy.deepcopy(document)
    expected['workspace_version'] = 2
    try:
        parsed = tomllib.loads(text + separator + addition)
        expected.setdefault('series', {})[series] = section
    except (tomllib.TOMLDecodeError, TypeError, AttributeError):
        parsed = None
    if parsed != expected:
        raise Refused(f'Cannot add {table} to {workspace}: the result is not the same file with that section added; '
                      'edit the file yourself.')
    try:
        checked = config.checked_document(copy.deepcopy(parsed), workspace)
    except config.InvalidConfig as exc:
        raise Refused(f'Cannot add {table} to {workspace}: as workspace_version 2 it would be refused ({exc}); edit '
                      'the file yourself.') from exc
    configured = (config.declared_series(document, workspace) if document['workspace_version'] == 2
                  else [document['odoo_version']])
    def compared(found, other):
        if other != exceptions_of:
            return found
        return [({key: value for key, value in item[0].items() if key != 'series_exceptions'}, item[1])
                if isinstance(item, tuple) else item for item in found]
    for other in configured:
        if compared(effective(document, workspace, other), other) != compared(effective(checked, workspace, other),
                                                                              other):
            raise Refused(f'Cannot add {table} to {workspace}: the change would alter the configuration of Odoo '
                          f'{other} ({{series}} or a [series] table that version 1 does not read); edit the file '
                          'yourself.')
    return (text + separator + addition).encode(), raw, lines, checked


def conf_data_dir(conf: Path) -> Path | None:
    """The directory an existing odoo.conf's data_dir names, as Odoo reads it (its config.py _normalize:
    variables and ~ expanded, a relative path made absolute from the working directory, symlinks
    resolved), or None: no data_dir, an empty one, or a file that cannot be read. Only data_dir is read,
    never the rest of odoo.conf."""
    reader = sibling('odoo_addons_path')
    try:
        value = (reader.read_option(conf, 'data_dir') or '').strip()
    except reader.ConfError:
        return None
    if not value:
        return None
    if '\x00' in value or '\n' in value:
        raise Refused(f'Invalid data_dir in {conf}: it must be one directory path.')
    return Path(os.path.realpath(os.path.abspath(os.path.expanduser(os.path.expandvars(value)))))


def configured_port(conf: Path) -> int | None:
    """The port an existing odoo.conf connects to (db_port, PostgreSQL's default without one), None when
    it cannot be read. Only db_port is read, never the rest of odoo.conf."""
    reader = sibling('odoo_addons_path')
    try:
        return int(reader.read_option(conf, 'db_port') or POSTGRES_PORT)
    except (ValueError, reader.ConfError):
        return None


def series_ports(document: dict, workspace: Path) -> dict[int, tuple[str, Path]]:
    """The ports the series a workspace configures already use (their odoo.conf and compose files), each
    with the first series and file that uses it: a new series' compose file must not publish one, nor
    its kept files use one."""
    taken = {}
    configured = (config.declared_series(document, workspace) if document['workspace_version'] == 2
                  else [document['odoo_version']])
    for series in configured:
        tooling = config.series_tooling(document, workspace, series)
        for key, read in (('config', configured_port), ('compose', published_port)):
            value = tooling.get(key)
            if isinstance(value, str) and value and '\x00' not in value and (workspace.parent / value).is_file():
                path = (workspace.parent / value).resolve()
                port = read(path)
                if port is not None:
                    taken.setdefault(port, (series, path))
    return taken


def series_plan(root, kind, options, questions, workspace, machine, target, lines) -> dict:
    """make_plan for a checkout of a series the workspace file has no section for (section_target)."""
    series, origin, document = target
    lines.append(f'workspace: {workspace} (existing)')
    questions.infer('workspace', workspace.parent, 'existing')
    questions.infer('series', series, origin)
    for option in options:
        if option not in SERIES_PLAN_OPTIONS:
            raise Refused(f'{option}: {root} is already configured by {workspace}; setup only fills what is '
                          'missing.')
    exceptions = list(dict.fromkeys(options.get('--exception', [])))
    for module in exceptions:
        if not config.MODULE_NAME.fullmatch(module):
            raise Refused(f'Invalid --exception {module}: use a module name.')
    # The series guard of the section about to be written, before any question.
    addons = document['tooling'].get('addons_paths')
    if isinstance(addons, list) and addons and all(isinstance(path, str) and path and '\x00' not in path
                                                   and '\n' not in path for path in addons):
        found = other_series({'ODOO_VERSION': series, 'SERIES_EXCEPTIONS': '\n'.join(exceptions),
                              'ADDON_ROOTS': '\n'.join(str((root / path).resolve()) for path in addons)})
        if found:
            mismatch = found[0]
            exceptions += exceptions_question(questions, root, found, series, workspace, (
                f'The module {mismatch["module"]} declares Odoo {mismatch["series"]} (version '
                f'{mismatch["version"]} in {mismatch["manifest"]}), but {root} is an Odoo {series} checkout: '
                f'pass --exception {mismatch["module"]} to list it in series_exceptions under '
                f'[series.{json.dumps(series)}], or set its version to {series}.x.y.z if it is an Odoo '
                f'{series} module.'))
    adopted = adopted_environment(options['--environment'], series) if '--environment' in options else None
    chosen, origin_environment = chosen_python(options, series), 'from --environment'
    community, enterprise, source_origin, machine_lines, machine_actions, environments = choose_sources(
        root, series, options, machine, questions)
    lines += [f'series: {series} ({origin}; {workspace} has no [series.{json.dumps(series)}] section)',
              f'community: {community} ({source_origin[0]})', f'enterprise: {enterprise or "none"} ({source_origin[1]})',
              *machine_lines]
    infer_sources(questions, community, enterprise, source_origin)

    def configured(adopted, chosen):
        """The section, the extended workspace file and the values it gives, with that adopted environment or
        Python."""
        section, adoption, folder = series_section(document, workspace, series, exceptions, (community, enterprise),
                                                   environments, options, adopted, chosen)
        new, raw, workspace_lines, checked = extended_workspace(workspace, document, series, section)
        try:
            planned, base, _workspace, name, _origins, _refusal = config.layered_configuration(root, planned=checked)
            # A new machine entry is not written yet: its source, as the existing flow does.
            if 'community' not in planned['tooling']:
                planned['tooling']['community'] = str(community)
            if enterprise is not None and 'enterprise' not in planned['tooling']:
                planned['tooling']['enterprise'] = str(enterprise)
            values = config.assignments(planned, root, base, workspace, name)
        except config.InvalidConfig as exc:
            raise Refused(str(exc)) from exc
        return adoption, folder, new, raw, workspace_lines, base, values
    adoption, folder, new, raw, workspace_lines, base, values = configured(adopted, chosen)
    python_origin = 'from --python' if chosen is not None else f'the default of Odoo {series}'
    if adopted is None:
        answered_now, chosen_now = environment_choice(options, questions, series, Path(values['PROJECT_ENVIRONMENT']),
                                                      values['PYTHON_VERSION'])
        if answered_now is not None or chosen_now is not None:
            adopted, chosen, origin_environment = answered_now, chosen_now, 'answered'
            python_origin = 'answered'
            adoption, folder, new, raw, workspace_lines, base, values = configured(adopted, chosen)
    lines += [*workspace_lines, *adoption]
    guarded(values)
    # A failed compile or uv venv undoes the edit of the shared workspace file too (undo_after).
    plan = {'root': root, 'workspace': workspace, 'values': values, 'lines': lines,
            'actions': [*machine_actions, ('extend', workspace, raw, new)], 'after': [], 'created': set(),
            'new': False, 'taken': series_ports(document, workspace), 'undo_after': True,
            'project_requirements': folder, 'questions': questions, 'python_origin': python_origin}
    if adopted is not None:
        plan['adopted_environment'] = adopted[1]
        plan['adopted_origin'] = origin_environment
    gaps(plan, base, set())
    return plan


def other_series(values: dict) -> list[dict]:
    """Every module of the addons paths whose manifest declares another series than ODOO_VERSION
    (config.series_mismatch, the SERIES_EXCEPTIONS left out), in its order."""
    found, values = [], dict(values)
    while (mismatch := config.series_mismatch(values)) is not None:
        found.append(mismatch)
        values['SERIES_EXCEPTIONS'] = '\n'.join(filter(None, (values.get('SERIES_EXCEPTIONS', ''), mismatch['module'])))
    return found


def exceptions_question(questions: Questions, root: Path, found: list, series: str, workspace: Path,
                        refusal: str) -> list[str]:
    """The modules of another series (found) to list in series_exceptions (v0.16.0 S4): the question
    series_exceptions, add (recommended) or no (refused with refusal). Open, the plan goes on as if added and
    --apply refuses."""
    modules = [mismatch['module'] for mismatch in found]
    listed = ', '.join(f'{mismatch["module"]} (Odoo {mismatch["series"]})' for mismatch in found)
    question = {'id': 'series_exceptions',
                'text': f'The modules {listed} of {root} declare another Odoo series than {series}: list them in '
                        f'series_exceptions under [series.{json.dumps(series)}] in {workspace}?',
                'options': [{'value': 'add', 'label': f'add {", ".join(modules)} to series_exceptions'},
                            {'value': 'no', 'label': f'no: they are Odoo {series} modules with another version, or '
                                                     f'this is not an Odoo {series} checkout'}],
                'recommended': 'add', 'flag': '--answer series_exceptions=<add|no>'}
    if questions.choose(question) == 'no':
        raise Refused(refusal)
    return modules


def with_exceptions(root, workspace, values, found, questions, lines, actions, checkout=None) -> dict:
    """An existing configuration whose modules declare another series (found): the question series_exceptions;
    the workspace file gets a [series."<x.y>"] section that lists them (a version 1 file becomes version 2), and
    the values it gives. A section of that series already in the file is never edited: refused."""
    series = values['ODOO_VERSION']
    try:
        document = config.checked_workspace(workspace)
    except config.InvalidConfig as exc:
        raise Refused(str(exc)) from exc
    modules = exceptions_question(questions, root, found, series, workspace,
                                  config.series_refusal(found[0], values, propose=False))
    if series in config.series_sections(document, workspace):
        raise Refused(f'{workspace} has a [series.{json.dumps(series)}] section, which setup never edits: add '
                      f'{", ".join(modules)} to its series_exceptions yourself, then run {config.program_name()} setup '
                      'again.')
    new, raw, extended, checked = extended_workspace(workspace, document, series, {'series_exceptions': modules},
                                                     exceptions_of=series)
    lines += extended
    actions.append(('extend', workspace, raw, new))
    try:
        planned, base, _workspace, name, _origins, _refusal = config.layered_configuration(root, planned=checked,
                                                                                            checkout=checkout)
        planned['tooling'].setdefault('community', values['ODOO_SOURCE'])
        if values.get('ENTERPRISE_SOURCE'):
            planned['tooling'].setdefault('enterprise', values['ENTERPRISE_SOURCE'])
        return config.assignments(planned, root, base, workspace, name)
    except config.InvalidConfig as exc:
        raise Refused(str(exc)) from exc


def worktree_slugs(root: Path, main: Path) -> set[str]:
    """The checkout slugs of the repository's other checkouts: their checkout file's, else (a linked worktree) the
    one their directory name gives, as tools/gc.py checkout_slugs reads them; those it cannot read are left out."""
    try:
        result = subprocess.run(['git', '-C', str(root), 'worktree', 'list', '--porcelain'], capture_output=True,
                                text=True, env=migrate.git_env(), timeout=30)
    except (OSError, subprocess.SubprocessError):
        return set()
    slugs = set()
    for line in result.stdout.splitlines() if result.returncode == 0 else ():
        path = Path(line[len('worktree '):]).resolve() if line.startswith('worktree ') else None
        if path is None or path == root:
            continue
        try:
            slug = config.checkout_overrides(path).get('checkout_slug') or (
                config.derived_slug(path, main) if path != main else '')
        except config.InvalidConfig:
            continue
        if slug:
            slugs.add(slug)
    return slugs


def slug_change(root: Path, kind: str, main: Path | None):
    """(the checkout file document setup is about to write, its plan line, its action), or three None: a linked
    worktree whose directory name gives a slug over 20 characters (v0.16.0 S4), without a checkout_slug, gets one
    shortened to 20, with _<n> when another checkout of the repository uses it. A checkout file without [tooling] is
    extended; one with [tooling] is never edited: refused, naming the line to add."""
    if kind != 'linked' or main is None:
        return None, None, None
    try:
        current = config.checkout_file(root)
    except config.InvalidConfig:
        return None, None, None  # the configuration refuses it
    raw = config.worktree_slug(root, main)
    # Only a slug over 20 characters is shortened. Any other invalid one (a name that gives nothing) is never
    # proposed: the configuration refuses it at plan time with the derived-slug message (config.derived_slug).
    if ('checkout_slug' in current.get('tooling', {}) or config.SLUG.fullmatch(raw) or len(raw) <= 20
            or not config.SLUG.fullmatch(raw[:20].rstrip('_'))):
        return None, None, None
    taken, slug, number = worktree_slugs(root, main), raw[:20].rstrip('_'), 2
    while slug in taken:
        slug, number = f'{raw[:19 - len(str(number))].rstrip("_")}_{number}', number + 1
    path, why = root / config.CHECKOUT_NAME, f'{len(raw)} characters; a slug has at most 20'
    if 'tooling' in current:
        raise Refused(f'The worktree directory name {root.name} gives the checkout slug {raw} ({why}) and {path} has '
                      f'a [tooling] table, which setup never edits: add checkout_slug = {migrate.toml_string(slug)} '
                      f'to it, then run {config.program_name()} setup again.')
    text = CHECKOUT_SLUG.format(name=root.name, raw=raw, slug=migrate.toml_string(slug))
    document = {**current, 'tooling': {'checkout_slug': slug}}
    why = f'the worktree directory name {root.name} gives {raw}, {why}'
    if not os.path.lexists(path):
        return document, f'create {path}: checkout_slug {slug} ({why})', ('create', path, text.encode(), 0o644)
    original = path.read_bytes()
    new = original + (b'' if not original.strip() else b'\n' if original.endswith(b'\n') else b'\n\n') + text.encode()
    try:
        if tomllib.loads(new.decode('utf-8')) != document:
            raise ValueError
    except (ValueError, UnicodeError):
        raise Refused(f'Cannot add checkout_slug to {path}: add checkout_slug = {migrate.toml_string(slug)} under '
                      '[tooling] yourself.') from None
    return document, f'add [tooling] checkout_slug {slug} to {path} ({why})', ('extend', path, original, new)


def infer_sources(questions: Questions, community: Path, enterprise: Path | None, origin: tuple[str, str]):
    questions.infer('community', community, origin[0])
    questions.infer('enterprise', enterprise, origin[1])


def guarded(values: dict):
    """Refuse a configuration whose modules declare another Odoo series (config.series_mismatch, S11)."""
    mismatch = config.series_mismatch(values)
    if mismatch is not None:
        raise Refused(config.series_refusal(mismatch, values, propose=False))


def published_port(compose: Path) -> int | None:
    """The one host port the compose file publishes to 5432, or None (tools/db_account.py published_port)."""
    return db_account.published_port(compose)


def prefix_name(values: dict) -> str:
    """The workspace's name from its dev_prefix: the _dev_ suffix removed only when it is there, and any
    trailing underscore."""
    prefix = values['DEV_PREFIX']
    if prefix.endswith('_dev_'):
        prefix = prefix[:-len('_dev_')]
    return prefix.rstrip('_').lower()


def conf_account(conf: Path) -> dict:
    """The db_user and db_password a kept odoo.conf sets (tools/db_account.py), {} without it or when it
    cannot be read (doctor reports it)."""
    try:
        return db_account.conf_options(conf) if conf.exists() else {}
    except db_account.AccountError:
        return {}


def account_values(conf: Path, env_file: Path, values: dict, names) -> tuple[dict, str, dict]:
    """({name: assignment line} for names of the account, what the plan says of them, {name: value}) (v0.16.0
    S2): each of
    ODOO_DB_USER and ODOO_DB_PASSWORD is the db_user or db_password a kept odoo.conf sets (Odoo keeps using
    it), else generated: oasis_<name> (prefix_name) and secrets.token_urlsafe(24). No value is ever in the
    plan; a value the env file cannot hold as docker compose reads it is refused."""
    options = conf_account(conf)
    generated = {'db_user': f'oasis_{prefix_name(values) or "odoo"}', 'db_password': secrets.token_urlsafe(24)}
    assignments, said, chosen = {}, [], {}
    for _key, option, name, _variable in db_account.ACCOUNT:
        if name not in names:
            continue
        value = chosen[name] = options.get(option, generated[option])
        if option in options:
            said.append(f'{name} from {option} of {conf}')
        else:
            said.append(f'{name} {value}' if option == 'db_user' else f'a generated {name}')
        if PLAIN_VALUE.fullmatch(value):
            assignments[name] = f'{name}={value}'
        elif "'" not in value:
            assignments[name] = f"{name}='{value}'"
        elif '"' not in value and not re.search(r'[$\\]', value):
            assignments[name] = f'{name}="{value}"'
        else:
            raise Refused(f'Cannot copy {option} of {conf} to {env_file}: docker compose would not read its value as '
                          f'written; write {env_file} yourself, then run {config.program_name()} setup again.')
    return assignments, ' and '.join(said), chosen


def new_account(conf: Path, env_file: Path, values: dict) -> tuple[str, str]:
    """(the text of a new env file, what the plan says of it): the whole account (account_values)."""
    assignments, said, _chosen = account_values(conf, env_file, values, db_account.account_names())
    return ENV_FILE.format(user=assignments['ODOO_DB_USER'], password=assignments['ODOO_DB_PASSWORD']), said


def filled_account(conf: Path, env_file: Path, values: dict):
    """(the original bytes, the new ones, the plan line) of a kept env file whose account variables setup
    fills (db_account.fill_names: those it assigns an empty value), or None: nothing to fill, or a file that
    cannot be read (doctor reports it). Each empty assignment gets its value in place (the `export` and a
    trailing ` # comment` kept); an absent variable is never added. Every other byte is kept; the result must
    read back as exactly those values."""
    try:
        raw = env_file.read_bytes()
        text = raw.decode('utf-8')
    except (OSError, UnicodeError):
        return None
    names = db_account.account_names()
    found = db_account.text_values(text, names)
    fill = db_account.fill_names(found)
    if not fill:
        return None
    assignments, said, chosen = account_values(conf, env_file, values, fill)
    lines = text.splitlines(keepends=True)
    for name in fill:
        index = max(number for number, line in enumerate(lines)
                    if (match := db_account.ENV_ASSIGNMENT.fullmatch(line.rstrip('\r\n'))) and match.group(1) == name)
        line = lines[index]
        body = line.rstrip('\r\n')
        ending = line[len(body):]
        head, _equals, value = body.partition('=')
        comment = re.search(r'\s+#.*$', value)
        lines[index] = f'{head}={assignments[name].partition("=")[2]}{comment.group(0) if comment else ""}{ending}'
    new = ''.join(lines)
    expected = {**found, **chosen}
    if db_account.text_values(new, names) != expected:
        raise Refused(f'Cannot fill {" and ".join(fill)} in {env_file}: the result would not read as written; '
                      f'fill it yourself, then run {config.program_name()} setup again.')
    line = f'fill {" and ".join(fill)} in {env_file} (mode 0600; every other line kept): {said}'
    return raw, new.encode('utf-8'), line


def conf_sections(text: str) -> dict:
    """Every section of an odoo.conf text with its options and raw values, as configparser reads it."""
    parser = configparser.RawConfigParser()
    parser.read_string(text)
    found = {section: {option: parser.get(section, option, raw=True) for option in parser.options(section)}
             for section in parser.sections()}
    found[parser.default_section] = dict(parser.defaults())
    return found


def without_options(conf: Path, options: list):
    """(the original bytes, the new ones) of odoo.conf without the [options] lines of options, or None when
    they are not one line each at the start of a line (a repeated or continued option) or the result does not
    read as the same file without them. Every other byte is kept."""
    try:
        raw = conf.read_bytes()
        text = raw.decode('utf-8')
        before = conf_sections(text)
    except (OSError, UnicodeError, configparser.Error):
        return None
    lines = text.splitlines(keepends=True)
    section, found = None, {option: [] for option in options}
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith('['):
            header = re.match(r'\[(.+)\]', stripped)
            section = header.group(1) if header else section
            continue
        match = OPTION_LINE.match(line)
        if section == 'options' and match and match.group(1).strip().lower() in found:
            found[match.group(1).strip().lower()].append(index)
    if any(len(indexes) != 1 for indexes in found.values()):
        return None
    removed = {indexes[0] for indexes in found.values()}
    for index in removed:
        following = lines[index + 1] if index + 1 < len(lines) else ''
        if following.strip() and following[:1].isspace():
            return None
    new = ''.join(line for index, line in enumerate(lines) if index not in removed)
    expected = {section: dict(values) for section, values in before.items()}
    for option in options:
        expected['options'].pop(option, None)
    try:
        if conf_sections(new) != expected:
            return None
    except configparser.Error:
        return None
    return raw, new.encode('utf-8')


def account_move(conf: Path, env_file: Path) -> tuple[list, list] | None:
    """(the plan lines, the actions) of the move of odoo.conf's db_user and db_password to the env file
    (v0.16.0 S2, "Los respeta y ofrece migrar"), against the env file as this plan leaves it (db_account.move):
    removed from odoo.conf when the env file holds the same values, else a WARN line and nothing changed. None
    when odoo.conf sets neither or a file cannot be read (doctor reports it). No value is ever in a line."""
    try:
        state = db_account.move(conf, env_file)
    except db_account.AccountError:
        return None
    options = [*state['same'], *state['differs'], *state['lacks']]
    if not options:
        return None
    if state['differs'] or state['lacks']:
        details = [f'{" and ".join(state[key])} ({reason})'
                   for key, reason in (('differs', 'another value'), ('lacks', 'not set')) if state[key]]
        return [f'WARN: {env_file} does not hold the account {conf} sets: {"; ".join(details)}: both files kept, and '
                f'Odoo keeps connecting with the account of {conf}; setup moves it to {env_file} only when both hold '
                'the same values'], []
    names = ' and '.join(options)
    edit = without_options(conf, options)
    if edit is None:
        return [f'WARN: {conf} sets {names} on a repeated or continued line, which setup does not edit: both files '
                f'kept; {env_file} holds the same account: remove {names} from {conf} yourself'], []
    lines = 'those lines' if len(options) > 1 else 'that line'
    return ([f'remove {names} from {conf} ({lines} only): {env_file} holds the same account, which oasis passes to '
             'Odoo'], [('edit', conf, *edit)])


def gaps(plan: dict, directory: Path, planned: set):
    """Plan every missing file, directory, lock and environment of the configuration; keep the rest."""
    values, lines, actions, root = plan['values'], plan['lines'], plan['actions'], plan['root']

    def create(path: Path, text: str, mode: int, line: str, key: str):
        if path.exists():
            lines.append(f'kept {path}')
            return
        actions.extend(directories(path.parent, planned))
        actions.append(('create', path, text.encode(), mode))
        lines.append(line)
        plan['created'].add(key)

    conf, compose, env_file = (Path(values[key]) for key in ('ODOO_CONFIG', 'COMPOSE_FILE', 'ENV_FILE'))
    # One port for both files: a new one takes the port of the one that is kept (odoo.conf's db_port,
    # PostgreSQL's default without one; the port the compose file publishes to 5432); two kept files
    # that disagree are reported; only without either is a free port chosen.
    conf_port = compose_port = None
    if conf.exists():
        conf_port = configured_port(conf)
    if compose.exists():
        compose_port = published_port(compose)
    port, unread = None, False
    # A new series' compose file never publishes a port another series of the workspace uses, and its kept
    # files never use one: that is refused (setup never edits a kept file; doctor fails a shared port).
    taken = plan.get('taken', {})
    for path, kept, verb in ((conf, conf_port if conf.exists() else None, 'connects to'),
                             (compose, compose_port if compose.exists() else None, 'publishes')):
        if kept in taken:
            other, used = taken[kept]
            fix = (f'set db_port in {conf} to a port no other series uses'
                   + (f' and publish the same port to 5432 in {compose}' if compose.exists() else '')
                   if path == conf else f'publish a port no other series uses to 5432 in {compose}')
            raise Refused(f'Port {kept} of Odoo {values["ODOO_VERSION"]} ({path} {verb} it) is already used by Odoo '
                          f'{other} ({used}); two series of a workspace cannot share a PostgreSQL port: {fix}, then '
                          f'run {config.program_name()} setup again.')
    if conf.exists() and not compose.exists():
        port = conf_port if conf_port is not None else free_port(taken)
    elif compose.exists() and not conf.exists():
        port, unread = (compose_port, False) if compose_port is not None else (free_port(taken), True)
    elif not conf.exists():
        port = free_port(taken)
    questions = plan['questions']
    if conf.exists() and conf_port is not None:
        questions.infer('db_port', conf_port, f'from {conf}')
    elif compose.exists() and compose_port is not None:
        questions.infer('db_port', compose_port, f'from {compose}')
    else:
        questions.infer('db_port', port, 'a free port')
    series = values['ODOO_VERSION']
    postgres = config.versions().capability(series, 'postgres_default')
    name = prefix_name(values).replace('_', '-')
    compose_name = f'oasis-{name}-{hashlib.sha256(str(directory).encode()).hexdigest()[:6]}'
    service = values['DB_SERVICE']
    create(conf, CONF.format(env_file=env_file, port=port), 0o600,
           f'create {conf} (mode 0600): path-free; db_port {port}; db_user and db_password empty', 'conf')
    if unread:
        lines.append(f'check {conf}: no port published to 5432 found in {compose}; set db_port {port} to the port '
                     'it publishes')
    create(compose, COMPOSE.format(name=compose_name, service=service, postgres=postgres, port=port), 0o644,
           f'create {compose}: PostgreSQL {postgres} (postgres:{postgres}) as service {service} on '
           f'127.0.0.1:{port}, compose project {compose_name}', 'compose')
    if 'conf' not in plan['created'] and 'compose' not in plan['created'] and None not in (conf_port, compose_port) \
            and conf_port != compose_port:
        lines.append(f'mismatch: {conf} connects to port {conf_port} but {compose} publishes {compose_port}: make '
                     'them the same')
    if not env_file.exists():
        text, described = new_account(conf, env_file, values)
        create(env_file, text, 0o600, f'create {env_file} (mode 0600): {described}', 'env')
    else:
        lines.append(f'kept {env_file}')
        filled = filled_account(conf, env_file, values)
        if filled is not None:
            lines.append(filled[2])
            actions.append(('fill', env_file, filled[0], filled[1]))
        else:
            try:
                declared = db_account.env_values(env_file)
            except db_account.AccountError:
                declared = None
            if declared == {}:
                lines.append(f'WARN: {env_file} sets neither ODOO_DB_USER nor ODOO_DB_PASSWORD: '
                             f'{db_account.unassigned_advice(env_file, config.program_name())}')
    if 'conf' not in plan['created']:
        moved = account_move(conf, env_file)
        if moved is not None:
            lines.extend(moved[0])
            actions.extend(moved[1])
    requirements = Path(values['REQUIREMENTS_DIR'])
    source = Path(values['ODOO_SOURCE'])
    if not (requirements / 'runtime.in').exists() and not (source / 'requirements.txt').is_file():
        raise Refused(f'Cannot write {requirements / "runtime.in"}: {source / "requirements.txt"} does not exist.')
    # The project's own requirement files in an adopted series folder (S7), referenced from the
    # requirements directory: relative when both are in the workspace directory, else absolute.
    folder = plan.get('project_requirements')
    extra, overrides = (folder / name if folder is not None and (folder / name).is_file() else None
                        for name in PROJECT_REQUIREMENTS)

    def included(path: Path) -> str:
        inside = path.is_relative_to(directory) and requirements.is_relative_to(directory)
        return os.path.relpath(path, requirements) if inside else str(path)
    needed = config.versions().capability(series, 'runtime_requirements')
    target = requirements / locks.OVERRIDES
    pins, additions = (anticipated(plan, source, requirements, extra, overrides, needed)
                       if not (requirements / 'runtime.in').exists() else ([], []))
    create(requirements / 'runtime.in',
           RUNTIME_IN.format(source=source)
           + ''.join(RUNTIME_SERIES.format(requirement=requirement, reason=reason) for requirement, reason in needed)
           + (RUNTIME_EXTRA.format(extra=included(extra)) if extra else '')
           + ''.join(RUNTIME_MODULE.format(requirement=requirement, module=module) for requirement, module in additions),
           0o644,
           f'create {requirements / "runtime.in"}: -r {source}/requirements.txt'
           + ''.join(f', {requirement}' for requirement, _reason in needed)
           + (f', -r {included(extra)}' if extra else '')
           + ''.join(f', {requirement}' for requirement, _module in additions), 'inputs')
    create(requirements / 'dev.in', DEV_IN, 0o644,
           f'create {requirements / "dev.in"}: -c runtime.txt, -r runtime.in', 'inputs')
    pinned = ''.join(ANSWERED_PIN.format(pin=pin, reason=reason) for pin, reason in pins)
    if overrides is not None or pins:
        listed = [*([f'-r {included(overrides)}'] if overrides is not None else []), *(pin for pin, _reason in pins)]
        create(target, (OVERRIDES_TXT.format(overrides=included(overrides)) if overrides is not None
                        else OVERRIDES_PINS) + pinned, 0o644,
               f'create {target}: {", ".join(listed)} (uv pip compile --override)', 'inputs')
    elif os.path.lexists(target):
        lines.append(f'kept {target}')
    for key in ('LOGS_DIR', 'DATA_DIR'):
        if values[key] and (key != 'LOGS_DIR' or plan.get('logs_set', True)):
            path = Path(values[key])
            if path.exists():
                lines.append(f'kept {path}/')
            else:
                actions.extend(directories(path, planned))
                lines.append(f'create {path}/')
    python = values['PYTHON_VERSION']
    usable = True
    if 'inputs' not in plan['created'] and locks.current(requirements, root):
        lines.append(f'kept the locks in {requirements}: current')
    elif 'inputs' not in plan['created'] and locks.state(requirements, root) == 'edited':
        lines.append(f'kept the locks in {requirements}: a lock was changed by hand; move it away or fingerprint '
                     f'it again (see {config.program_name()} bootstrap)')
        usable = False
    else:
        lines.append(f'compile {requirements}/runtime.txt, dev.txt and lock.sha256 with Python {python} '
                     '(uv pip compile)')
        plan['after'].append(('compile', requirements, python))
    environment = Path(values['PROJECT_ENVIRONMENT'])
    kept_environment = (environment / 'pyvenv.cfg').is_file()
    questions.infer('environment', environment, plan.get('adopted_origin') if 'adopted_environment' in plan
                    else 'existing' if kept_environment else 'new')
    questions.infer('python', python, 'from the adopted environment' if 'adopted_environment' in plan
                    else plan['python_origin'])
    if 'adopted_environment' in plan:
        lines.append(f'adopt the environment {environment} ({plan["adopted_origin"]}): Python '
                     f'{plan["adopted_environment"]} (its pyvenv.cfg); setup never creates, syncs or deletes it')
    elif (environment / 'pyvenv.cfg').is_file():
        lines.append(f'kept the environment {environment}')
    elif not usable:
        lines.append(f'not created: the environment {environment}, until the locks match lock.sha256')
    else:
        lines.append(f'create the environment {environment} with Python {python} (uv venv) and sync dev.txt '
                     '(uv pip sync)')
        plan['after'].append(('environment', environment, python, requirements / 'dev.txt'))


def anticipated(plan: dict, source: Path, requirements: Path, extra, overrides, needed) -> tuple[list, list]:
    """([(pin, reason)] for a new overrides.txt, [(requirement, module)] for the new runtime.in): the answers to
    the problems a new runtime.in would meet (tools/known_problems.py, v0.16.0 S3). Each problem is a question;
    without an answer it stays open and --apply refuses. A kept overrides.txt is never edited: python-ldap then
    gets a WARN line and a conflicting pin no question."""
    values, questions, lines = plan['values'], plan['questions'], plan['lines']
    series, python = values['ODOO_VERSION'], values['PYTHON_VERSION']
    target, runtime = requirements / locks.OVERRIDES, requirements / 'runtime.in'
    kept = os.path.lexists(target)
    found = known_problems.pins(
        [*known_problems.lines(source / 'requirements.txt'), *(requirement for requirement, _reason in needed),
         *(known_problems.lines(extra) if extra else [])], python, known_problems.lines(overrides) if overrides else [])
    pins, additions = [], []
    ldap = config.versions().capability(series, 'ldap_override')
    system = known_problems.system_ldap() if ldap and known_problems.pinned(found, ldap[0]) else None
    if system is not None:
        text = (f"Odoo {series} pins {ldap[0]}, which does not build against this machine's OpenLDAP {system} (no "
                f'libldap_r): pin {ldap[1]} in {target}?')
        if kept:
            lines.append(f"WARN: Odoo {series} pins {ldap[0]}, which does not build against this machine's OpenLDAP "
                         f'{system} (no libldap_r): add {ldap[1]} to {target} yourself (setup keeps that file)')
        elif questions.choose({'id': 'python_ldap', 'text': text, 'options': [
                {'value': 'yes', 'label': f'pin {ldap[1]} (uv pip compile --override)'},
                {'value': 'no', 'label': "keep Odoo's pin: its build may fail"}],
                'recommended': 'yes', 'flag': '--answer python_ldap=<yes|no>'}) == 'yes':
            pins.append((ldap[1], f"Odoo {series}'s {ldap[0]} does not build against OpenLDAP 2.6 (no libldap_r)."))
    roots = [Path(root) for root in values['ADDON_ROOTS'].splitlines() if root]
    for problem in known_problems.requirement_problems(known_problems.module_requirements(roots), found):
        module, entry, question_id = problem['module'], problem['entry'], problem['id']
        if problem['kind'] == 'missing' and problem['known']:
            question = {'id': question_id, 'text': (f'The module {module} requires {entry} (external_dependencies), '
                                                    f'which no requirement of {runtime} lists: add it there?'),
                        'options': [{'value': 'add', 'label': f'add {entry} to runtime.in'},
                                    {'value': 'skip', 'label': 'leave it out: the module will not install without it'}],
                        'recommended': 'add', 'flag': f'--answer {question_id}=<add|skip>'}
        elif problem['kind'] == 'missing':
            # A name setup does not know as a distribution's may be only an import name (cv2 is opencv-python's):
            # never proposed; added as written only when the answer says it is the distribution's name.
            name = problem['name']
            question = {'id': question_id, 'text': (f'The module {module} requires {entry} (external_dependencies), '
                                                    f'which no requirement of {runtime} lists, and setup cannot tell '
                                                    f'whether {name} is the name of its distribution or only the '
                                                    f'module it imports: add {entry} there as written?'),
                        'options': [{'value': 'add', 'label': f'add {entry} to runtime.in: {name} is the name of its '
                                                              'distribution'},
                                    {'value': 'skip', 'label': f'leave it out: add the distribution that provides '
                                                               f'{name} to the requirements yourself, or the module '
                                                               'will not install'}],
                        'recommended': None, 'flag': f'--answer {question_id}=<add|skip>'}
        if problem['kind'] == 'missing':
            if questions.choose(question) == 'add':
                additions.append((entry, module))
        elif not kept:
            proposal = problem['proposal']
            question = {'id': question_id, 'text': (f'The module {module} requires {entry} (external_dependencies), but '
                                                    f'the Odoo {series} requirements pin {problem["pin"]}: override it '
                                                    f'with {proposal} in {target}?'),
                        'options': [{'value': 'override', 'label': f'pin {proposal} (uv pip compile --override)'},
                                    {'value': 'skip', 'label': "keep Odoo's pin: the module may not install"}],
                        'recommended': 'override', 'flag': f'--answer {question_id}=<override|skip>'}
            if questions.choose(question) == 'override':
                pins.append((proposal, f'The module {module} requires {entry} (external_dependencies).'))
    return pins, additions


# -- apply -----------------------------------------------------------------------------------------

class Changes:
    """The file changes made so far, undone in reverse order by rollback. Files are created
    exclusively (never overwritten); an existing file is only extended, when it still has the
    content the plan read."""

    def __init__(self):
        self.undo = []

    def apply(self, action):
        kind, path = action[0], action[1]
        if kind == 'mkdir':
            os.mkdir(path, DIRECTORY_MODE)
            self.undo.append(('rmdir', path))
        elif kind == 'create':
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, action[3])
            self.undo.append(('remove', path))
            with os.fdopen(descriptor, 'wb') as stream:
                os.fchmod(stream.fileno(), action[3])
                stream.write(action[2])
        elif kind == 'rename':
            # A directory moved whole (os.rename never moves it across file systems): never onto an existing path.
            if os.path.lexists(action[2]):
                raise OSError(17, f'{action[2]} exists')
            os.rename(path, action[2])
            self.undo.append(('rename', action[2], path))
        elif kind == 'delete':
            # A file removed once its moved copy exists: its bytes and mode come back on rollback.
            if path.read_bytes() != action[2]:
                raise OSError(0, f'{path} changed since the plan')
            mode = path.stat().st_mode & 0o7777
            os.unlink(path)
            self.undo.append(('recreate', path, action[2], mode))
        elif kind == 'fill':
            # An env file that gets the account: its bytes and mode come back on rollback; it ends 0600.
            original, data = action[2], action[3]
            if path.read_bytes() != original:
                raise OSError(0, f'{path} changed since the plan')
            self.keep(path)
            os.chmod(path, 0o600)
            migrate.write_in_place(path, data)
        else:
            original, data = action[2], action[3]
            if path.read_bytes() != original:
                raise OSError(0, f'{path} changed since the plan')
            migrate.write_in_place(path, data, lambda: self.undo.append(('restore', path, original)))

    def keep(self, path: Path):
        """Before a command setup runs (uv) may write path: rollback gives it back its bytes and mode, or
        removes it when it did not exist."""
        if os.path.lexists(path):
            self.undo.append(('rewrite', path, path.read_bytes(), path.stat().st_mode & 0o7777))
        else:
            self.undo.append(('discard', path))

    def made(self, directories: list[Path]):
        """Directories created outside apply (outermost first): rollback removes them when empty."""
        self.undo += [('rmdir', directory) for directory in directories]

    def rollback(self) -> list[str]:
        failed = []
        for step in reversed(self.undo):
            try:
                if step[0] == 'rmdir':
                    os.rmdir(step[1])
                elif step[0] == 'rename':
                    os.rename(step[1], step[2])
                elif step[0] == 'recreate':
                    descriptor = os.open(step[1], os.O_WRONLY | os.O_CREAT | os.O_EXCL, step[3])
                    with os.fdopen(descriptor, 'wb') as stream:
                        os.fchmod(stream.fileno(), step[3])
                        stream.write(step[2])
                elif step[0] == 'remove':
                    os.unlink(step[1])
                elif step[0] == 'discard':
                    if os.path.lexists(step[1]):
                        os.unlink(step[1])
                elif step[0] == 'rewrite':
                    if os.path.lexists(step[1]):
                        migrate.write_in_place(step[1], step[2])
                        os.chmod(step[1], step[3])
                    else:
                        descriptor = os.open(step[1], os.O_WRONLY | os.O_CREAT | os.O_EXCL, step[3])
                        with os.fdopen(descriptor, 'wb') as stream:
                            os.fchmod(stream.fileno(), step[3])
                            stream.write(step[2])
                else:
                    migrate.write_in_place(step[1], step[2])
            except OSError as exc:
                failed.append(f'{step[1]}: {exc.strerror or exc}')
        self.undo = []
        return failed


def undone(message: str, failed: list[str], then: str = '') -> int:
    if failed:
        print(f'ERROR: {message}; these changes could not be undone:', file=sys.stderr)
    else:
        print(f'ERROR: {message}; every change was undone' + (f': {then}' if then else '.'), file=sys.stderr)
    for line in failed:
        print(f'  {line}', file=sys.stderr)
    return 1


def apply_plan(plan: dict) -> int:
    program, root = config.program_name(), plan['root']
    changes = Changes()
    try:
        for action in plan['actions']:
            changes.apply(action)
        loaded = config.load(root)
        # A moved workspace (move_plan) gives its values once moved.
        plan['values'] = plan['values'] or loaded
    except OSError as exc:
        return undone(f'Could not set up: {exc.strerror or exc}', changes.rollback())
    except config.InvalidConfig as exc:
        return undone(f'Verification failed ({exc})', changes.rollback())
    except BaseException:
        changes.rollback()
        raise
    print(f'verified: {root} loads its configuration from {plan["workspace"]}', flush=True)
    rerun = f'{program} setup --apply'
    # A series section (series_plan): a failed compile or uv venv undoes every change, the locks and the
    # directories made for the environment included, so the shared workspace file never keeps a section
    # whose series is not set up. Otherwise the files are kept and a second run continues.
    undo_after = plan.get('undo_after', False)
    try:
        failed = after_steps(plan, changes, rerun, undo_after)
    except BaseException:
        if undo_after:
            changes.rollback()
        raise
    if failed:
        return failed
    values = plan['values']
    # The account is generated (new_account) and read by the service and Odoo: nothing to fill in.
    steps = []
    if 'adopted_environment' in plan:
        # S7: setup never syncs an adopted environment; bootstrap --apply does, to the locks.
        requirements = Path(values['REQUIREMENTS_DIR'])
        inputs = ['runtime.in', 'dev.in', *([locks.OVERRIDES] if (requirements / locks.OVERRIDES).is_file() else [])]
        described = ', '.join(inputs[:-1]) + f' and {inputs[-1]}'
        steps.append(f'the locks in {requirements} describe {described}: {program} --project {root} bootstrap '
                     f'--apply syncs the adopted environment {values["PROJECT_ENVIRONMENT"]} to them (it changes the '
                     'packages installed there)')
    elif any(step[0] == 'compile' for step in plan['after']) and not any(step[0] == 'environment' for step in plan['after']):
        steps.append(f'{program} --project {root} bootstrap --apply')
    # start-database names no env file: an agent harness may refuse a command that does (v0.16.0 S6).
    steps += [f'{program} --project {root} start-database', f'{program} --project {root} doctor']
    # init-dev-database needs the role accounts of [development] (tools/dev_users.py). A workspace
    # file that cannot be read now gets no edit advice: doctor reports the configuration.
    workspace_file = Path(values['WORKSPACE_ROOT']) / config.WORKSPACE_NAME
    try:
        development = isinstance(config.read_toml(workspace_file).get('development'), dict)
    except config.InvalidConfig:
        development = None
    if development is False:
        lines = migrate.toml_table('development', DEVELOPMENT).splitlines()
        steps.append(f'add these lines to {workspace_file} (docs/dev-database.md):'
                     + ''.join(f'\n       {line}' for line in lines))
    steps.append(f'{program} --project {root} init-dev-database <module> {values["DEV_PREFIX"]}manual')
    print('next steps:')
    for number, step in enumerate(steps, 1):
        print(f'  {number}. {step}')
    return 0


def after_steps(plan: dict, changes: Changes, rerun: str, undo_after: bool) -> int:
    """Compile the locks and create the environment of the plan: 0, or 2 after a failed step (with
    undo_after, a failed compile or uv venv rolls back every change first)."""
    program, root = config.program_name(), plan['root']
    for step in plan['after']:
        if step[0] == 'compile':
            if undo_after:
                for name in (*locks.LOCKS, locks.FINGERPRINT):
                    changes.keep(step[1] / name)
            if locks.compile_locks(step[1], step[2], rerun):
                if undo_after:
                    undone('uv pip compile failed', changes.rollback())
                return 2
            print(f'compiled {step[1]}/runtime.txt, dev.txt and lock.sha256', flush=True)
            continue
        _kind, environment, python, lock = step
        absent = not os.path.lexists(environment)
        missing = [directory for directory in environment.parents if not os.path.lexists(directory)]
        environment.parent.mkdir(parents=True, exist_ok=True)
        if undo_after:
            changes.made(list(reversed(missing)))
        for command in (['uv', 'venv', '--python', python, str(environment)],
                        ['uv', 'pip', 'sync', '--python', str(environment / 'bin/python'), str(lock)]):
            try:
                status = subprocess.run(command, env=locks.uv_environment()).returncode
            except OSError:
                status = 127
            if status == 0:
                if command[1] == 'venv':
                    # oasis' mark (v0.17.0 S1): its drift from the locks is a FAIL, an adopted one's a WARN.
                    # A mark that cannot be written is a warning (try_mark prints it): setup goes on.
                    environment_origin.try_mark(environment, f'{program} setup --apply')
                continue
            if command[1] == 'venv' and undo_after:
                # What uv venv left of an environment that did not exist: removed when empty, else reported.
                if absent and os.path.lexists(environment):
                    changes.made([environment])
                undone(f'uv venv failed (exit {status})', changes.rollback(),
                       f'fix it, then run {rerun} again.')
            elif command[1] == 'pip':
                # The environment exists now: a second setup run keeps it unsynced, bootstrap syncs it.
                print(f'ERROR: uv pip sync failed (exit {status}); the files above and the environment '
                      f'{environment} are kept: fix it, then run {program} --project {root} bootstrap --apply '
                      'to sync it.', file=sys.stderr)
            else:
                print(f'ERROR: uv venv failed (exit {status}); the files above are kept: fix it, then run '
                      f'{rerun} again.', file=sys.stderr)
            return 2
        print(f'created the environment {environment}', flush=True)
    return 0


def main(arguments: list[str]) -> int:
    if arguments in (['--help'], ['-h']):
        print(usage() + '\n' + HELP, end='')
        return 0
    options = parse_arguments(arguments)
    if options is None:
        print(usage(), file=sys.stderr)
        return 2
    try:
        answers = answered(options)
    except Refused as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 2
    if '--python' in options and '--environment' in options:
        print('ERROR: --python cannot be combined with --environment: an adopted environment keeps the Python of '
              'its pyvenv.cfg.', file=sys.stderr)
        return 2
    for option in ('--workspace', '--config-dir', '--environment'):
        if option in options and (not os.path.isabs(options[option]) or not os.path.isdir(options[option])):
            print(f'ERROR: {option} requires an absolute existing directory.', file=sys.stderr)
            return 2
    root = config.selected_root()
    if root is None:
        print(f'ERROR: {config.PROJECT_ROOT_REQUIRED}', file=sys.stderr)
        return 2
    questions = Questions(answers, interactive=False if '--json' in options else None)
    plan = None
    try:
        plan = make_plan(root, options, questions)
    except Refused as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 2
    except Interrupted:
        print('\nERROR: Interrupted at a question: nothing changed.', file=sys.stderr)
        return 130
    except Open as exc:
        # A question setup cannot go on without (v0.16.0 S3): --apply refuses as before; the plan lists it.
        if '--apply' in options:
            print(f'ERROR: {exc}', file=sys.stderr)
            return 2
    unused = [key for key in questions.answers if key not in questions.used]
    if unused:
        # An answer setup never used would otherwise look applied (v0.16.0 S3 review): refuse it.
        source = questions.answers[unused[0]][1].split()[0]
        print(f'ERROR: {source}: setup does not ask {unused[0]} for this checkout; nothing changed: drop it.',
              file=sys.stderr)
        return 2
    still_open = questions.open()
    if '--json' in options:
        print(json.dumps(plan_document(root, questions, plan)))
        return 0
    if '--apply' in options and still_open:
        for question in still_open:
            print(f'ERROR: open question {question}: {questions.refusals[question]}', file=sys.stderr)
        print(f'ERROR: nothing changed: answer the open questions, then run {config.program_name()} setup --apply '
              'again.', file=sys.stderr)
        return 2
    print('\n'.join(questions.lines), flush=True)
    if still_open:
        for question in still_open:
            print(f'open question {question}: {questions.refusals[question]}')
        print(OPEN_PLAN)
        return 0
    if not plan['actions'] and not plan['after']:
        print(f'nothing to set up: run {config.program_name()} --project {root} doctor')
        return 0
    if '--apply' not in options:
        print(DRY_RUN)
        return 0
    return apply_plan(plan)


def change_summary(path: Path, kind: str, lines: list[str]) -> str:
    """The plan line of one change (its first line that names path as a word), else what the change is."""
    for line in lines:
        if line[:1].isspace() or line.startswith(('kept', 'WARN', 'checkout:', 'workspace:', 'series:')):
            continue
        if any(word.rstrip(':').rstrip('/') == str(path) for word in line.split()):
            return line.rstrip(':')
    return f'create the directory {path}/' if kind == 'mkdir' else f'{kind} {path}'


def plan_document(root: Path, questions: Questions, plan: dict | None) -> dict:
    """The plan as one JSON object (docs/setup.md#the-plan-as-json): what setup inferred and from where, the
    changes it would make (never a value of the account), every question it met and the open ones. A plan
    that stopped at an open question (plan None) is not complete and lists no change."""
    changes = []
    for action in (plan or {}).get('actions', []):
        changes.append({'kind': action[0], 'path': str(action[1]),
                        'summary': change_summary(action[1], action[0], questions.lines)})
    for step in (plan or {}).get('after', []):
        if step[0] == 'compile':
            summary = (f'compile {step[1]}/runtime.txt, dev.txt and lock.sha256 with Python {step[2]} '
                       '(uv pip compile)')
        else:
            summary = (f'create the environment {step[1]} with Python {step[2]} (uv venv) and sync {step[3].name} '
                       '(uv pip sync)')
        changes.append({'kind': step[0], 'path': str(step[1]), 'summary': summary})
    still_open = questions.open()
    return {'format': 'oasis-setup-plan', 'version': 1, 'checkout': str(root), 'complete': plan is not None,
            'ready_to_apply': plan is not None and not still_open, 'inferred': questions.inferred,
            'changes': changes, 'questions': questions.listed, 'open': still_open, 'lines': questions.lines}


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
