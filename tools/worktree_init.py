#!/usr/bin/env python3
"""Create a linked git worktree next to the main checkout and prepare its local files.

User-run only: it links the main checkout's environment file, which agents may not touch.
The content of odoo.conf and of environment files is never printed. Nothing is deleted:
a failure after `git worktree add` keeps what was created and reports it.
"""
import importlib.util
import os
from pathlib import Path
import re
import subprocess
import sys
import tomllib

USAGE = 'Usage: worktree-init <feature> <branch> [--dry-run]'
HELP = f"""{USAGE}

Create a linked git worktree named <main folder>-<feature> next to the main checkout and
prepare it for oasis. <feature> becomes the checkout slug (lowercase, other characters -> _).
<branch> is checked out when it exists locally, tracked when only origin/<branch> exists, and
otherwise created from the main checkout's HEAD.

In the new worktree: an untracked .odoo19-agent.toml is copied; each untracked or ignored
entry of the main checkout's dev/ is linked, except dev/odoo.conf (copied with mode 0600,
the main root in addons_path replaced by the worktree root, db_name removed) and dev/runtime
(a new empty 0700 directory); the profile's env_file is linked to the main checkout's file.
Existing paths are never replaced. --dry-run prints the same plan and changes nothing.
"""
QUERY_TIMEOUT_SECONDS = 30
PROFILE = '.odoo19-agent.toml'
ADDONS_PATH = re.compile(r'^(\s*addons_path\s*[=:])(.*)$', re.IGNORECASE)
DB_NAME = re.compile(r'^\s*db_name\s*[=:]', re.IGNORECASE)


class Refused(Exception):
    """A refusal before any change: exit 2 with the message."""


def fail(message, code=2):
    print('ERROR: ' + message, file=sys.stderr)
    return code


def git_env():
    return {key: value for key, value in os.environ.items()
            if key not in ('GIT_DIR', 'GIT_WORK_TREE', 'GIT_COMMON_DIR', 'GIT_INDEX_FILE', 'GIT_PREFIX')}


def git(cwd, *args, timeout=QUERY_TIMEOUT_SECONDS):
    return subprocess.run(['git', '-C', str(cwd), *args], capture_output=True, text=True,
                          env=git_env(), timeout=timeout)


def load_config():
    # Load the packaged parser by its own path; never import project Python code.
    spec = importlib.util.spec_from_file_location('odoo19_config', Path(__file__).with_name('config.py'))
    config = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(config)
    return config


def parse_arguments(arguments):
    dry_run = arguments.count('--dry-run') == 1
    positional = [argument for argument in arguments if argument != '--dry-run']
    if (len(positional) != 2 or arguments.count('--dry-run') > 1
            or any(argument.startswith('-') for argument in positional)):
        return None
    return positional[0], positional[1], dry_run


def resolve_commit(main, ref):
    result = git(main, 'rev-parse', '--verify', '--quiet', ref + '^{commit}')
    return result.stdout.strip() if result.returncode == 0 else ''


def checked_out_in(main, branch):
    """The worktree path that has the branch checked out, or ''."""
    result = git(main, 'worktree', 'list', '--porcelain')
    path = ''
    for line in result.stdout.splitlines():
        if line.startswith('worktree '):
            path = line[len('worktree '):]
        elif line == f'branch refs/heads/{branch}':
            return path
    return ''


def in_commit(main, commit, relative):
    return git(main, 'cat-file', '-e', f'{commit}:{relative}').returncode == 0


def is_tracked(main, relative):
    return git(main, 'ls-files', '--error-unmatch', '--', relative).returncode == 0


def dev_entries(main):
    """Names of the top-level entries of main/dev that git reports as untracked or ignored."""
    dev = main / 'dev'
    if dev.is_symlink() or not dev.is_dir():
        return []
    reported = set()
    for extra in ((), ('--ignored',)):
        result = git(main, 'ls-files', '-z', '--others', *extra, '--exclude-standard', '--directory',
                     '--', 'dev/')
        if result.returncode != 0:
            raise Refused('Cannot list the untracked files of the main checkout.')
        reported.update(path for path in result.stdout.split('\0') if path)
    names = set()
    for path in reported:
        if not path.startswith('dev/'):
            continue
        rest = path[len('dev/'):].rstrip('/')
        if not rest:
            names.update(os.listdir(dev))  # the whole dev/ is untracked or ignored
        elif '/' not in rest:
            names.add(rest)
    return sorted(names)


def rewrite_conf(text, main, new):
    """odoo.conf lines with main-root addons paths moved to the new root and db_name dropped."""
    lines, rewrote, removed = [], False, False
    for line in text.splitlines(keepends=True):
        body = line.rstrip('\r\n')
        ending = line[len(body):]
        if DB_NAME.match(body):
            removed = True
            continue
        match = ADDONS_PATH.match(body)
        if match:
            pieces = []
            for piece in match.group(2).split(','):
                core = piece.strip()
                # Only whole path components: <main>-other is a different directory.
                if core == main or core.startswith(main + '/'):
                    piece = piece.replace(core, new + core[len(main):], 1)
                    rewrote = True
                pieces.append(piece)
            body = match.group(1) + ','.join(pieces)
        lines.append(body + ending)
    return ''.join(lines), rewrote, removed


def plan_items(main, new, commit, env_relative):
    """Ordered actions: (kind, relative path, payload). Paths existing in the commit are skipped."""
    items, created = [], set()
    profile = main / PROFILE
    if profile.is_file() and not is_tracked(main, PROFILE) and not in_commit(main, commit, PROFILE):
        with profile.open('rb') as stream:
            try:
                tooling = tomllib.load(stream).get('tooling', {})
            except tomllib.TOMLDecodeError as exc:
                raise Refused(f'Invalid tooling configuration: {profile}') from exc
        if isinstance(tooling, dict) and 'checkout_slug' in tooling:
            raise Refused(f'{profile} sets [tooling].checkout_slug, which the new worktree would share '
                          'with this checkout; prepare the worktree by hand.')
        items.append(('copy', PROFILE, None))
    names = dev_entries(main)
    if names and not in_commit(main, commit, 'dev'):
        items.append(('mkdir', 'dev', None))
        created.add('dev')
    for name in names:
        relative = f'dev/{name}'
        if in_commit(main, commit, relative):
            continue
        source = main / relative
        if name == 'odoo.conf' and source.is_file():
            text = source.read_text(encoding='utf-8', errors='surrogateescape')
            items.append(('conf', relative, rewrite_conf(text, str(main), str(new))))
        elif name == 'runtime':
            items.append(('runtime', relative, None))
        else:
            items.append(('link', relative, None))
    if env_relative:
        covered = any(env_relative == relative or env_relative.startswith(relative + '/')
                      for kind, relative, _payload in items if kind != 'mkdir')
        if (not covered and os.path.exists(main / env_relative)
                and not in_commit(main, commit, env_relative)):
            parts = Path(env_relative).parts
            for depth in range(1, len(parts)):
                parent = '/'.join(parts[:depth])
                if parent not in created and not in_commit(main, commit, parent):
                    items.append(('mkdir', parent, None))
                    created.add(parent)
            items.append(('link', env_relative, None))
    return items


def env_path(root):
    """The profile's env_file relative to the checkout, or '' when it lives outside it.

    Read raw from the profile: config.py resolves symlinks, and a linked worktree's env file
    is a link into the main checkout.
    """
    with (root / PROFILE).open('rb') as stream:
        value = tomllib.load(stream)['tooling']['env_file']
    relative = os.path.normpath(value)
    if os.path.isabs(relative) or relative == '.' or relative.split(os.sep)[0] == '..':
        return ''
    return relative


def item_lines(main, kind, relative, payload):
    if kind == 'copy':
        return [f'copied {relative}']
    if kind in ('mkdir', 'runtime'):
        return [f'created dir {relative}']
    if kind == 'link':
        return [f'linked {relative} -> {main / relative}']
    _text, rewrote, removed = payload
    lines = [f'copied {relative}']
    if rewrote:
        lines.append(f'rewrote addons_path in {relative}')
    if removed:
        lines.append(f'removed db_name from {relative}')
    return lines


def apply_item(main, new, kind, relative, payload):
    target = new / relative
    if os.path.lexists(target):
        # Never replace: the plan read the commit, the checkout may differ (hooks, sparse).
        return [f'kept existing {relative}']
    if kind == 'copy':
        data = (main / relative).read_bytes()
        target.write_bytes(data)
    elif kind == 'mkdir':
        target.mkdir()
    elif kind == 'runtime':
        target.mkdir(mode=0o700)
        os.chmod(target, 0o700)
    elif kind == 'link':
        os.symlink(main / relative, target)
    else:
        text = payload[0]
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, 'w', encoding='utf-8', errors='surrogateescape', newline='') as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(text)
    return item_lines(main, kind, relative, payload)


def main():
    arguments = sys.argv[1:]
    if arguments in (['--help'], ['-h']):
        print(HELP, end='')
        return 0
    parsed = parse_arguments(arguments)
    if parsed is None:
        return fail(USAGE)
    feature_input, branch, dry_run = parsed
    selected = os.environ.get('ODOO19_PROJECT_ROOT', '')
    if not selected or not Path(selected).is_absolute() or not Path(selected).is_dir():
        return fail('ODOO19_PROJECT_ROOT must name an absolute existing project directory.')
    config = load_config()
    root = Path(selected).resolve()
    try:
        values = config.load(root)
    except config.InvalidConfig as exc:
        return fail(str(exc))
    if values['CHECKOUT_KIND'] == 'none' or not values['CHECKOUT_MAIN_ROOT']:
        return fail('worktree-init needs a git checkout.')
    main_root = Path(values['CHECKOUT_MAIN_ROOT'])

    feature = re.sub(r'[^a-z0-9]+', '_', feature_input.lower()).strip('_')
    if not config.SLUG.fullmatch(feature):
        return fail('Invalid feature name: it must give 1-20 characters of a-z, 0-9 and _ '
                    'starting with a letter or digit.')
    new = main_root.parent / f'{main_root.name}-{feature.replace("_", "-")}'
    try:
        derived = config.derived_slug(new, main_root)
    except config.InvalidConfig:
        derived = ''
    if derived != feature:
        return fail(f'Folder {new.name} would not give the checkout slug {feature}.')
    if os.path.lexists(new):
        return fail(f'Worktree folder already exists: {new}')

    check = git(main_root, 'check-ref-format', '--branch', branch)
    if check.returncode != 0 or check.stdout.strip() != branch:
        return fail(f'Invalid branch name: {branch}')
    holder = checked_out_in(main_root, branch)
    if holder:
        return fail(f'Branch {branch} is already checked out in {holder}.')
    local = resolve_commit(main_root, f'refs/heads/{branch}')
    remote = '' if local else resolve_commit(main_root, f'refs/remotes/origin/{branch}')
    if local:
        commit = local
        add = ['worktree', 'add', str(new), branch]
        branch_line = f'{branch} (existing)'
    elif remote:
        commit = remote
        add = ['worktree', 'add', '--track', '-b', branch, str(new), f'origin/{branch}']
        branch_line = f'{branch} (tracking origin/{branch})'
    else:
        commit = resolve_commit(main_root, 'HEAD')
        if not commit:
            return fail('The main checkout has no commit to branch from.')
        add = ['worktree', 'add', '-b', branch, str(new), commit]
        branch_line = f'{branch} (created from HEAD {commit[:12]})'

    try:
        env_relative = env_path(root)
        items = plan_items(main_root, new, commit, env_relative)
    except Refused as exc:
        return fail(str(exc))
    except OSError as exc:
        return fail(f'Cannot read the main checkout: {exc.strerror or exc}.')

    header = [f'worktree: {new}', f'branch: {branch_line}', f'slug: {feature}']
    if dry_run:
        for line in header:
            print(line)
        for kind, relative, payload in items:
            for line in item_lines(main_root, kind, relative, payload):
                print(line)
        print('dry run: nothing changed')
        return 0

    added = git(main_root, *add, timeout=None)
    if added.returncode != 0:
        message = added.stderr.strip().splitlines()
        return fail('git worktree add failed: ' + (message[-1] if message else f'exit {added.returncode}'), 1)
    for line in header:
        print(line, flush=True)
    for kind, relative, payload in items:
        try:
            lines = apply_item(main_root, new, kind, relative, payload)
        except OSError as exc:
            return fail(f'Could not create {relative}: {exc.strerror or exc}. '
                        'The worktree and the items listed above were kept.', 1)
        for line in lines:
            print(line, flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
