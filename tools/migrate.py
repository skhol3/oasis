#!/usr/bin/env python3
"""Convert the legacy profiles of a project's checkouts into one oasis-workspace.toml (`oasis migrate`).

User-run only: it rewrites project files (the Gentle Shell bash guard blocks agents). Without
--apply it prints the plan and changes nothing. With --apply it writes the workspace file (and an
oasis-checkout.toml for each checkout whose profile sets checkout_slug), removes the location
options addons_path and data_dir from odoo.conf (the original is kept as odoo.conf.bak-<stamp>,
0600), rewrites lock.sha256 relative to its own directory and renames every .odoo19-agent.toml
to .odoo19-agent.toml.bak-<stamp>. Every checkout must then load the same configuration as
before (tools/config.py, and the addons path and data directory of its Odoo command line); on
any mismatch every change is undone and the exit status is 1. The content of odoo.conf and of
the environment file is never printed.

The only reader of the legacy profile: tools/config.py refuses a checkout that has one, so
legacy_load reads it here with the rules config.py applied to it before v0.12.0.
"""
import configparser
import errno
import hashlib
import importlib.util
import os
import signal
from pathlib import Path
import re
import subprocess
import sys
import time
import tomllib

PROFILE = '.odoo19-agent.toml'
# What a legacy profile had to declare: the profile format only ever served this series.
LEGACY_VERSION = '19.0'
LEGACY_PYTHON = '3.12'
# Migrated sections; the advisory ones stay in the profile backups.
MIGRATED = ('tooling', 'development')
# [tooling] keys a workspace derives (from odoo_version) or keeps per checkout (oasis-checkout.toml).
DERIVED = ('version', 'python_version')
SLUG = 'checkout_slug'
# Tooling paths besides config.PATHS, all resolved from the profile's checkout.
OPTIONAL_PATHS = ('logs', 'data_dir', 'lint_rcfile')
# odoo.conf options that depend on where the checkouts live; oasis passes them on the command line.
LOCATION_OPTIONS = ('addons_path', 'data_dir')
OPTION = re.compile(r'^([^\s=:\[#;][^=:]*?)\s*[=:]')
SECTION = re.compile(r'^\[([^\]]+)\]')
LOCK_LINE = re.compile(r'^([0-9a-fA-F]{64}) ([ *])(.+)$')
# Variables a workspace sets by design differently from a profile.
WORKSPACE_ONLY = ('WORKSPACE_ROOT', 'ENVIRONMENT_NAME', 'DATA_DIR')
HEADER = '# Written by oasis migrate. Paths are relative to this file, addons_paths to each checkout.\n'
GIT_TIMEOUT_SECONDS = 30
HELP = '''
Converts the .odoo19-agent.toml of every checkout of this repository (git worktree list) into
one oasis-workspace.toml in <dir>: by default the deepest directory above every checkout and the
profile's odoo.conf; --workspace names another one above every checkout. The profiles must agree
on every [tooling] and [development] value once resolved, except checkout_slug, which goes to
the checkout's oasis-checkout.toml. Paths become relative to <dir>; addons_paths stays relative
to each checkout. addons_path and data_dir are removed from odoo.conf (data_dir moves to
[tooling].data_dir; the original is kept as odoo.conf.bak-<stamp>), lock.sha256 is rewritten
relative to its directory with the same hashes, and each profile is renamed to
.odoo19-agent.toml.bak-<stamp>. Advisory sections are not migrated.

Without --apply it prints the plan and changes nothing. With --apply every checkout must load
the same configuration afterwards; otherwise every change is undone (exit 1). --plan asks for
the plan explicitly and can never apply: together with --apply it is a usage error.
'''


class Refused(Exception):
    """A refusal before any change: exit 2 with the message."""


def sibling(name: str):
    """A packaged helper loaded from its file (python3 -I keeps the tools directory off sys.path)."""
    spec = importlib.util.spec_from_file_location(f'oasis_migrate_{name}', Path(__file__).with_name(f'{name}.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def usage() -> str:
    return f'Usage: {sibling("config").usage_name()} migrate [--workspace <dir>] [--apply | --plan]'


def parse_arguments(arguments: list[str]):
    """(apply, workspace or None), or None for a usage error (--plan with --apply is one)."""
    apply, plan, workspace, index = False, False, None, 0
    while index < len(arguments):
        argument = arguments[index]
        if argument == '--apply' and not apply and not plan:
            apply = True
        elif argument == '--plan' and not plan and not apply:
            plan = True
        elif argument == '--workspace' and workspace is None and index + 1 < len(arguments):
            index += 1
            workspace = arguments[index]
        elif argument.startswith('--workspace=') and workspace is None:
            workspace = argument.split('=', 1)[1]
        else:
            return None
        index += 1
    return apply, workspace


# -- reading ---------------------------------------------------------------------------------------

def git_env():
    return {key: value for key, value in os.environ.items()
            if key not in ('GIT_DIR', 'GIT_WORK_TREE', 'GIT_COMMON_DIR', 'GIT_INDEX_FILE', 'GIT_PREFIX')}


def checkouts_of(root: Path, values: dict) -> list[tuple[Path, str]]:
    """Every checkout of root's repository with its kind (main first), or root alone outside git."""
    if values['CHECKOUT_KIND'] == 'none':
        return [(root, 'none')]
    main = values['CHECKOUT_MAIN_ROOT']
    if not main:
        raise Refused('migrate needs git to list the worktrees of this checkout.')
    try:
        result = subprocess.run(['git', '-C', main, 'worktree', 'list', '--porcelain'], capture_output=True,
                                text=True, env=git_env(), timeout=GIT_TIMEOUT_SECONDS)
    except (OSError, subprocess.SubprocessError) as exc:
        raise Refused('Cannot list the worktrees of this repository.') from exc
    if result.returncode != 0:
        raise Refused('Cannot list the worktrees of this repository.')
    found = []
    for block in result.stdout.split('\n\n'):
        lines = block.splitlines()
        if not lines or not lines[0].startswith('worktree ') or 'bare' in lines:
            continue
        path = Path(lines[0][len('worktree '):])
        if any(line.startswith('prunable') for line in lines) or not path.is_dir():
            raise Refused(f'Worktree {path} is missing; restore it or run git worktree prune.')
        found.append((path.resolve(), 'linked' if found else 'main'))
    if root not in [path for path, _kind in found]:
        raise Refused(f'git does not list {root} as a worktree of its repository.')
    return found


def legacy_load(config, checkout: Path) -> dict:
    """tools/config.py's assignments for a checkout configured by its legacy profile, as
    config.py read it: the same validation, every path resolved from the checkout, an empty
    WORKSPACE_ROOT and no named environment."""
    try:
        with (checkout / PROFILE).open('rb') as stream:
            document = tomllib.load(stream)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise config.InvalidConfig('Invalid tooling configuration.') from exc
    tooling = document.get('tooling')
    if not isinstance(tooling, dict):
        raise config.InvalidConfig('Invalid tooling configuration.')
    if tooling.get('version') != LEGACY_VERSION or tooling.get('python_version') != LEGACY_PYTHON:
        raise config.InvalidConfig(f'Tooling requires Odoo {LEGACY_VERSION} and Python {LEGACY_PYTHON}.')
    return config.assignments(document, checkout, checkout, None, '')


def read_profile(path: Path) -> dict:
    try:
        with path.open('rb') as stream:
            return tomllib.load(stream)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise Refused(f'Invalid tooling configuration: {path}') from exc


def comparable(document: dict, checkout: Path, path_keys) -> dict:
    """The migrated values of a profile, paths resolved from its checkout, checkout_slug left out."""
    flat = {}
    for section in MIGRATED:
        table = document.get(section, {})
        if not isinstance(table, dict):
            flat[section] = table
            continue
        for key, value in table.items():
            if section == 'tooling' and key == SLUG:
                continue
            if section == 'tooling' and key in path_keys and isinstance(value, str):
                value = str((checkout / value).resolve())
            flat[f'{section}.{key}'] = value
    return flat


def relative(lexical: str, resolved: Path, base: Path) -> str:
    """A path relative to base that resolves to resolved: the lexical form when it does (it keeps
    symlinked directories), else the resolved one."""
    candidate = os.path.relpath(os.path.normpath(lexical), base)
    if (base / candidate).resolve() == resolved:
        return candidate
    return os.path.relpath(resolved, base)


def options_of(text: str, conf: Path) -> dict:
    """Every section's options as Odoo reads them (RawConfigParser); errors name the file only."""
    parser = configparser.RawConfigParser()
    try:
        parser.read_string(text, source=str(conf))
    except configparser.Error as exc:
        raise Refused(f'Cannot read {conf}: invalid configuration file.') from exc
    options = {section: dict(parser.items(section)) for section in parser.sections()}
    options['DEFAULT'] = dict(parser.defaults())
    return options


def without_location_options(text: str) -> str:
    """odoo.conf text without the addons_path and data_dir lines of [options] (and their
    continuation lines); every other line is kept as it is."""
    kept, section, dropping = [], None, False
    for line in text.splitlines(keepends=True):
        body = line.rstrip('\r\n')
        if dropping and body[:1] in (' ', '\t') and body.strip():
            continue
        dropping = False
        heading = SECTION.match(body)
        if heading:
            section = heading.group(1).strip()
        option = OPTION.match(body)
        if section == 'options' and option and option.group(1).strip().lower() in LOCATION_OPTIONS:
            dropping = True
            continue
        kept.append(line)
    return ''.join(kept)


def lock_entries(text: str):
    """[(digest, mode, path)] of a sha256sum file, or None when a line is not one oasis can rewrite."""
    lines = text.split('\n')
    if lines and lines[-1] == '':
        lines.pop()
    entries = []
    for line in lines:
        match = LOCK_LINE.match(line)
        if not match:
            return None
        entries.append(tuple(match.groups()))
    return entries or None


def lock_verifies(entries, base: Path) -> bool:
    """Whether every entry, relative to base, names a file with its hash (sha256sum --check)."""
    for digest, _mode, name in entries:
        path = base / name
        try:
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest.lower():
                return False
        except OSError:
            return False
    return True


def lock_change(lock: Path, root: Path):
    """The plan line for lock.sha256 and its entries relative to its directory (None: kept as it is).

    Legacy entries are relative to the checkout, where check-environment ran sha256sum; they may
    also resolve from the lock's directory when both lie at the same depth, and are still rewritten.
    """
    try:
        entries = lock_entries(lock.read_bytes().decode('utf-8'))
    except (OSError, UnicodeError):
        entries = None
    if entries is None:
        return f'keep {lock}: it has lines oasis cannot rewrite; regenerate it', None
    if lock_verifies(entries, root):
        rewritten = [(digest, mode, relative(os.path.join(root, name), (root / name).resolve(), lock.parent))
                     for digest, mode, name in entries]
        if rewritten == entries:
            return f'keep {lock}: already relative to its directory', None
        if (all('\\' not in name and '\n' not in name for _digest, _mode, name in rewritten)
                and lock_verifies(rewritten, lock.parent)):
            return f'rewrite {lock}: {len(entries)} entries relative to its directory, hashes unchanged', rewritten
        return f'keep {lock}: its entries cannot be made relative to its directory; regenerate it', None
    if lock_verifies(entries, lock.parent):
        return f'keep {lock}: already relative to its directory', None
    return f'keep {lock}: it does not match from its directory or from {root}; regenerate it', None


def untrusted(directory: Path) -> str:
    """Why a file written in directory would be refused by tools/config.py (trusted), or ''."""
    try:
        info = directory.stat()
    except OSError:
        return f'cannot inspect {directory}'
    if info.st_uid not in (os.getuid(), 0):
        return f'{directory} is not owned by the current user or root'
    if info.st_mode & 0o022:
        return f'{directory} is writable by group or others'
    if not os.access(directory, os.W_OK | os.X_OK):
        return f'{directory} is not writable'
    return ''


# -- TOML ------------------------------------------------------------------------------------------

def toml_string(value: str) -> str:
    if "'" not in value and all(char == '\t' or (ord(char) >= 0x20 and ord(char) != 0x7f) for char in value):
        return f"'{value}'"
    escaped = []
    for char in value:
        if char in '\\"':
            escaped.append('\\' + char)
        elif ord(char) < 0x20 or ord(char) == 0x7f:
            escaped.append(f'\\u{ord(char):04x}')
        else:
            escaped.append(char)
    return '"' + ''.join(escaped) + '"'


def toml_key(key: str) -> str:
    return key if re.fullmatch(r'[A-Za-z0-9_-]+', key) else toml_string(key)


def toml_value(value) -> str:
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        return toml_string(value)
    if isinstance(value, list):
        return '[' + ', '.join(toml_value(item) for item in value) + ']'
    if isinstance(value, dict):
        return '{' + ', '.join(f'{toml_key(key)} = {toml_value(item)}' for key, item in value.items()) + '}'
    raise Refused(f'Cannot write a value of type {type(value).__name__} to the workspace file.')


def toml_table(name: str, table: dict) -> str:
    return f'[{name}]\n' + ''.join(f'{toml_key(key)} = {toml_value(value)}\n' for key, value in table.items())


# -- plan ------------------------------------------------------------------------------------------

def make_plan(root: Path, workspace_argument, config, reader, stamp: str) -> dict:
    """Every line to print, every change to make and what verification needs; nothing is written."""
    try:
        values = legacy_load(config, root)
    except config.InvalidConfig as exc:
        raise Refused(str(exc)) from exc
    checkouts = checkouts_of(root, values)
    paths = [path for path, _kind in checkouts]
    path_keys = (*config.PATHS, *OPTIONAL_PATHS)
    profiles, before, effective_before = {}, {}, {}
    for path in paths:
        if (path / PROFILE).is_file():
            profiles[path] = read_profile(path / PROFILE)
            try:
                before[path] = legacy_load(config, path)
                effective_before[path] = effective(reader, before[path])
            except config.InvalidConfig as exc:
                raise Refused(f'{path}: {exc}') from exc
            except reader.ConfError as exc:
                raise Refused(str(exc)) from exc
    flats = [comparable(document, path, path_keys) for path, document in profiles.items()]
    missing = object()
    differing = [key for key in sorted({key for flat in flats for key in flat})
                 if any(flat.get(key, missing) != flats[0].get(key, missing) for flat in flats)]
    if differing:
        raise Refused(f'Cannot migrate: the profiles of the checkouts disagree on {", ".join(differing)}.')

    if workspace_argument is None:
        directory = Path(os.path.commonpath([*map(str, paths), values['ODOO_CONFIG']]))
        while any(directory.is_relative_to(path) for path in paths):
            directory = directory.parent
    else:
        directory = Path(workspace_argument).resolve()
        if not all(path.is_relative_to(directory) and path != directory for path in paths):
            raise Refused(f'Refusing --workspace {workspace_argument}: it is not above every checkout '
                          f'({", ".join(map(str, paths))}).')
    workspace = directory / config.WORKSPACE_NAME
    if os.path.lexists(workspace):
        raise Refused(f'{workspace} already exists.')
    reason = untrusted(directory)
    if reason:
        raise Refused(f'Refusing to write {workspace}: {reason}.')
    for path in paths:
        for parent in (path, *path.parents):
            if parent == directory:
                break
            if (parent / config.WORKSPACE_NAME).is_file():
                raise Refused(f'{parent / config.WORKSPACE_NAME} would be found before {workspace} from {path}.')

    document = profiles[root]
    tooling = {}
    for key, value in document['tooling'].items():
        if key in DERIVED or key == SLUG:
            continue
        if key in path_keys and isinstance(value, str):
            value = relative(os.path.join(root, value), (root / value).resolve(), directory)
        tooling[key] = value
    development = document.get('development')
    if development is not None and not isinstance(development, dict):
        raise Refused(f'Invalid [development] in {root / PROFILE}.')

    lines = [f'workspace: {directory}']
    for path, kind in checkouts:
        lines.append(f'checkout: {path} ({kind}{"" if path in profiles else ", no profile"})')
    actions = []

    # odoo.conf: drop the location options; data_dir moves to [tooling].data_dir.
    conf = Path(values['ODOO_CONFIG'])
    try:
        conf_bytes = conf.read_bytes()
        conf_text = conf_bytes.decode('utf-8')
    except (OSError, UnicodeError) as exc:
        raise Refused(f'Cannot read {conf}.') from exc
    original = options_of(conf_text, conf)
    present = [option for option in LOCATION_OPTIONS if option in original.get('options', {})]
    moved = False
    if 'data_dir' in present and 'data_dir' not in tooling:
        expanded = os.path.expanduser(original['options']['data_dir'].strip())
        if not os.path.isabs(expanded):
            raise Refused(f'Cannot move the data_dir of {conf} to [tooling].data_dir: it is not an absolute path.')
        tooling['data_dir'] = relative(expanded, Path(expanded).resolve(), directory)
        moved = True
    conf_lines = []
    if present:
        rewritten = without_location_options(conf_text)
        expected = {section: dict(options) for section, options in original.items()}
        for option in present:
            expected['options'].pop(option)
        if options_of(rewritten, conf) != expected:
            raise Refused(f'Cannot remove {" and ".join(present)} from {conf} line by line; edit it by hand.')
        backup = conf.with_name(f'{conf.name}.bak-{stamp}')
        if os.path.lexists(backup):
            raise Refused(f'{backup} already exists.')
        conf_lines = [f'back up {conf} as {backup.name}',
                      f'remove {" and ".join(present)} from {conf}'
                      + ('; data_dir moves to [tooling].data_dir' if moved else '')]
        conf_actions = [('create', backup, conf_bytes, 0o600), ('replace', conf, rewritten.encode('utf-8'))]
    else:
        conf_actions = []

    text = HEADER + f'workspace_version = 1\nodoo_version = {toml_value(document["tooling"]["version"])}\n'
    text += '\n' + toml_table('tooling', tooling)
    if development is not None:
        text += '\n' + toml_table('development', development)
    intended = {'workspace_version': 1, 'odoo_version': document['tooling']['version'], 'tooling': tooling}
    if development is not None:
        intended['development'] = development
    if tomllib.loads(text) != intended:
        raise Refused('Cannot write these values to the workspace file.')
    lines.append(f'write {workspace}')
    lines += [f'  {line}' if line else '' for line in text.splitlines()]
    actions.append(('create', workspace, text.encode('utf-8'), 0o600))

    for path, document_of in profiles.items():
        slug = document_of['tooling'].get(SLUG)
        if slug is None:
            continue
        target = path / config.CHECKOUT_NAME
        if os.path.lexists(target):
            raise Refused(f'{target} already exists.')
        reason = untrusted(path)
        if reason:
            raise Refused(f'Refusing to write {target}: {reason}.')
        checkout_text = f'[tooling]\n{SLUG} = {toml_value(slug)}\n'
        lines.append(f'write {target}')
        lines += [f'  {line}' for line in checkout_text.splitlines()]
        actions.append(('create', target, checkout_text.encode('utf-8'), 0o600))

    # The conf backup and rewrite run last (below), in the order the plan shows them, so a process
    # killed before them leaves a conf that still names its paths and still works.

    # lock.sha256: entries relative to its directory, the same hashes.
    lock = Path(values['REQUIREMENTS_DIR']) / 'lock.sha256'
    rewritten_lock = None
    if lock.is_file():
        line, rewritten_lock = lock_change(lock, root)
        lines.append(line)
        if rewritten_lock is not None:
            new_lock = ''.join(f'{digest} {mode}{name}\n' for digest, mode, name in rewritten_lock)
            actions.append(('replace', lock, new_lock.encode('utf-8')))

    for path in profiles:
        target = path / f'{PROFILE}.bak-{stamp}'
        if os.path.lexists(target):
            raise Refused(f'{target} already exists.')
        lines.append(f'rename {path / PROFILE} to {target.name}')
        actions.append(('rename', path / PROFILE, target))
    lines += conf_lines
    actions += conf_actions
    advisory = [f'[{key}]' if isinstance(value, dict) else key
                for key, value in document.items() if key not in MIGRATED]
    if advisory:
        lines.append(f'not migrated: {", ".join(advisory)} (kept in the profile backups)')
    return {'lines': lines, 'actions': actions, 'paths': paths, 'before': before,
            'effective': effective_before, 'directory': directory, 'workspace': workspace,
            'lock': (lock, rewritten_lock)}


def effective(reader, values: dict):
    """The addons path items and data directory Odoo gets for a checkout (config.py values): from
    its command line (odoo_addons_path.config_arguments), else from odoo.conf, else None."""
    arguments = reader.config_arguments(values)
    conf = values['ODOO_CONFIG']
    addons = next((argument.split('=', 1)[1] for argument in arguments
                   if argument.startswith('--addons-path=')), None)
    if addons is None:
        addons = reader.read_addons_path(conf)
    data = next((argument.split('=', 1)[1] for argument in arguments if argument.startswith('--data-dir=')), None)
    if data is None:
        data = reader.read_option(conf, 'data_dir')
    items = None
    if addons is not None:
        items = []
        for item in addons.split(','):
            item = os.path.expanduser(item.strip())
            if item:
                items.append(str(Path(item).resolve()) if os.path.isabs(item) else item)
    data = os.path.expanduser(data.strip()) if data else ''
    return items, (str(Path(data).resolve()) if data else None)


# -- apply -----------------------------------------------------------------------------------------

def write_in_place(path: Path, data: bytes, opened=None):
    """Replace a file's content, keeping its inode, mode and owner.

    `opened` is called once the file is open for writing and before anything is written, so a
    caller can register its undo step only for a file that may actually change.
    """
    with path.open('r+b') as stream:
        if opened is not None:
            opened()
        stream.write(data)
        stream.truncate()
        stream.flush()
        os.fsync(stream.fileno())


class Changes:
    """The changes made so far, undone in reverse order by rollback."""

    def __init__(self):
        self.undo = []

    def apply(self, action):
        kind = action[0]
        if kind == 'create':
            _kind, path, data, mode = action
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
            self.undo.append(('remove', path))
            with os.fdopen(descriptor, 'wb') as stream:
                os.fchmod(stream.fileno(), mode)
                stream.write(data)
        elif kind == 'replace':
            _kind, path, data = action
            original = path.read_bytes()
            # Registered only once the file opened for writing: a read-only file is never
            # touched, so there is nothing to undo and no false "could not be undone".
            write_in_place(path, data, lambda: self.undo.append(('restore', path, original)))
        else:
            _kind, source, target = action
            if os.path.lexists(target):
                raise FileExistsError(errno.EEXIST, os.strerror(errno.EEXIST), str(target))
            os.rename(source, target)
            self.undo.append(('rename', target, source))

    def rollback(self) -> list[str]:
        """Undo every change; the paths that could not be restored, with the reason."""
        failed = []
        for step in reversed(self.undo):
            try:
                if step[0] == 'remove':
                    os.unlink(step[1])
                elif step[0] == 'restore':
                    write_in_place(step[1], step[2])
                elif os.path.lexists(step[2]):
                    raise FileExistsError(errno.EEXIST, os.strerror(errno.EEXIST), str(step[2]))
                else:
                    os.rename(step[1], step[2])
            except OSError as exc:
                failed.append(f'{step[1]}: {exc.strerror or exc}')
        self.undo = []
        return failed


def verify(plan: dict, config, reader) -> list[str]:
    """For every checkout, what differs from before the migration (empty when equivalent)."""
    problems = []
    for path in plan['paths']:
        try:
            after = config.load(path)
        except config.InvalidConfig as exc:
            problems.append(f'{path}: {exc}')
            continue
        names = [] if after['WORKSPACE_ROOT'] == str(plan['directory']) else ['WORKSPACE_ROOT']
        if path in plan['before']:
            before = plan['before'][path]
            names += [key for key in dict.fromkeys([*before, *after])
                      if key not in WORKSPACE_ONLY and before.get(key) != after.get(key)]
            try:
                addons, data = effective(reader, after)
            except reader.ConfError as exc:
                problems.append(f'{path}: {exc}')
                continue
            if addons != plan['effective'][path][0]:
                names.append('addons_path')
            if data != plan['effective'][path][1]:
                names.append('data_dir')
        if names:
            problems.append(f'{path}: {", ".join(names)}')
    lock, entries = plan['lock']
    if entries is not None and not lock_verifies(entries, lock.parent):
        problems.append(f'{lock}: entries')
    return problems


SIGNALS = (signal.SIGTERM, signal.SIGHUP)


def apply_plan(plan: dict, config, reader) -> int:
    """Apply every action, verify, and undo everything on an error, a mismatch or a signal.

    SIGTERM and SIGHUP are recorded, not raised: the current action always finishes (so its undo
    step is registered), the run stops before the next one and rolls back. Both signals are
    ignored while rolling back, so a repeated signal cannot leave a half-migrated project.
    """
    changes = Changes()
    pending = []
    previous = {signum: signal.signal(signum, lambda signum, _frame: pending.append(signum))
                for signum in SIGNALS}

    def rollback():
        for signum in SIGNALS:
            signal.signal(signum, signal.SIG_IGN)
        try:
            return changes.rollback()
        finally:
            for signum, handler in previous.items():
                signal.signal(signum, handler)

    try:
        for action in plan['actions']:
            if pending:
                break
            changes.apply(action)
        problems = [] if pending else verify(plan, config, reader)
    except OSError as exc:
        return undone(f'Could not migrate: {exc.strerror or exc}', [], rollback())
    except BaseException:
        rollback()
        raise
    if pending:
        undone(f'Interrupted by signal {pending[0]}', [], rollback())
        return 128 + pending[0]
    if problems:
        return undone('Verification failed', problems, rollback())
    for signum, handler in previous.items():
        signal.signal(signum, handler)
    print(f'verified: {len(plan["paths"])} checkouts load the same configuration from {plan["workspace"]}')
    return 0


def undone(message: str, problems: list[str], failed: list[str]) -> int:
    try:
        report_undone(message, problems, failed)
    except OSError:
        pass  # SIGHUP: the terminal may be gone; the rollback itself already finished.
    return 1


def report_undone(message: str, problems: list[str], failed: list[str]):
    if failed:
        print(f'ERROR: {message}; these changes could not be undone:', file=sys.stderr)
        problems = problems + failed
    else:
        print(f'ERROR: {message}; every change was undone' + (':' if problems else '.'), file=sys.stderr)
    for problem in problems:
        print(f'  {problem}', file=sys.stderr)
    return 1


def main(arguments: list[str]) -> int:
    if arguments in (['--help'], ['-h']):
        print(usage() + '\n' + HELP, end='')
        return 0
    parsed = parse_arguments(arguments)
    if parsed is None:
        print(usage(), file=sys.stderr)
        return 2
    apply, workspace = parsed
    if workspace is not None and (not os.path.isabs(workspace) or not os.path.isdir(workspace)):
        print('ERROR: --workspace requires an absolute existing directory.', file=sys.stderr)
        return 2
    config, reader = sibling('config'), sibling('odoo_addons_path')
    root = config.selected_root()
    if root is None:
        print(f'ERROR: {config.PROJECT_ROOT_REQUIRED}', file=sys.stderr)
        return 2
    try:
        if not (root / PROFILE).is_file():
            try:
                others = [path for path, _kind in checkouts_of(root, config.load(root))
                          if (path / PROFILE).is_file()]
            except (config.InvalidConfig, Refused):
                others = []
            if others:
                raise Refused(f'{root} has no {PROFILE}; run migrate from {others[0]}.')
            print(f'nothing to migrate: {root} has no {PROFILE}')
            return 0
        plan = make_plan(root, workspace, config, reader, time.strftime('%Y%m%dT%H%M%SZ', time.gmtime()))
    except Refused as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 2
    print('\n'.join(plan['lines']), flush=True)
    if not apply:
        print('dry run: nothing changed; run with --apply to migrate')
        return 0
    return apply_plan(plan, config, reader)


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
