#!/usr/bin/env python3
"""The plan of a new database (v0.20.0 S6, S12): `init-dev-database --plan`, the one command that creates a database.

Creating a database is the user's decision (Tier B in tools/policy.py, v0.20.0 S5), and so are the questions of
Odoo's database manager form: the plan lists them as questions, in the shape `setup --plan --json` uses
(docs/setup.md#questions-and-answers: id, text, options, recommended, flag, answer, origin; `open` lists the
ids still unanswered), and chooses none of them. An agent relays the open questions to the user and passes the
answers with --answer <id>=<value> (repeatable) or --answers <file.json> (one JSON object of ids and text
answers):

  suffix    the part of the name after the prefix and the checkout slug (no recommended answer).
  kind      dev, test or both (no recommended answer): <dev_prefix>[<slug>_]<suffix>, <test_prefix>[<slug>_]<suffix>
            or both, each created the same way (a test one fits in 56 bytes, as [tooling].test_database).
  module    the module it installs, one of the checkout's addon modules (no recommended answer).
  demo      no (recommended: without demo data) or yes (Odoo's demo data); open until answered.
  language  one of the Odoo source's languages, as the form lists them (exp_list_lang: base/data/res.lang.csv,
            en_US alone when it cannot be read); recommended en_US, open until answered.
  country   none or one of the Odoo source's countries (exp_list_countries: base/data/res_country_data.xml; a
            code in either case); no recommended answer. Every supported series takes it the same way (country_code of
            exp_create_database: the company's country and currency, the users' time zone when it has one).

The prefixes are the workspace's [tooling].dev_prefix and test_prefix, shown as inferred values: changing one is
a workspace setting (docs/workspace-file.md), not an answer of this plan. Once every question is answered, the
plan runs init-dev-database --dry-run for each database, so the name guards of tools/common.sh and the checks of
tools/dev_users.py decide whether it is valid, prints it, then the exact --confirm command of each database. It
never creates anything: exit 0 with open questions or with the commands, exit 2 when an answer is refused (an
unknown id, an answer that is not one of the options, a name the guards refuse).

Usage (through init-dev-database --plan):
  database_plan.py init-dev-database [--json] [--answer <id>=<value>]... [--answers <file.json>]
"""
import importlib.util
import json
from pathlib import Path
import shlex
import subprocess
import sys

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
import config  # noqa: E402
import dev_users  # noqa: E402

COMMANDS = ('init-dev-database',)
# The oasis options of init-dev-database (tools/init-dev-database).
DEMO_OPTION = '--with-demo'
LANGUAGE_OPTION = '--lang'
COUNTRY_OPTION = '--country'
NO_COUNTRY = 'none'
KINDS = ('dev', 'test', 'both')
# Up to this many options, a refused answer lists them; more (the languages, the countries), the plan's JSON does.
LISTED_OPTIONS = 10
DRY_RUN_TIMEOUT_SECONDS = 120
OPEN_PLAN = ('nothing changed: answer the open questions above (docs/dev-database.md#the-plan-of-a-new-database), '
             'then run the plan again')


class Refused(Exception):
    """A refusal before anything ran: exit 2 with the message."""


def usage(command: str) -> str:
    return (f'Usage: {config.usage_name()} {command} --plan [--json] [--answer <id>=<value>]... '
            '[--answers <file.json>]')


def parse_arguments(arguments: list[str]) -> dict | None:
    """{'json': bool, 'answer': [...], 'answers': path or None}, or None for a usage error (no abbreviations)."""
    options = {'json': False, 'answer': [], 'answers': None}
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        key, equals, value = argument.partition('=')
        if argument == '--json' and not options['json']:
            options['json'] = True
        elif key == '--answer' and equals:
            options['answer'].append(value)
        elif argument == '--answer' and index + 1 < len(arguments):
            index += 1
            options['answer'].append(arguments[index])
        elif key == '--answers' and equals and options['answers'] is None:
            options['answers'] = value
        elif argument == '--answers' and index + 1 < len(arguments) and options['answers'] is None:
            index += 1
            options['answers'] = arguments[index]
        else:
            return None
        index += 1
    return options


def answered(options: dict, ids: tuple[str, ...]) -> dict:
    """{question id: (answer, where it came from)} of --answers and --answer, as setup reads them."""
    answers = {}
    path = options['answers']
    if path is not None:
        try:
            document = json.loads(Path(path).read_text(encoding='utf-8'))
        except (OSError, UnicodeError, ValueError):
            document = None
        if not isinstance(document, dict) or not all(isinstance(value, str) for value in document.values()):
            raise Refused(f'--answers {path} must be a JSON object of question ids and text answers.')
        answers = {key: (value, f'--answers {path}') for key, value in document.items()}
    for item in options['answer']:
        key, equals, value = item.partition('=')
        if not equals or not key:
            raise Refused(f'--answer {item}: use --answer <question id>=<value>.')
        if key in answers:
            raise Refused(f'The question {key} is answered twice: by {answers[key][1]} and by --answer.')
        answers[key] = (value, '--answer')
    for key, (_value, source) in answers.items():
        if key not in ids:
            raise Refused(f'{source}: unknown question {key} (this plan asks {", ".join(ids)}).')
    return answers


def addon_modules(roots: str) -> list[str]:
    """The checkout's addon modules, as the menu lists them (tools/actions.py addon_modules)."""
    spec = importlib.util.spec_from_file_location('oasis_plan_actions', TOOLS / 'actions.py')
    actions = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(actions)
    return actions.addon_modules(roots)


def namespace(prefix: str, slug: str) -> str:
    """The managed prefix of this checkout's databases (common.sh checkout_database_name without its rest)."""
    return f'{prefix}{slug}_' if slug else prefix


def country_options(source: str) -> list[dict]:
    """none, then the Odoo source's countries (none alone when its file cannot be read)."""
    try:
        listed = dev_users.countries(source)
    except dev_users.CountryError:
        listed = []
    return [{'value': NO_COUNTRY, 'label': "none: no country (the database manager form's empty choice)"},
            *({'value': code, 'label': name} for code, name in listed)]


def questions(command: str, values: dict) -> list[dict]:
    slug = values.get('CHECKOUT_SLUG', '')
    dev, test = namespace(values['DEV_PREFIX'], slug), namespace(values['TEST_PREFIX'], slug)
    modules = addon_modules(values['ADDON_ROOTS'])
    form = 'as its database manager form does'
    return [
        {'id': 'suffix', 'text': f'Name of the new database after {dev} or {test} (letters, digits and underscores)',
         'options': [], 'recommended': None, 'flag': '--answer suffix=<name>'},
        {'id': 'kind', 'text': 'Kind of the new database: dev, test or both',
         'options': [{'value': 'dev', 'label': f'a development database {dev}<suffix>'},
                     {'value': 'test', 'label': f'a test database {test}<suffix>'},
                     {'value': 'both', 'label': f'both: {dev}<suffix> and {test}<suffix>'}],
         'recommended': None, 'flag': '--answer kind=<dev|test|both>'},
        {'id': 'module', 'text': f'Module {command} installs in the new database',
         'options': [{'value': module, 'label': module} for module in modules],
         'recommended': None, 'flag': '--answer module=<module>'},
        {'id': 'demo', 'text': "Load Odoo's demo data into the new database",
         'options': [{'value': 'no', 'label': 'without demo data'},
                     {'value': 'yes', 'label': "with Odoo's demo data and [development].demo_modules"}],
         'recommended': 'no', 'flag': '--answer demo=<no|yes>'},
        {'id': 'language', 'text': f'Language of the new database: Odoo loads it and gives it to the administrator, '
                                   f'{form}',
         'options': [{'value': code, 'label': name} for code, name in dev_users.languages(values['ODOO_SOURCE'])],
         'recommended': dev_users.DEFAULT_LANGUAGE, 'flag': '--answer language=<code>'},
        {'id': 'country', 'text': "Country of the new database's company: Odoo sets the company's country and currency "
                                  f"(and the users' time zone when the country has only one), {form}",
         'options': country_options(values['ODOO_SOURCE']), 'recommended': None,
         'flag': f'--answer country=<code|{NO_COUNTRY}>'},
    ]


def inferred(values: dict) -> dict:
    setting = 'a workspace setting (docs/workspace-file.md): change it there, not per database'
    return {'dev_prefix': {'value': values['DEV_PREFIX'], 'origin': f'[tooling].dev_prefix, {setting}'},
            'test_prefix': {'value': values['TEST_PREFIX'], 'origin': f'[tooling].test_prefix, {setting}'},
            'checkout_slug': {'value': values.get('CHECKOUT_SLUG') or None,
                              'origin': 'the checkout: its databases go after the prefix and the slug'}}


def resolve(listed: list[dict], answers: dict) -> list[dict]:
    """The questions with their answers (None: open); an answer that is not one of a question's options is
    refused (the suffix has none: the guards of the dry run decide)."""
    result = []
    for question in listed:
        answer, origin = None, None
        if question['id'] in answers:
            answer, source = answers[question['id']]
            values = [option['value'] for option in question['options']]
            if question['id'] == 'country' and answer.lower() in values:
                # Odoo's codes are lowercase and its search ignores the case (ilike): AR is ar.
                answer = answer.lower()
            if values and answer not in values:
                if len(values) > LISTED_OPTIONS:
                    listed_values = (f'one of the {len(values)} options of the question (init-dev-database --plan '
                                     '--json lists them)')
                else:
                    listed_values = ', '.join(values[:-1]) + f' or {values[-1]}' if len(values) > 1 else values[0]
                raise Refused(f'Invalid answer {answer} for {question["id"]}: answer {listed_values}.')
            if question['id'] == 'module' and not values:
                raise Refused(f'Invalid answer {answer} for module: the checkout has no addon module.')
            if question['id'] == 'suffix' and not answer:
                raise Refused('Invalid answer for suffix: the name needs at least one character after the prefix.')
            origin = f'from {source.split()[0]}'
        result.append({**question, 'answer': answer, 'origin': origin})
    return result


def databases(command: str, values: dict, answer: dict) -> list[dict]:
    """The databases the answers give, in order (dev first), each with its dry-run arguments and its
    --confirm command."""
    slug = values.get('CHECKOUT_SLUG', '')
    kinds = ('dev', 'test') if answer['kind'] == 'both' else (answer['kind'],)
    country = None if answer['country'] == NO_COUNTRY else answer['country']
    options = [*([DEMO_OPTION] if answer['demo'] == 'yes' else []), LANGUAGE_OPTION, answer['language'],
               *([COUNTRY_OPTION, country] if country else [])]
    found = []
    for kind in kinds:
        name = namespace(values['DEV_PREFIX'] if kind == 'dev' else values['TEST_PREFIX'], slug) + answer['suffix']
        arguments = [*options, answer['module'], name]
        found.append({'database': name, 'kind': kind, 'arguments': arguments,
                      'command': shlex.join([config.program_name(), '--project', values['PROJECT_ROOT'], command,
                                             *arguments, '--confirm', name]),
                      'module': answer['module'], 'demo': answer['demo'] == 'yes', 'language': answer['language'],
                      'country': country})
    return found


def dry_run(command: str, arguments: list[str]) -> list[str]:
    """The lines of the command's own --dry-run (its guards included); Refused with its error when it refuses."""
    try:
        result = subprocess.run(['bash', str(TOOLS / command), *arguments, '--dry-run'], capture_output=True,
                                text=True, stdin=subprocess.DEVNULL, timeout=DRY_RUN_TIMEOUT_SECONDS)
    except (OSError, subprocess.SubprocessError) as exc:
        raise Refused(f'{command} --dry-run could not run: {exc}.') from exc
    if result.returncode != 0:
        message = result.stderr.strip() or f'{command} --dry-run exited {result.returncode}.'
        raise Refused(message[7:] if message.startswith('ERROR: ') else message)
    return result.stdout.splitlines()


def plan(command: str, options: dict, root: Path) -> dict:
    values = config.load(root)
    listed = questions(command, values)
    resolved = resolve(listed, answered(options, tuple(question['id'] for question in listed)))
    still_open = [question['id'] for question in resolved if question['answer'] is None]
    found = inferred(values)
    lines = [f'checkout: {root}']
    lines += [f'{key}: {item["value"]} ({item["origin"]})' for key, item in found.items() if item['value'] is not None]
    lines += [f'{question["id"]}: {question["answer"]} ({question["origin"]})'
              for question in resolved if question['answer'] is not None]
    planned = []
    if still_open:
        for question in resolved:
            if question['answer'] is None:
                recommended = question['recommended']
                lines.append(f'open question {question["id"]}: {question["text"]}. Answer with {question["flag"]} '
                             + (f'(recommended: {recommended}).' if recommended is not None
                                else '(no recommended answer).'))
        lines.append(OPEN_PLAN)
    else:
        planned = databases(command, values, {question['id']: question['answer'] for question in resolved})
        for entry in planned:
            lines += dry_run(command, entry.pop('arguments'))
        lines += [f'run: {entry["command"]}' for entry in planned]
        lines.append(f'nothing changed: creating a database is Tier B (oasis policy --json): the user confirms '
                     f'{"each command" if len(planned) > 1 else "the command"} above')
    return {'format': 'oasis-database-plan', 'version': 1, 'command': command, 'checkout': str(root),
            'complete': not still_open, 'inferred': found, 'questions': resolved, 'open': still_open,
            'databases': planned, 'lines': lines}


def main(arguments: list[str]) -> int:
    if not arguments or arguments[0] not in COMMANDS:
        print('Usage: database_plan.py init-dev-database [--json] [--answer <id>=<value>]... '
              '[--answers <file.json>]', file=sys.stderr)
        return 2
    command = arguments[0]
    options = parse_arguments(arguments[1:])
    if options is None:
        print(usage(command), file=sys.stderr)
        return 2
    root = config.selected_root()
    if root is None:
        print(config.PROJECT_ROOT_REQUIRED, file=sys.stderr)
        return 2
    try:
        document = plan(command, options, root)
    except Refused as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 2
    except config.InvalidConfig as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 2
    if options['json']:
        print(json.dumps(document, indent=2))
    else:
        print('\n'.join(document['lines']))
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
