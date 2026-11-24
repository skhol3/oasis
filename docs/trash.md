# Database trash

`drop-database` does not drop: it moves the database to the trash of its checkout, where it
stays until you restore it or `gc --apply --trash` drops it after the retention time (7 days by
default).

```bash
~/.agents/skills/odoo19/oasis --project /absolute/project drop-database <name> [--terminate]
~/.agents/skills/odoo19/oasis --project /absolute/project trash                        # list, change nothing
~/.agents/skills/odoo19/oasis --project /absolute/project trash restore <trash name>
~/.agents/skills/odoo19/oasis --project /absolute/project gc --trash [--older-than <days>]          # list
~/.agents/skills/odoo19/oasis --project /absolute/project gc --apply --trash [--older-than <days>]  # drop
```

## Moving a database to the trash

`drop-database <name>` takes a managed name of this checkout, as before. A database that does
not exist prints `Database does not exist: <name>` and exits 0, as before. Otherwise it prints
the plan before acting:

```text
database=cc_dev_coffee
size=7.6MB
sessions=0
filestore=/srv/project/data/filestore/cc_dev_coffee
trash=cc_dev_coffee_trash_20261123_142501
```

- `size` is `pg_database_size` (B, kB, MB, GB, TB in steps of 1024; `unknown` when the server
  did not answer a number). `sessions` counts the open sessions of the database.
- `filestore` is `<data_dir>/filestore/<name>` when that directory exists, else `none`.
  `<data_dir>` is `[tooling].data_dir` when it is set, otherwise the `data_dir` of `odoo.conf`;
  without an absolute `data_dir`, Odoo's default data directory is not guessed (`none`), as for
  disposable test databases.
- With open sessions it stops after the plan with today's refusal (`Refusing to drop database
  with <n> active session(s): <name>`, exit 3), unless you pass `--terminate`, which closes them
  first.

Then it renames the filestore directory to `<data_dir>/filestore/<trash name>` and the
database to its trash name. The rename and the database comment `oasis-trash
original=<name>` are one transaction (`ALTER DATABASE ... RENAME TO ...; COMMENT ON DATABASE
...`). When the rename fails, the filestore moves back and the command prints `Cannot move
<name> to the trash; nothing changed.` (exit 1). On success it prints:

```text
Database moved to trash: cc_dev_coffee -> cc_dev_coffee_trash_20261123_142501
Restore it with: oasis trash restore cc_dev_coffee_trash_20261123_142501
```

It refuses before changing anything (exit 2) when the trash name already exists (`Trash name
already exists: <trash name>`), when the filestore entry is not a directory (`Filestore of
<name> is not a directory; not moved: <path>`, a symlink included) or when the filestore path of
the trash name exists (`Filestore path already exists: <path>`).

## Trash names

`<original>_trash_<YYYYMMDD>_<HHMMSS>`, with the drop time in UTC. When that would exceed 63
bytes, the name becomes the first 34 bytes of the original, `_`, the first 6 hex of the
SHA-256 of the original name, then `_trash_<YYYYMMDD>_<HHMMSS>`: exactly 63 bytes.

- The name keeps the namespace (`<dev_prefix>` or `<test_prefix>`, then `<slug>_` in a
  checkout with a slug), so every guard of [Databases per checkout](checkouts-and-worktrees.md#databases-per-checkout)
  still applies. A prefix and slug of 34 bytes or more leave no room for a shortened name: the
  command exits 2 (`Database prefix and checkout slug leave no room for a trash name: <namespace>`).
- The suffix `_trash_` + 8 digits + `_` + 6 digits is reserved. Every command that takes a
  database (`create-database`, `install-module`, `update-module`, `odoo-shell`, `start
  -d`/`--database`, `init-dev-database`, `test-module`, `verify-module`, `module-status` and
  `drop-database` itself) refuses such a name with `Database names ending in
  _trash_<YYYYMMDD>_<HHMMSS> are reserved for the trash: <name>` (exit 2, nothing runs). Only
  `trash restore` and `gc --trash` take them.
- The original name comes from the comment, not from the name, so a shortened name restores to
  its full original. An entry belongs to this checkout's trash when its name has the suffix and
  lies in this checkout's namespace (the main checkout skips the namespaces of its existing
  linked worktrees, as `gc` does), and its comment names an original in the same namespace whose
  trash name for that drop time is exactly this name. Anything else is never listed, restored
  or dropped by the trash commands.

## Listing and restoring

`trash` lists this checkout's trash, one line per entry, then the count; it changes nothing:

```text
trash cc_dev_coffee_trash_20261113_110000 original=cc_dev_coffee dropped=2026-11-13T11:00:00Z age=10d03h size=7.6MB
trashed=1
```

`trash restore <trash name>` renames the filestore and then the database back, and clears the
comment: `Database restored from trash: <trash name> -> <original>`. It refuses, changing
nothing:

- a name without the trash suffix, or not a trash entry of this checkout: `Not a trash database
  of this checkout: <name>` (exit 2); a name outside the checkout's namespace gets the usual
  namespace refusal;
- a missing database: `Database does not exist: <name>` (exit 2);
- an original name that exists: `Refusing to restore <trash name>: database <original> already
  exists.` (exit 2), and an existing filestore path of the original: `Filestore path already
  exists: <path>` (exit 2);
- open sessions on the trash database: `Refusing to restore database with <n> active
  session(s): <name>` (exit 3).

## Emptying the trash

`gc --trash` lists the entries of this checkout's trash dropped at least `--older-than <days>`
days ago (a whole number, default 7; `0` takes every entry), one `expired <name>` line each, then
`expired=<n>`; it changes nothing. With `--apply` it closes their sessions, drops them and removes
their filestores, printing `dropped <name>`; a failed drop prints `failed <name>` on stderr and
keeps that entry's filestore, and the next entry is still dropped. The run ends with
`dropped=<n>` and `failed=<m>` and exits 1 when `m` is not 0. `--older-than` without `--trash`,
and `--trash` with `--all-checkouts`, print the usage (exit 2).

Plain `gc` and `gc --apply` never touch the trash: they handle only orphaned disposable test
databases (see [Disposable test databases](disposable-test-databases.md)).

The [action menu](action-menu.md) has *Move a database to the trash*, *List trash*, *Restore
from trash* and *Empty trash* (`gc --apply --trash`, after you type `yes`).
