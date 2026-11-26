#!/usr/bin/env python3
"""Create a linked git worktree next to the main checkout, or at --path, for the same workspace file.

Tier B in the agent policy (tools/policy.py): an agent proposes it and a person confirms it; its
--dry-run is Tier A. The new worktree reads the
workspace file the main checkout reads (above it, or through git: tools/config.py
workspace_file), so only `git worktree add` runs: nothing is copied or linked. Nothing is deleted.
"""
import importlib.util
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys

USAGE = 'Usage: worktree-init <feature> <branch> [--path <dir>] [--dry-run] [--resume] [--confirm <worktree path>]'
HELP = f"""{USAGE}

Create a linked git worktree named <main folder>-<feature> next to the main checkout and
prepare it for oasis. <feature> becomes the checkout slug (lowercase, other characters -> _).
<branch> is checked out when it exists locally, tracked when only origin/<branch> exists, and
otherwise created from the main checkout's HEAD.

--path <dir> creates it at that absolute path instead; the folder name must still give the
slug (<feature>, or <main folder>-<feature>). It may not be inside the Odoo source or another
checkout, nor an existing directory that is not empty.

The new worktree reads the oasis-workspace.toml the main checkout reads: one above the new
folder, else the main checkout's through git. Only `git worktree add` runs: nothing is copied
or linked. A folder below another workspace file is refused, and so is a workspace file the
main checkout tracks in git: each worktree would read its own committed copy. Untrack it or
keep the workspace file above the checkouts.

--dry-run prints the same plan and changes nothing. --resume accepts an existing folder that
is a worktree of this repository on <branch>.

Adding a worktree (and a new branch) is Tier B in the agent policy (`oasis policy --json`): it
runs only with --confirm <worktree path>, the path the plan names after `worktree:`. Without it,
or with another path, it refuses (exit 2) naming the exact command; nothing changes. --dry-run
and resuming an existing worktree need no confirmation.
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
    """(feature, branch, dry_run, resume, path, confirm, kept) with path and confirm None without
    --path or --confirm, or None on a usage error. --path and --confirm take the next argument, or
    their value after `=`, once. kept: the arguments without --confirm and its value."""
    flags = ('--dry-run', '--resume')
    rest = []
    values = {'--path': None, '--confirm': None}
    seen = {'--path': 0, '--confirm': 0}
    kept = []
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        option = next((name for name in values if argument == name or argument.startswith(name + '=')), None)
        if option is not None:
            seen[option] += 1
            if argument == option:
                index += 1
                if index >= len(arguments):
                    return None
                value = arguments[index]
            else:
                value = argument[len(option) + 1:]
            if not value or value.startswith('-'):
                return None
            values[option] = value
            if option == '--path':
                kept += arguments[index - (argument == option):index + 1]
        else:
            rest.append(argument)
            kept.append(argument)
        index += 1
    positional = [argument for argument in rest if argument not in flags]
    if (len(positional) != 2 or max(seen.values()) > 1 or any(rest.count(flag) > 1 for flag in flags)
            or any(argument.startswith('-') for argument in positional)):
        return None
    return (positional[0], positional[1], '--dry-run' in rest, '--resume' in rest, values['--path'],
            values['--confirm'], kept)


def resolve_commit(main, ref):
    result = git(main, 'rev-parse', '--verify', '--quiet', ref + '^{commit}')
    return result.stdout.strip() if result.returncode == 0 else ''


def checked_out_in(main, branch):
    """(path, prunable) of the worktree entry that has the branch checked out, or ('', False).
    prunable: git reports the entry as prunable (its folder is gone; `git worktree prune` drops it)."""
    result = git(main, 'worktree', 'list', '--porcelain')
    for block in result.stdout.split('\n\n'):
        lines = block.splitlines()
        if lines and lines[0].startswith('worktree ') and f'branch refs/heads/{branch}' in lines:
            return lines[0][len('worktree '):], any(line.startswith('prunable') for line in lines)
    return '', False


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


def tracked(main, path):
    """Whether git tracks path in the main checkout (a path outside it is never tracked there).
    A git failure here is a refusal: the check decides whether worktrees share the file."""
    if not path.is_relative_to(main):
        return False
    relative = path.relative_to(main).as_posix()
    result = git(main, 'ls-files', '-z', '--', relative)
    if result.returncode != 0:
        message = result.stderr.strip().splitlines()
        raise Refused(f'Cannot ask git whether {path} is tracked: '
                      + (message[-1] if message else f'exit {result.returncode}') + '.')
    return relative in result.stdout.split('\0')


def workspace_dir(config, main, new):
    """The directory of the workspace file the main checkout reads, which new will read too.

    The new worktree needs nothing but `git worktree add`, provided it reads the same workspace
    file: the nearest one at or above new must be that file, or there must be none (the new
    linked worktree then reads it through git, config.workspace_file). The main checkout must not
    track it in git: the new worktree would check out its own copy and read that one. It must be
    trusted and readable TOML (config.InvalidConfig otherwise, as every command reports it).
    """
    try:
        workspace = config.find_workspace(main)
    except OSError as exc:
        raise Refused(f'Cannot search {main} and above for {config.WORKSPACE_NAME}: '
                      f'{exc.strerror or exc}.') from exc
    if workspace is None:
        raise Refused(f'The main checkout {main} has no {config.WORKSPACE_NAME} at or above it; '
                      'prepare the worktree by hand.')
    if tracked(main, workspace):
        raise Refused(f'{workspace} is tracked by git in the main checkout {main}: each worktree would '
                      'read its own committed copy, not this file. Untrack it (git rm --cached '
                      f'{workspace.relative_to(main).as_posix()}) or keep the workspace file above the checkouts.')
    try:
        nearest = config.find_workspace(new)
    except OSError as exc:
        raise Refused(f'Cannot search {new} and above for {config.WORKSPACE_NAME}: '
                      f'{exc.strerror or exc}.') from exc
    if nearest is not None and nearest != workspace:
        raise Refused(f"The new worktree {new} would read {nearest}, not the main checkout's {workspace}; "
                      'choose another --path.')
    config.read_toml(config.trusted(workspace))
    return workspace.parent


def chosen_path(value):
    """The --path folder: absolute, normalized, its parent resolved (the folder itself is not, so a
    link there stays a link); None when value is relative."""
    if not os.path.isabs(value):
        return None
    folder = Path(os.path.normpath(value))
    return folder.parent.resolve() / folder.name


def path_refusal(config, values, new):
    """Why the --path folder new cannot hold the worktree, or ''."""
    for key in ('ODOO_SOURCE', 'ENTERPRISE_SOURCE'):
        source = values.get(key)
        if source and new.is_relative_to(source):
            return f'The new worktree {new} would be inside the Odoo source {source}.'
    entry = config.dot_git(new.parent)
    if entry is not None:
        return f'The new worktree {new} would be inside the checkout {entry.parent}.'
    return ''


def used_folder(new):
    """Whether new exists and is not an empty directory (a link counts as used)."""
    if not os.path.lexists(new):
        return False
    if new.is_symlink() or not new.is_dir():
        return True
    try:
        return any(new.iterdir())
    except OSError:
        return True


def main():
    arguments = sys.argv[1:]
    if arguments in (['--help'], ['-h']):
        print(HELP, end='')
        return 0
    parsed = parse_arguments(arguments)
    if parsed is None:
        return fail(USAGE)
    feature_input, branch, dry_run, resume, path, confirm, kept = parsed
    config = load_config()
    root = config.selected_root()
    if root is None:
        return fail(config.PROJECT_ROOT_REQUIRED)
    try:
        values = config.load(root)
    except config.InvalidConfig as exc:
        return fail(str(exc))
    except OSError as exc:  # older Pythons: Path.is_file raises on a directory it cannot search
        return fail(f'Cannot read the configuration of {root}: {exc.strerror or exc}.')
    if values['CHECKOUT_KIND'] == 'none' or not values['CHECKOUT_MAIN_ROOT']:
        return fail('worktree-init needs a git checkout.')
    main_root = Path(values['CHECKOUT_MAIN_ROOT'])

    feature = re.sub(r'[^a-z0-9]+', '_', feature_input.lower()).strip('_')
    if not config.SLUG.fullmatch(feature):
        return fail('Invalid feature name: it must give 1-20 characters of a-z, 0-9 and _ '
                    'starting with a letter or digit.')
    if path is None:
        new = main_root.parent / f'{main_root.name}-{feature.replace("_", "-")}'
    else:
        new = chosen_path(path)
        if new is None:
            return fail('--path requires an absolute path.')
    try:
        derived = config.derived_slug(new, main_root)
    except config.InvalidConfig:
        derived = ''
    if derived != feature:
        return fail(f'Folder {new.name} would not give the checkout slug {feature}.')
    if path is not None:
        refusal = path_refusal(config, values, new)
        if refusal:
            return fail(refusal)
    resumed = False
    # An empty directory at --path is not in the way: git worktree add fills it.
    if os.path.lexists(new) and (path is None or resume or used_folder(new)):
        if not resume:
            if path is not None:
                return fail(f'Worktree folder already exists and is not empty: {new}')
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
    holder, prunable = ('', False) if resumed else checked_out_in(main_root, branch)
    if prunable:
        return fail(f'Branch {branch} is held by the prunable worktree entry {holder} (its folder is gone); '
                    f'run git -C {main_root} worktree prune, then run worktree-init again.')
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
    except (Refused, config.InvalidConfig) as exc:
        return fail(str(exc))

    header = [f'worktree: {new}', f'branch: {branch_line}', f'slug: {feature}', f'workspace: {workspace}']
    if dry_run:
        for line in header:
            print(line)
        print('dry run: nothing changed')
        return 0
    # Resuming adds nothing and needs no confirmation, but an explicit value must still name the worktree.
    if (add is not None or confirm is not None) and (confirm is None or chosen_path(confirm) != new):
        # Tier B (tools/policy.py): explicit intent, named exactly; the plan above decides nothing yet.
        command = shlex.join([config.program_name(), '--project', str(root), 'worktree-init', *kept,
                              '--confirm', str(new)])
        if confirm is None:
            return fail(f'worktree-init adds the git worktree {new} and its branch {branch} (Tier B: it needs '
                        f'explicit confirmation); nothing changed. Run: {command}')
        return fail(f'--confirm {confirm} does not name the worktree {new}; nothing changed. Run: {command}')

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
