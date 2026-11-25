# Setting up a checkout with oasis setup

`oasis setup` configures a checkout for oasis in one command: clone the repository, read the plan,
apply it, then run `doctor`. It infers what it can, asks only what it cannot, keeps everything that
already exists and creates only the missing pieces. The whole flow, from a clone to a development
database, where each value lives and what setup does for you by hand are in
[Setting up a new workspace](new-workspace.md).

```bash
cd /absolute/checkout
~/.agents/skills/odoo19/oasis setup            # the plan; nothing changes
~/.agents/skills/odoo19/oasis setup --apply    # creates the missing pieces
~/.agents/skills/odoo19/oasis doctor
```

```text
oasis [--project <checkout>] setup [--series <x.y>] [--community <dir>] [--enterprise <dir> | --no-enterprise]
                                   [--workspace <dir>] [--name <name>] [--exception <module>]...
                                   [--config-dir <dir>] [--apply | --plan]
```

- [Plan and apply](#plan-and-apply): what is printed, what changes, exit status.
- [What it infers and what it asks](#what-it-infers-and-what-it-asks): the checkout, the series, the source.
- [What it creates and what it keeps](#what-it-creates-and-what-it-keeps): every file and directory.
- [Another Odoo series](#another-odoo-series): a checkout of a series the workspace file has no section for.
- [Next steps](#next-steps): what is left for you.
- [oasis setup and /oasis setup](#oasis-setup-and-oasis-setup): two different commands.

## Plan and apply

- Without `--apply` it prints the plan and changes nothing; the plan ends with
  `dry run: nothing changed; run with --apply to set up`. `--plan` asks for the plan explicitly and
  can never apply: with `--apply` it is a usage error (exit 2), like `--enterprise` with
  `--no-enterprise`. Options are never abbreviated.
- The plan names the checkout, the series, the source and the workspace with where each came from
  (`from the module manifests`, `from the machine file`, `from --community`, `answered`), then one
  line per piece: `create <path>` for a missing one, `kept <path>` for an existing one. The new
  workspace file and the machine file entry are shown in full, indented; the other files by a
  summary line. The environment file is never read and its values are never printed.
- With `--apply` it prints the same plan, creates the files (each one exclusively, so an existing
  file is never replaced), checks that the checkout loads its configuration
  (`verified: <checkout> loads its configuration from <workspace file>`), compiles the locks, creates
  the environment and prints the [next steps](#next-steps). When the configuration does not load,
  every file it wrote is removed again and it exits 1 with `ERROR: Verification failed (...); every
  change was undone.`
- A failed `uv pip compile`, `uv venv` or `uv pip sync` stops with exit 2 and keeps the files
  already written. After a failed compile or `uv venv`, fix the cause and run `oasis setup --apply`
  again, which keeps them and continues. After a failed `uv pip sync` the environment exists, and a
  second setup run would keep it without syncing it, so the error names the command that completes
  it: `ERROR: uv pip sync failed (exit <n>); the files above and the environment <environment> are
  kept: fix it, then run oasis --project <checkout> bootstrap --apply to sync it.`
- When nothing is missing it prints the `kept` lines and `nothing to set up: run oasis --project
  <checkout> doctor` (exit 0). Refusals exit 2 with `ERROR: <reason>` and change nothing.
- Agents may run the plan; the Gentle Shell [bash guard](bash-guard.md) blocks `setup --apply` (and
  any `setup` whose arguments it cannot read literally) the way it blocks `migrate --apply`.

## What it infers and what it asks

- The checkout: `--project`, else the git top level of the current directory (the current
  directory outside git). A linked worktree without a workspace file is refused
  (`<worktree> is a linked worktree of <main>: run oasis setup in the main checkout.`): set up the
  main checkout, and its worktrees then find the workspace file through git.
- The series: `--series`, else the version prefix of the module manifests directly in the checkout
  or one directory below it (`19.0.1.0.0` gives `19.0`), else the single series of the machine
  file, else a question. Manifests of several series, or of one oasis does not support, are refused.
  Versions are read as the series guard reads them: only `<series>.x.y.z` of a supported series or one
  that looks like an Odoo release (`<major>.0`, major 8 to 99) counts, so `1.0` or `1.2.3.4.5` says
  nothing. A configuration whose modules declare another series than its own, an existing one or one
  `--series` asks for, is refused before anything is written (a new one before any question; see
  [Workspace file](workspace-file.md#discovery-precedence-and-versions)).
- The Odoo source: the machine file's entry for the series, else `--community <dir>` (an absolute
  directory whose `odoo/release.py` declares the series) and `--enterprise <dir>` or
  `--no-enterprise`, else a question. A source found near the checkout is only offered
  (`[Enter: <path>]` on a terminal, `found <path>, a suggestion only` otherwise), never chosen.
- The project name, which gives the database prefixes `<name>_dev_` and `<name>_test_` and the compose
  project: the checkout's directory name, lower-cased, or `--name` (2 to 20 lowercase letters,
  digits or underscores, starting with a letter).
- Questions are asked only when standard input and standard error are a terminal. Otherwise a
  missing answer is an error that names its flag, for example
  `No Odoo Community source for 19.0 in the machine file <file>: pass --community <dir>.` or
  `Enterprise or not for 19.0: pass --enterprise <dir> or --no-enterprise.`

## What it creates and what it keeps

| Piece | When it is missing, setup creates |
| --- | --- |
| [Machine file](workspace-file.md#machine-file) entry `[series."<x.y>"]` | `community` and, with Enterprise, `enterprise`. A new file is created with mode 0600; an existing file without the entry gets it appended. An existing entry is used and never edited: a flag that disagrees with it, or an entry without `community`, is refused. |
| `oasis-workspace.toml` | `workspace_version`, `odoo_version`, and `[tooling]` with the environment, `config`, `env_file`, `compose`, `requirements`, `addons_paths` (the directories that hold the modules, `'.'` by default), `db_service = 'db'`, the prefixes, `logs` and `data_dir`; never a source key. Mode 0600. |
| `odoo.conf` | Path-free (no `addons_path`, no `data_dir`; see [Path-free odoo.conf](path-free-odoo-conf.md)): `db_host = 127.0.0.1`, the `db_port` of the compose file, `db_user` and `db_password` empty. Mode 0600. |
| Compose file | `name: oasis-<name>-<6 hex of the workspace directory>` and the PostgreSQL service (`postgres:<postgres_default>` of the series in `tools/odoo_versions.py`: `postgres:17` on 19.0) with the variables oasis uses, published on `127.0.0.1` on the [port](#one-port-for-odooconf-and-the-compose-file) `odoo.conf` connects to. |
| Environment file | `ODOO_DB_USER=` and `ODOO_DB_PASSWORD=`, names only, empty values; mode 0600. Never read or printed. |
| `runtime.in`, `dev.in` | `-r <community>/requirements.txt`; `-c runtime.txt` and `-r runtime.in`, to which you add your development tools. |
| Locks | `runtime.txt`, `dev.txt` and `lock.sha256`, compiled with the series' Python by the same code as `bootstrap --apply` when they are missing or stale; current locks are kept, and a lock changed by hand is kept and leaves the environment uncreated. |
| Environment | `uv venv --python <python>` and `uv pip sync` of `dev.txt`. An existing environment is kept and not synced (run `bootstrap --apply` for that). |
| `logs`, `data_dir` | The directories (mode 0700). |

### One port for odoo.conf and the compose file

`odoo.conf`'s `db_port` and the port the compose file publishes to PostgreSQL's 5432 must be the same:

- Both missing: the first free port from 5432 on `127.0.0.1`.
- Only `odoo.conf` exists: the new compose file publishes its `db_port` (5432, PostgreSQL's default, when it
  has none).
- Only the compose file exists: the new `odoo.conf` gets the port it publishes to 5432, read from a
  short-syntax entry such as `- '127.0.0.1:6001:5432'`, `- "6001:5432"` or `- 6001:5432/tcp` (no YAML
  parser: the long syntax, ranges and variables are not read). When no single such port is found, it gets
  a free port and the plan says `check <odoo.conf>: no port published to 5432 found in <compose file>; set
  db_port <port> to the port it publishes`.
- Both exist: both are kept; when they disagree the plan says `mismatch: <odoo.conf> connects to port <a>
  but <compose file> publishes <b>: make them the same`.

### Where the files go

- Without a workspace file, the workspace is the checkout itself: `oasis-workspace.toml` at its root
  and `config/`, `data/`, `logs/` and the environment `venv/` under `<checkout>/.oasis/`. Both are
  added to the clone's `.git/info/exclude` (never to the tracked `.gitignore`), unless git already
  ignores them, so no directory layout is imposed and nothing new shows in `git status`. The
  environment goes to `<environments>/<name>` instead when the machine file's entry sets
  `environments`.
- `--workspace <dir>` puts the workspace file in `<dir>` instead, an absolute existing directory at
  or above the checkout (`Refusing --workspace <dir>: it is not at or above the checkout <checkout>.`),
  with `config/`, `data/`, `logs/` and `venv/` directly under it, as in the
  [example tree](new-workspace.md#the-example-tree), one possible layout. The directory must be yours and not writable by
  group or others ([Trust](workspace-file.md#trust)).
- With a workspace file at or above the checkout (or found through git), that file is adopted: its
  paths decide where everything goes and only the missing pieces are created. The options that
  answer a new configuration (`--series`, `--name`, `--workspace`, and the source options when the
  configuration already has a source) are then refused (`<option>: <checkout> is already configured
  by <file>; setup only fills what is missing.`). A workspace file without a source gets the machine
  file entry. A checkout that still has the legacy profile is refused before setup runs: run
  [migrate](migrating.md) first. A checkout of another series than the file configures gets a
  section instead ([Another Odoo series](#another-odoo-series)). `--exception` and `--config-dir` apply
  only then; without a workspace file they are refused (`<option>: <checkout> has no workspace file; it
  only applies when setup adds a [series."<x.y>"] section to one.`).

## Another Odoo series

One workspace file can hold [several Odoo series](workspace-file.md#several-series-workspace_version-2).
Run `setup` in a checkout of a series the file has no section for, and the plan adds that section and
that series' files, next to the other series and without touching them:

- The checkout's series: `odoo_version` in its `oasis-checkout.toml`, else the series its module
  manifests declare, the modules of `--exception <module>` (repeatable) and of every section's
  `series_exceptions` left out. Manifests of several supported series are refused as before. A module
  of another series that is not an exception is refused before any question: `The module <module>
  declares Odoo 16.0 (version 16.0.2.0.2 in <manifest>), but <checkout> is an Odoo 15.0 checkout: pass
  --exception <module> to list it in series_exceptions under [series."15.0"], or set its version to
  15.0.x.y.z if it is an Odoo 15.0 module.`
- The machine file entry of the series, when it is missing, exactly as for a new checkout (`--community`,
  `--enterprise` or `--no-enterprise`, else a question). `--series`, `--name` and `--workspace` are refused.
- The workspace file: `add [series."<x.y>"] to <file>:` shows the section, appended after a one-line
  comment; nothing else in the file changes. A `workspace_version = 1` file becomes version 2 by that line
  only (`change workspace_version = 1 to workspace_version = 2 in <file> (that line only)`). The result
  is checked before anything is written: it must parse to the same document plus the section, pass the
  workspace checks, and give every series it configured the same configuration. Otherwise it is
  refused (exit 2), for example `Cannot add [series."15.0"] to <file>: the change would alter the
  configuration of Odoo 19.0 ({series} or a [series] table that version 1 does not read); edit the file
  yourself.`, or, when the version line is not a plain `workspace_version = 1`, `Cannot convert <file> to
  workspace_version 2: no single line workspace_version = 1; set workspace_version = 2 yourself, then
  run oasis setup again.`
- The section sets only what `[tooling]` would otherwise share with the default series (a path that
  already uses `{series}` is left to `[tooling]`): `config`, `env_file`, `compose` and `requirements` in
  `<folder of [tooling].config>/<x.y>/` (`config/15.0/`), the environment next to `[tooling]`'s
  (`environments/acme` gives `environments/acme-15.0`; with the machine file's `environments` for the
  series, `<environments>/<name><major>`), `logs` and `data_dir` in `<logs>/<x.y>` and `<data_dir>/<x.y>`,
  the prefixes `<name><major>_dev_` and `<name><major>_test_` (`cc_dev_` gives `cc15_dev_`), the source
  when `[tooling]` sets one, and `series_exceptions` from `--exception`.
- Adopted files: a folder next to the default one named for the series (`<x.y>`, `odoo-<major>`,
  `odoo<major>`, `odoo-<x.y>`, `odoo<x.y>` or `<major>`) that holds an `odoo.conf` or a compose file
  (`compose.yml`, `compose.yaml`, `docker-compose.yml`, `docker-compose.yaml`), or the folder
  `--config-dir <dir>` names (an absolute existing directory), is adopted: `adopt <folder> (found):
  odoo.conf, compose.yml, .env, requirements/`. The section points to its files, setup keeps them and
  creates only the missing ones there. Two such folders are refused (`Several folders hold Odoo 15.0
  files: <folder>, <folder>; pass --config-dir <dir>.`).
- The missing files as for any checkout ([What it creates](#what-it-creates-and-what-it-keeps)), with
  the series' values: the compose file with its `postgres_default` (`postgres:14` on 15.0) on a free port
  that no other series of the workspace uses, its own compose project (`oasis-<name><major>-...`), the
  requirement inputs of its source, and the locks and environment with its `python_default` (3.10 on
  15.0).

After `--apply` the next run in that checkout finds the section and only prints `kept` lines; the
checkouts of the other series read the file as before. Agents may run the plan; `setup --apply` stays
the user's.

For example, corpus-cafe has a 19.0 workspace file and a 15.0 worktree, `codigo/facturacion`, whose
`report_xlsx` declares `16.0.2.0.2`; an earlier setup left the 15.0 files in `config/odoo-15/`
(`odoo.conf` with `db_port = 5415` and `dbfilter = ^cc15_`, `compose.yml` with `postgres:14-alpine` on
5415, `.env`):

```toml
# corpus-cafe/oasis-workspace.toml before, example only.
workspace_version = 1
odoo_version = '19.0'

[tooling]
environment = 'environments/corpus-cafe'
config = 'config/odoo.conf'
env_file = 'config/.env'
compose = 'config/compose.yml'
requirements = 'config/requirements'
addons_paths = ['.']
db_service = 'db'
dev_prefix = 'cc_dev_'
test_prefix = 'cc_test_'
logs = 'logs'
data_dir = 'data'
```

```bash
cd corpus-cafe/codigo/facturacion
~/.agents/skills/odoo19/oasis setup --exception report_xlsx            # the plan
~/.agents/skills/odoo19/oasis setup --exception report_xlsx --apply
```

```text
series: 15.0 (from the module manifests; <corpus-cafe>/oasis-workspace.toml has no [series."15.0"] section)
...
change workspace_version = 1 to workspace_version = 2 in <corpus-cafe>/oasis-workspace.toml (that line only)
add [series."15.0"] to <corpus-cafe>/oasis-workspace.toml:
  # Added by oasis setup: what differs for the Odoo 15.0 checkouts (docs/setup.md#another-odoo-series).
  [series."15.0"]
  environment = 'environments/corpus-cafe-15.0'
  config = 'config/odoo-15/odoo.conf'
  env_file = 'config/odoo-15/.env'
  compose = 'config/odoo-15/compose.yml'
  requirements = 'config/odoo-15/requirements'
  dev_prefix = 'cc15_dev_'
  test_prefix = 'cc15_test_'
  logs = 'logs/15.0'
  data_dir = 'data/15.0'
  series_exceptions = ['report_xlsx']
adopt <corpus-cafe>/config/odoo-15 (found): odoo.conf, compose.yml, .env
kept <corpus-cafe>/config/odoo-15/odoo.conf
kept <corpus-cafe>/config/odoo-15/compose.yml
kept <corpus-cafe>/config/odoo-15/.env
create <corpus-cafe>/config/odoo-15/requirements/runtime.in: -r <15.0 source>/requirements.txt
...
create the environment <corpus-cafe>/environments/corpus-cafe-15.0 with Python 3.10 (uv venv) and sync dev.txt (uv pip sync)
```

The 19.0 checkouts keep `config/odoo.conf`, `cc_dev_` and their environment; `doctor` in either shows
`PASS series_isolation=19.0,15.0` once the two compose files publish different ports.

## Next steps

After `--apply`, setup prints what is left, numbered, for example:

```text
next steps:
  1. fill in ODOO_DB_USER and ODOO_DB_PASSWORD in <env file>, and the same values as db_user and db_password in <odoo.conf>
  2. docker compose --env-file <env file> -f <compose file> up -d --wait
  3. oasis --project <checkout> doctor
  4. add a [development] table with administrator_login to <workspace file> (docs/dev-database.md)
  5. oasis --project <checkout> init-dev-database <module> <name>_dev_manual
```

The first step appears only for the files setup created, and `bootstrap --apply` is added when it
compiled the locks of an environment it kept. Choose your own local database account; setup never
generates or prints one. Then follow [Development database](dev-database.md) and
[Tests and test databases](testing.md).

## oasis setup and /oasis setup

They are different commands. `oasis setup` (this page) is the command-line tool that configures a
checkout. `/oasis setup` in Gentle Shell installs the subagent overlay (see
[Subagents](subagents.md)) and writes nothing in the project.
