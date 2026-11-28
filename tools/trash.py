#!/usr/bin/env python3
"""The database trash (internal CLI behind tools/drop-database, tools/trash and tools/gc --trash).

Usage:
  trash.py name <dev_prefix> <test_prefix> <slug> <database>
      prints the trash name of database for a drop now
  trash.py filestore <odoo.conf> <from> <to>
      prints the filestore directory that moves with the database (or `none`); exit 2 when it
      cannot move: not a directory, the target path exists, or the conf cannot be read
  trash.py move-filestore <odoo.conf> <from> <to>
      the same checks, then renames <data_dir>/filestore/<from> to <data_dir>/filestore/<to>
  trash.py size <bytes>
      a size for people (7.6MB), `unknown` when the value is not a number
  trash.py list <project_root> <dev_prefix> <test_prefix> <slug>
  trash.py expired <project_root> <dev_prefix> <test_prefix> <slug> <days>
      read `<name>\\t<bytes>\\t<comment>` rows (common.sh list_trash_databases) on stdin; list
      prints this checkout's trash, expired the names dropped at least <days> days ago (0 to
      MAX_DAYS; tools/gc refuses other values before any query)
  trash.py original <project_root> <dev_prefix> <test_prefix> <slug> <trash name> <comment>
      prints the name the trash database had; exit 2 when it is not this checkout's trash
  trash.py purge <odoo.conf> <trash name>
      drops a trash database (common.sh drop_trash_database) and removes its filestore; exit 1
      when the database is not dropped, 3 when it is dropped but its filestore is left (its path
      on stderr, to remove by hand)

Trash name: `<original>_trash_<YYYYMMDD>_<HHMMSS>` (the drop time in UTC). When that exceeds 63
bytes, the original part becomes its first 34 bytes, `_` and 6 hex of the SHA-256 of the
original name, so the name is exactly 63 bytes; the namespace (prefix and `<slug>_`) stays
whole, so every guard of common.sh still applies. The suffix is reserved: normal commands
refuse such names (require_managed_database_name).

The database keeps the comment `oasis-trash original=<original>` while it is in the trash (set
in the same statement list as the rename). An entry is this checkout's trash when its name has
the suffix, lies in this checkout's namespace (not in the namespace of another existing
checkout, as gc decides), and its comment names an original of the same namespace whose trash
name for that drop time is exactly this name. Other names are never listed, restored or purged.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import os
from pathlib import Path
import re
import stat
import sys

import config
import odoo_addons_path
import siblings
import test_temp


gc = siblings.load('gc', 'oasis_trash_gc')  # `gc` is also the name of a built-in module

MAX_BYTES = 63
KEEP_BYTES = 34  # 34 + len('_<6 hex>') + len('_trash_YYYYMMDD_HHMMSS') == 63
STAMP = '%Y%m%d_%H%M%S'
TRASH = re.compile(r'[A-Za-z0-9_]+_trash_(\d{8}_\d{6})')
DATABASE = re.compile(r'[A-Za-z0-9_]+')
COMMENT = 'oasis-trash original='
MAX_DAYS = 36500  # gc --older-than: 100 years; larger values would overflow the date arithmetic
USAGE = ('Usage: trash.py name <dev> <test> <slug> <database> | filestore|move-filestore <odoo.conf> <from> <to> | '
         'size <bytes> | list <root> <dev> <test> <slug> | expired <root> <dev> <test> <slug> <days> | '
         'original <root> <dev> <test> <slug> <name> <comment> | purge <odoo.conf> <name>')


class Refused(Exception):
    """A step that must not run; the message says why."""


def trash_name(original, when):
    """The trash name of original dropped at when (an aware datetime)."""
    suffix = '_trash_' + when.astimezone(timezone.utc).strftime(STAMP)
    name = original + suffix
    if len(name.encode()) <= MAX_BYTES:
        return name
    digest = hashlib.sha256(original.encode()).hexdigest()[:6]
    return f'{original.encode()[:KEEP_BYTES].decode("utf-8", "ignore")}_{digest}{suffix}'


def namespace(name, dev, test, slug):
    """The namespace (prefix and slug_) name belongs to, or None outside both prefixes."""
    for prefix in (dev, test):
        if name.startswith(prefix):
            return prefix + (f'{slug}_' if slug else '')
    return None


def new_name(dev, test, slug, database, now=None):
    """The trash name for a drop now; Refused when the namespace would not stay whole."""
    name = trash_name(database, now or datetime.now(timezone.utc))
    space = namespace(database, dev, test, slug) or ''
    if name != f'{database}_trash_{name[-15:]}' and len(space.encode()) >= KEEP_BYTES:
        raise Refused(f'Database prefix and checkout slug leave no room for a trash name: {space}')
    return name


def dropped_at(name):
    found = TRASH.fullmatch(name)
    if not found:
        return None
    try:
        return datetime.strptime(found.group(1), STAMP).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def owned(name, dev, test, slug, slugs):
    """Whether name lies in this checkout's namespace and not in another existing checkout's."""
    for prefix in (dev, test):
        space = prefix + (f'{slug}_' if slug else '')
        if name.startswith(space) and len(name) > len(space):
            return not any(name.startswith(other) for other in gc.foreign_namespaces(slugs, prefix, slug))
    return False


def original_of(name, comment, dev, test, slug, slugs):
    """The original name of this checkout's trash entry name, or None (see the module docstring)."""
    when = dropped_at(name)
    if when is None or not comment.startswith(COMMENT):
        return None
    original = comment[len(COMMENT):]
    if (not DATABASE.fullmatch(original) or len(original.encode()) > MAX_BYTES or dropped_at(original)
            or not owned(name, dev, test, slug, slugs) or not owned(original, dev, test, slug, slugs)
            or trash_name(original, when) != name):
        return None
    return original


def entries(rows, dev, test, slug, slugs):
    """(name, original, dropped_at, bytes or None) of this checkout's trash, in input order."""
    for row in rows:
        parts = row.rstrip('\n').split('\t')
        if len(parts) != 3:
            continue
        name, size, comment = parts
        original = original_of(name, comment, dev, test, slug, slugs)
        if original:
            yield name, original, dropped_at(name), int(size) if size.isdigit() else None


def human_size(value):
    if value is None:
        return 'unknown'
    size = float(value)
    for unit in ('B', 'kB', 'MB', 'GB'):
        if size < 1024:
            return f'{size:.0f}{unit}' if unit == 'B' else f'{size:.1f}{unit}'
        size /= 1024
    return f'{size:.1f}TB'


def age(when, now):
    seconds = max(0, int((now - when).total_seconds()))
    return f'{seconds // 86400}d{seconds % 86400 // 3600:02d}h'


def filestores(conf, source, target):
    """(source directory or None, target path) of a filestore move; Refused when it cannot move."""
    try:
        origin = test_temp.filestore_path(conf, source)
        destination = test_temp.filestore_path(conf, target)
    except odoo_addons_path.ConfError as exc:
        raise Refused(f'{exc} Filestore of {source} not moved.') from exc
    if origin is None:
        return None, None
    if os.path.lexists(destination):
        raise Refused(f'Filestore path already exists: {destination}')
    try:
        mode = os.lstat(origin).st_mode
    except FileNotFoundError:
        return None, destination
    except OSError as exc:
        raise Refused(f'Cannot read the filestore of {source}: {origin}') from exc
    if not stat.S_ISDIR(mode):
        raise Refused(f'Filestore of {source} is not a directory; not moved: {origin}')
    return origin, destination


def move_filestore(conf, source, target):
    origin, destination = filestores(conf, source, target)
    if origin is None:
        return 0
    try:
        os.rename(origin, destination)
    except OSError:
        print(f'Cannot move the filestore of {source}: {origin}', file=sys.stderr)
        return 1
    return 0


def purge(conf, name):
    """Drop a trash database, then remove its filestore: 0 when both are gone, 1 when the
    database is not dropped, 3 when it is dropped but its filestore is left (its path on stderr)."""
    if test_temp.database_step('drop_trash_database', name) != 0:
        return 1
    if test_temp.remove_filestore(conf, name):
        return 0
    try:
        path = test_temp.filestore_path(conf, name)
    except odoo_addons_path.ConfError:
        path = None
    print(f'Database {name} was dropped, but its filestore is left: {path or f"<data_dir>/filestore/{name}"}; '
          'remove it by hand.', file=sys.stderr)
    return 3


def main(argv):
    command, args = (argv[0], argv[1:]) if argv else ('', [])
    try:
        if command == 'name' and len(args) == 4:
            print(new_name(*args))
            return 0
        if command == 'filestore' and len(args) == 3:
            origin, _destination = filestores(*args)
            print(origin or 'none')
            return 0
        if command == 'move-filestore' and len(args) == 3:
            return move_filestore(*args)
        if command == 'size' and len(args) == 1:
            print(human_size(int(args[0]) if args[0].isdigit() else None))
            return 0
        if command in ('list', 'expired', 'original') and len(args) == {'list': 4, 'expired': 5, 'original': 6}[command]:
            root, dev, test, slug = args[:4]
            slugs = gc.checkout_slugs(Path(root))
            if command == 'original':
                original = original_of(args[4], args[5], dev, test, slug, slugs)
                if not original:
                    raise Refused(f'Not a trash database of this checkout: {args[4]}')
                print(original)
                return 0
            now = datetime.now(timezone.utc)
            found = list(entries(sys.stdin, dev, test, slug, slugs))
            if command == 'list':
                for name, original, when, size in found:
                    print(f'trash {name} original={original} dropped={when.strftime("%Y-%m-%dT%H:%M:%SZ")} '
                          f'age={age(when, now)} size={human_size(size)}')
                print(f'trashed={len(found)}')
                return 0
            if not (args[4].isascii() and args[4].isdigit()) or int(args[4]) > MAX_DAYS:
                raise Refused(USAGE)
            limit = now - timedelta(days=int(args[4]))
            for name, _original, when, _size in found:
                if when <= limit:
                    print(name)
            return 0
        if command == 'purge' and len(args) == 2:
            return purge(*args)
    except Refused as exc:
        print(exc, file=sys.stderr)
        return 2
    except config.InvalidConfig as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 2
    print(f'ERROR: {USAGE}', file=sys.stderr)
    return 2


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
