#!/usr/bin/env python3
"""Orphaned disposable test databases for `odoo19 gc` (internal CLI behind tools/gc).

Usage:
  gc.py orphans <project_root> <test_prefix> <slug> <checkout|all> [<test_database>]
      reads database names on stdin and prints the orphans among them, in input order
  gc.py discard <odoo.conf> <database>
      drops one orphan and its filestore (tools/test_temp.py) and removes its stale run locks

A disposable run database is `<test_prefix><rest>_r<6 hex>`, optionally with `_update`
(tools/runtime_state.py). It is an orphan when no run lock of any checkout of this user is
live for it (the lock's pid still runs the recorded command line). The configured
test_database and its `_update` sibling are never orphans.

Namespaces (scope `checkout`): a checkout with a slug owns `<test_prefix><slug>_<rest>`; the
main checkout (or a project outside git) owns `<test_prefix><rest>`. Both exclude the names
of every other existing checkout whose namespace is longer and starts with theirs, so the main
checkout skips `<test_prefix><linked slug>_...`. The other checkouts' slugs come from
`git worktree list` (their profile's checkout_slug, or without a profile their
oasis-checkout.toml's, else the slug derived from the folder name, as tools/config.py does). A worktree that no longer exists has no namespace, so the
main checkout takes its leftovers. Scope `all` matches every name with the run suffix.
"""
import os
from pathlib import Path
import subprocess
import sys
import tomllib

import config
import runtime_state
import test_temp

USAGE = ('Usage: gc.py orphans <project_root> <test_prefix> <slug> <checkout|all> [<test_database>] | '
         'discard <odoo.conf> <database>')


def profile_slug(checkout):
    """A checkout's own [tooling].checkout_slug, or None.

    From its profile; a checkout without one (workspace mode) sets it in its
    oasis-checkout.toml, read with tools/config.py's rules. An untrusted or invalid checkout file
    raises: falling back to the folder slug could make this checkout's databases look like
    another checkout's orphans.
    """
    if not (checkout / config.PROFILE_NAME).is_file():
        try:
            value = config.checkout_overrides(checkout).get('checkout_slug')
        except config.InvalidConfig as exc:
            raise config.InvalidConfig(f'Cannot read the checkout slug of {checkout}: {exc}') from exc
        return value if isinstance(value, str) and config.SLUG.fullmatch(value) else None
    try:
        with (checkout / config.PROFILE_NAME).open('rb') as stream:
            tooling = tomllib.load(stream).get('tooling', {})
    except (OSError, tomllib.TOMLDecodeError):
        return None
    value = tooling.get('checkout_slug') if isinstance(tooling, dict) else None
    return value if isinstance(value, str) and config.SLUG.fullmatch(value) else None


def checkout_slugs(root):
    """The slugs of the checkouts of root's repository (read-only `git worktree list`)."""
    env = {key: value for key, value in os.environ.items()
           if key not in ('GIT_DIR', 'GIT_WORK_TREE', 'GIT_COMMON_DIR')}
    try:
        result = subprocess.run(['git', '-C', str(root), 'worktree', 'list', '--porcelain'],
                                capture_output=True, text=True, env=env,
                                timeout=config.GIT_TIMEOUT_SECONDS)
    except (OSError, subprocess.SubprocessError):
        return set()
    if result.returncode != 0:
        return set()
    paths = [Path(line[len('worktree '):]).resolve() for line in result.stdout.splitlines()
             if line.startswith('worktree ')]
    slugs = set()
    for index, path in enumerate(paths):
        slug = profile_slug(path)
        if slug is None and index > 0:
            try:
                slug = config.derived_slug(path, paths[0])
            except config.InvalidConfig:
                slug = None
        if slug:
            slugs.add(slug)
    return slugs


def orphans(names, root, prefix, slug, scope, configured=''):
    live = runtime_state.live_run_databases()
    namespace = prefix + (f'{slug}_' if slug else '')
    excluded = []
    if scope != 'all':
        excluded = [f'{prefix}{other}_' for other in checkout_slugs(root) if other != slug]
        excluded = [other for other in excluded if len(other) > len(namespace) and other.startswith(namespace)]
    owned = prefix if scope == 'all' else namespace
    reserved = {configured, f'{configured}_update'} if configured else set()
    for name in names:
        if (not name.startswith(owned) or not runtime_state.is_run_database(name[len(owned):])
                or name in reserved or any(name.startswith(other) for other in excluded)
                or name in live):
            continue
        yield name


def main(argv):
    try:
        if argv[:1] == ['orphans'] and len(argv) in (5, 6) and argv[4] in ('checkout', 'all'):
            names = [line.strip() for line in sys.stdin if line.strip()]
            for name in orphans(names, Path(argv[1]), argv[2], argv[3], argv[4], *argv[5:]):
                print(name)
            return 0
        if argv[:1] == ['discard'] and len(argv) == 3:
            if not test_temp.discard(argv[1], argv[2]):
                return 1
            runtime_state.discard_stale_run_locks(argv[2])
            return 0
    except (runtime_state.StateError, config.InvalidConfig) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 2
    print(f'ERROR: {USAGE}', file=sys.stderr)
    return 2


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
