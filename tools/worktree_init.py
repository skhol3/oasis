#!/usr/bin/env python3
"""Create a linked git worktree next to the main checkout, below the same workspace file.

User-run only (the Gentle Shell bash guard blocks agents). The new worktree reads the
workspace file the main checkout reads, so only `git worktree add` runs: nothing is copied or
linked. Nothing is deleted.
"""
import importlib.util
import os
from pathlib import Path
import re
import subprocess
import sys

USAGE = 'Usage: worktree-init <feature> <branch> [--dry-run] [--resume]'
HELP = f"""{USAGE}

Create a linked git worktree named <main folder>-<feature> next to the main checkout and
prepare it for oasis. <feature> becomes the checkout slug (lowercase, other characters -> _).
<branch> is checked out when it exists locally, tracked when only origin/<branch> exists, and
otherwise created from the main checkout's HEAD.

The oasis-workspace.toml the main checkout reads must be in a directory above the new folder;
the new worktree then reads it too, so only `git worktree add` runs: nothing is copied or
linked.

--dry-run prints the same plan and changes nothing. --resume accepts an existing folder that
is a worktree of this repository on <branch>.
"""
QUERY_TIMEOUT_SECONDS = 30


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
    spec = importlib.util.spec_from_file_location('oasis_config', Path(__file__).with_name('config.py'))
    config = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(config)
    return config


def parse_arguments(arguments):
    flags = ('--dry-run', '--resume')
    positional = [argument for argument in arguments if argument not in flags]
    if (len(positional) != 2 or any(arguments.count(flag) > 1 for flag in flags)
            or any(argument.startswith('-') for argument in positional)):
        return None
    return positional[0], positional[1], '--dry-run' in arguments, '--resume' in arguments


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


def registered_branch(main, folder):
    """The branch of folder as a worktree of main's repository: None when it is not one,
    '' when it is detached."""
    if folder.is_symlink() or not folder.is_dir():
        return None
    result = git(main, 'worktree', 'list', '--porcelain')
    if result.returncode != 0:
        return None
    for block in result.stdout.split('\n\n'):
        lines = block.splitlines()
        if not lines or not lines[0].startswith('worktree '):
            continue
        if Path(lines[0][len('worktree '):]).resolve() != folder:
            continue
        for line in lines[1:]:
            if line.startswith('branch refs/heads/'):
                return line[len('branch refs/heads/'):]
        return ''
    return None


def workspace_dir(config, main, new):
    """The directory of the workspace file the main checkout reads, which must be above new.

    The new worktree needs nothing but `git worktree add`, provided it finds the same
    workspace file, so that file must be in a directory above the new folder.
    """
    workspace = config.find_workspace(main)
    if workspace is None:
        raise Refused(f'The main checkout {main} has no {config.WORKSPACE_NAME} at or above it; '
                      'prepare the worktree by hand.')
    if not new.is_relative_to(workspace.parent):
        raise Refused(f'The new worktree {new} would not be under the workspace {workspace.parent}; '
                      'prepare the worktree by hand.')
    return workspace.parent


def main():
    arguments = sys.argv[1:]
    if arguments in (['--help'], ['-h']):
        print(HELP, end='')
        return 0
    parsed = parse_arguments(arguments)
    if parsed is None:
        return fail(USAGE)
    feature_input, branch, dry_run, resume = parsed
    config = load_config()
    root = config.selected_root()
    if root is None:
        return fail(config.PROJECT_ROOT_REQUIRED)
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
    resumed = False
    if os.path.lexists(new):
        if not resume:
            return fail(f'Worktree folder already exists: {new}')
        current = registered_branch(main_root, new)
        if current is None:
            return fail(f'{new} is not a worktree of this repository.')
        if current != branch:
            return fail(f'Worktree {new} is not on branch {branch}.')
        resumed = True

    check = git(main_root, 'check-ref-format', '--branch', branch)
    if check.returncode != 0 or check.stdout.strip() != branch:
        return fail(f'Invalid branch name: {branch}')
    holder = '' if resumed else checked_out_in(main_root, branch)
    if holder:
        return fail(f'Branch {branch} is already checked out in {holder}.')
    local = '' if resumed else resolve_commit(main_root, f'refs/heads/{branch}')
    remote = '' if local or resumed else resolve_commit(main_root, f'refs/remotes/origin/{branch}')
    if resumed:
        commit = resolve_commit(new, 'HEAD')
        if not commit:
            return fail(f'Worktree {new} has no commit checked out.')
        add = None
        branch_line = f'{branch} (resumed)'
    elif local:
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
        workspace = workspace_dir(config, main_root, new)
    except Refused as exc:
        return fail(str(exc))

    header = [f'worktree: {new}', f'branch: {branch_line}', f'slug: {feature}', f'workspace: {workspace}']
    if dry_run:
        for line in header:
            print(line)
        print('dry run: nothing changed')
        return 0

    if add is not None:
        added = git(main_root, *add, timeout=None)
        if added.returncode != 0:
            message = added.stderr.strip().splitlines()
            return fail('git worktree add failed: ' + (message[-1] if message else f'exit {added.returncode}'), 1)
    for line in header:
        print(line, flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
