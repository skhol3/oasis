# Workspace file

One `oasis-workspace.toml` configures every checkout of a project: checkouts and linked worktrees at any depth below it read the same file, so a new worktree needs no copy of it, and a linked worktree anywhere else reads the main checkout's file through git (see [Discovery](#discovery-precedence-and-versions)). The Odoo source of each series comes from the [machine file](#machine-file); the workspace file sets it only to override it. Review the [example workspace file](../odoo19-environment/assets/oasis-workspace.example.toml). One file can also hold [several Odoo series](#several-series-workspace_version-2) (`workspace_version = 2`), each checkout working with the series of its modules. [`oasis setup`](setup.md) writes it for a clone; [Setting up a new workspace](new-workspace.md) has the whole flow, where each value lives, an example tree and accepted and refused paths.

## Layout and example

No layout is required: the file may sit in the main checkout or in any directory above the checkouts. Two common ones:

```text
<checkout>/oasis-workspace.toml               what oasis setup writes by default, excluded from git in .git/info/exclude
<checkout>/.oasis/config/                     odoo.conf, environment file, compose file, requirements/
<checkout>/.oasis/data/, .oasis/logs/         data_dir and logs; .oasis/venv/ the environment

<project>/oasis-workspace.toml                above the checkouts (oasis setup --workspace <project>)
<project>/codigo/<main checkout>              checkouts and linked worktrees, at any depth
<project>/codigo/<main checkout>-<feature>
<project>/config/                             odoo.conf, environment file, compose file, requirements/
<project>/data/                               Odoo data directory (data_dir = 'data'; passed as --data-dir)
<project>/logs/                               compact runs and browser evidence (logs = 'logs')
```

```toml
# Example only.
workspace_version = 1
odoo_version = '19.0'

[tooling]
# community = '/other/odoo'   # only to override the machine file's source for this project
environment = 'environments/acme'
config = 'config/odoo.conf'
env_file = 'config/.env'
compose = 'config/compose.yml'
requirements = 'config/requirements'
addons_paths = ['.']
db_service = 'db'
dev_prefix = 'acme_dev_'
test_prefix = 'acme_test_'
logs = 'logs'
data_dir = 'data'
agent_destructive = 'ask'
```

## Machine file

The Odoo source of each series is the machine's, not the project's: it normally lives in one file of the machine, `$XDG_CONFIG_HOME/oasis/config.toml` (`~/.config/oasis/config.toml` when `XDG_CONFIG_HOME` is unset, empty or relative), so every workspace on that machine uses it without repeating it. A workspace declares a source only to override it for that project; workspace files that already declare it keep working, with or without a machine file.

```toml
# ~/.config/oasis/config.toml, example only.
[series."19.0"]
community = '/srv/odoo/19.0/source/odoo'
enterprise = '/srv/odoo/19.0/source/enterprise'
environments = '/srv/odoo/19.0/environments'
```

- Keys: only `[series."<x.y>"]` tables of supported series (19.0, 15.0), each with optional `community`, `enterprise` and `environments`. Relative paths resolve from the machine file's directory; absolute paths are used as written (`~` is not expanded).
- Precedence, each value in one place: `oasis-checkout.toml` (slug, environment name) over `oasis-workspace.toml` over the machine file. A workspace's `[tooling].community` or `[tooling].enterprise` overrides the machine file's; `enterprise = false` turns the machine's Enterprise off for that project. `environments` is where `oasis setup` proposes new environments; it never chooses a checkout's environment, which stays in the workspace file.
- Without a source: a workspace without `[tooling].community`, on a machine whose file gives none for its series, stops every command with `No Odoo source for 19.0: create the machine file <path> with community under [series."19.0"], or set [tooling].community in <workspace file>.` (when the file exists: `No Odoo source for 19.0: set community under [series."19.0"] in the machine file <path>, or [tooling].community in <workspace file>.`).
- Agents: the Gentle Shell layer asks the user before an agent changes it, whatever `agent_destructive` says (see [Bash guard](bash-guard.md#the-setting-files)).
- Checks: the file is trusted like a workspace file (see [Trust](#trust); the refusal says `machine file`) and checked whole, every series, whichever series the project uses. Errors stop every command (exit 2): `Invalid TOML in <file>.`, `Unknown key <key> in <file>; the machine file holds only [series."<version>"] tables.`, `Invalid [series] in <file>.`, `Unknown series <v> in <file>; supported: 19.0, 15.0.`, `Invalid [series.<v>] in <file>.`, `Unknown key series.<v>.<key> in <file>; use community, enterprise or environments.` and `Invalid machine path series.<v>.<key> in <file>.`

## Discovery, precedence and versions

- Discovery: the checkout root is the `--project` directory; without `--project`, the git top level of the current directory (the current directory itself outside git; when git fails inside a repository the command stops with `Cannot determine the project root of <dir>: git failed (<reason>); pass --project.`). In Gentle Shell it is the git top level of the session directory, compared by real path, so a session directory reached through a symlink resolves to the checkout root. oasis walks up from it to the nearest `oasis-workspace.toml`, as git finds `.git`, up to the filesystem root. When none is found and the checkout is a linked git worktree, oasis asks git for its main checkout (`git rev-parse --git-common-dir`) and uses the file the main checkout reads, so a worktree can live in any directory; its slug still comes from its own directory name, its `oasis-checkout.toml` and `addons_paths` from its own root, and the other paths from the workspace file's directory. The upward search comes first, so a workspace file above the worktree wins, and the file found through git is checked like any other (see [Trust](#trust)). Without one every command stops with `Missing tooling configuration: no oasis-workspace.toml at or above <checkout>.` (exit 2).
- A checkout that still has the per-checkout file of earlier versions is refused before anything runs, also next to a workspace file; [Migrating to the workspace file](migrating.md) converts it.
- Versions: the top level must set `workspace_version = 1` (one series) or `2` ([several series](#several-series-workspace_version-2)) and `odoo_version` to a supported series (`'19.0'` or `'15.0'`; with version 2, the default series). Any other value stops every command with `Unsupported workspace_version <v> in <file>.` or `Unsupported odoo_version <v> in <file>; supported: 19.0, 15.0.` (`<v>` in JSON form: strings in quotes, `(missing)` when absent). A file that is not valid TOML gives `Invalid TOML in <file>.`
- Series of the modules: a checkout whose modules carry a series-style version of another series is refused before anything runs (exit 2), for example a worktree of a 16.0 branch that reads the main checkout's 19.0 workspace file through git: `The module <module> declares Odoo 16.0 (version 16.0.1.0.0 in <manifest>), but <checkout> is configured for Odoo 19.0 by <workspace file>: run oasis in a checkout of an Odoo 19.0 branch, or set the version of <module> to 19.0.x.y.z if it is an Odoo 19.0 module; oasis does not support Odoo 16.0 (supported: 19.0, 15.0).` For a supported series it ends with the [series model](#several-series-workspace_version-2) instead: `; for Odoo 15.0 here, run oasis setup to add a [series."15.0"] section to <workspace file>` (with `workspace_version = 2` and a section for that series: `; for Odoo 15.0 here, set odoo_version = '15.0' in <checkout>/oasis-checkout.toml`). Only `<addons path>/<module>/__manifest__.py` of each `addons_paths` entry is read, never imported (hidden directories skipped), and most manifests are not parsed: a manifest with no series-style number is skipped, and one whose `version` key appears once, as a plain string literal (`'version': '19.0.1.0.0',`), is decided from that string alone: ignored when it is not series-style, accepted when it is the configured series. Only a version of another series, or a manifest whose version cannot be read that way (the key repeated, a non-literal value), is parsed whole with `ast.literal_eval`, and the refusal follows the parsed dict; a manifest that does not parse is ignored. The first offending module, in `addons_paths` order then by name, is named. A version counts when it is `<major>.<minor>.<x>.<y>.<z>` and the series is supported or looks like an Odoo release (`<major>.0`, major 8 to 99); others (`1.0`, `1.2.3.4.5`, `15.1.1.0.0`) are ignored. `doctor` reports it as one `FAIL module_series=...` and goes on; `setup` refuses it for an existing workspace file or a `--series` that disagrees, but a new checkout's series it infers itself from the same manifests. With `workspace_version = 2` the checkout's own series is checked instead, the modules of its `series_exceptions` are skipped, and the refusal's fix also names them: `..., or list <module> in series_exceptions under [series."<x.y>"] in <workspace file>`, see [Series exceptions](#series-exceptions).

## Tooling keys

- `[tooling]` keys: `community` and `enterprise`, both optional (the [machine file](#machine-file) gives them; set here they override it, and `enterprise = false` means no Enterprise for this project), `environment` (or named `[environments]`, below), `config`, `env_file`, `compose`, `requirements`, `addons_paths`, `db_service`, `dev_prefix` and `test_prefix` (`<name>_dev_` and `<name>_test_`), and optional `test_database`, `logs`, `data_dir`, `lint_rcfile` (see [Lint module](lint-module.md)) and `agent_destructive`; the guards are in [Project contract](../odoo19-environment/references/project-contract.md). An optional `[development]` table declares the accounts of `init-dev-database` (see [Development database](dev-database.md)); advisory sections such as `[odoo].version` must agree with `[tooling]`. `version` and `python_version` are not keys: they derive from `odoo_version` (the series' default Python, 3.12 on 19.0, or the selected named environment's `python`) and are refused when set (`[tooling].<key> is derived in a workspace; remove it from <file>.`). Every relative path resolves from the workspace file's directory, except `addons_paths`, which resolves from each checkout (`'.'` is the checkout itself), because the modules live in every checkout. Absolute paths are accepted for every path key and used as written; `~` and `$HOME` are not expanded. The environment target rule: once resolved, it may be any directory, whatever its name or place, that is a Python environment (it has `pyvenv.cfg`) or does not exist yet (`bootstrap` creates it); it may not be or contain the checkout, nor be or contain the Odoo source, even with a `pyvenv.cfg`. Otherwise every command stops with `Unsafe tooling environment target: <dir> is or contains the checkout <checkout>.`, `Unsafe tooling environment target: <dir> is or contains the Odoo source <source>.` or `Unsafe tooling environment target: <dir> exists and is not a Python environment (no pyvenv.cfg).` (see [Paths](new-workspace.md#paths)).
- `agent_destructive` (optional, in the workspace file) decides what the Gentle Shell layer does when an agent runs `drop-database`, `stop --database` or `gc --apply --trash`: `'ask'` (the default) shows the user a dialog first, `'deny'` blocks them, `'allow'` lets them run without a dialog (see [Bash guard](bash-guard.md)). Any other value, or a value that is not a string, stops every command with `Invalid tooling agent_destructive: use ask, deny or allow.` `oasis-checkout.toml` cannot set it, and no tool argument changes it; the agent's changes to the workspace file go through the same dialog (see [Bash guard](bash-guard.md#the-setting-files)); `doctor` prints `PASS agent_destructive=<value>`.

## Checkout file and named environments

- `checkout_slug` is per checkout, so the workspace file refuses it. An optional `oasis-checkout.toml` in the checkout may set only that key and `environment` (the name of a named environment) under `[tooling]`, and, at the top level, `odoo_version`, the checkout's series (see [The checkout's series](#the-checkouts-series)); any other key or table is refused with `oasis-checkout.toml may only set [tooling].checkout_slug and [tooling].environment: <key>` (`tooling.logs`, `odoo`, ...).
- Named environments: instead of `[tooling].environment`, the workspace may declare `[environments.<name>]` tables with `path` (relative to the workspace file, with the same rules as `[tooling].environment`) and `python` (`'3.<minor>'`). A checkout uses `default` unless its `oasis-checkout.toml` sets `environment`. Errors: `Unknown environment <name>; <file> declares: <names or (none)>.`, `Unsupported python <v> for environment <name> in <file>; Odoo 19.0 supports 3.10 to 3.14.`, `Invalid [environments] in <file>.`, `Invalid environment <name> in <file>.`, and `Set either [tooling].environment or [environments] in <file>, not both.` The Python of the environment's interpreter must then match that `python`; with `[tooling].environment` it must match the series' default (`python_default` in `tools/odoo_versions.py`: 3.12 on 19.0). `bootstrap` creates the environment with that Python, and `doctor` and `check-environment` check it (see [The declared Python](checking-environment.md#the-declared-python)).

```toml
# <checkout>/oasis-checkout.toml, example only.
[tooling]
checkout_slug = 'mrp_2'
environment = 'next'
```

```toml
# In oasis-workspace.toml, example only, in place of [tooling].environment.
[environments.default]
path = 'environments/acme'
python = '3.12'

[environments.next]
path = 'environments/acme-next'
python = '3.13'
```

## Several series (workspace_version 2)

One workspace file can configure checkouts of several Odoo series (for example the `15.0` and `19.0` branches of one repository), each with its own source, environment, PostgreSQL, credentials, database prefixes, data and logs. `workspace_version = 2` keeps every key of version 1, and:

- `odoo_version` is the default series: the series of a checkout that declares none and whose modules tell none.
- `[tooling]` holds what the series share. In its path values (`community`, `enterprise`, `environment`, `config`, `env_file`, `compose`, `requirements`, `logs`, `data_dir`, `lint_rcfile`) and in the `path` of named `[environments]`, `{series}` is replaced by the checkout's series (`logs = 'logs/{series}'` is `logs/15.0` in a 15.0 checkout). Version 1 does not replace it.
- `[series."<x.y>"]` holds what differs for that series, over `[tooling]`: `community`, `enterprise`, `environment` (a path), `config`, `env_file`, `compose` (with its compose project and published port), `requirements`, `db_service`, `dev_prefix`, `test_prefix`, `test_database`, `logs`, `data_dir` and `series_exceptions`. Its values keep the `[tooling]` rules (`Unsafe tooling database prefixes.`, `Invalid tooling path: <key>.`, ...). The default series may have a section too; any other series needs one.
- Errors (exit 2): `Invalid [series] in <file>.`, `Unknown series "<v>" in <file>; supported: <series>.`, `Invalid [series."<v>"] in <file>.`, `Unknown key series."<v>".<key> in <file>; a series section may set: community, enterprise, environment, config, env_file, compose, requirements, db_service, dev_prefix, test_prefix, test_database, logs, data_dir, series_exceptions.`, `Invalid series."<v>".series_exceptions in <file>: use a list of module names.` and `[tooling].series_exceptions belongs in a [series."<version>"] section of <file>.`

### The checkout's series

Each checkout (and each linked worktree) works with one series, chosen in this order:

1. `odoo_version` at the top of its `oasis-checkout.toml` (`from=checkout`); an unsupported value stops with `Unsupported odoo_version <v> in <checkout>/oasis-checkout.toml; supported: <series>.`
2. Else, with version 2, the series its module manifests declare (`from=manifests`): the `<addons path>/<module>/__manifest__.py` of each `addons_paths` entry, read as the [series guard](#discovery-precedence-and-versions) reads them, the modules listed in any section's `series_exceptions` and the series oasis does not support left out. Modules of several supported series stop with `The modules of <checkout> declare several Odoo series: 15.0 (<first module>), 19.0 (<first module>); set odoo_version in <checkout>/oasis-checkout.toml to the series of this checkout, or list the modules of the other series in series_exceptions under its [series."<version>"] in <file>.`
3. Else the workspace `odoo_version` (`from=workspace`).

A series other than the default without a section stops every command with `<checkout> is an Odoo 15.0 checkout (the series of its module manifests), but <file> has no [series."15.0"] section: run oasis setup to add it.` (or `(odoo_version in <checkout>/oasis-checkout.toml)`); with version 1 that is any series other than its `odoo_version`.

Precedence, each value in one place: `oasis-checkout.toml` (series, slug, environment name) over the workspace's `[series."<x.y>"]` over its `[tooling]` over the [machine file](#machine-file)'s `[series."<x.y>"]` over the series table (`tools/odoo_versions.py`: the default Python, the Odoo options). For the environment: the checkout's named environment, else the section's `environment`, else the default named environment, else `[tooling].environment`; a named environment's `python` must be within the range of the checkout's series.

### Series exceptions

`series_exceptions` lists the modules of a checkout of that series whose manifests declare another series on purpose (a module ported without changing its version, for example `report_xlsx` declaring `16.0.2.0.2` in a 15.0 branch). The series guard does not refuse them for that series, and the series detection leaves them out. `doctor` shows them as `PASS series_exceptions=report_xlsx` (comma-separated).

### Isolation

Two series of one workspace may not share a database: `doctor` fails, for each group of series that resolve to the same value, `FAIL series_isolation=db_port series=19.0,15.0` (the host port the compose file publishes to 5432), `compose_project` (its top-level `name:`), `prefixes` (`dev_prefix` or `test_prefix`) and `env_file` (the database account), each with the fix for the series after the first; otherwise it shows `PASS series_isolation=19.0,15.0` (see [The doctor report](checking-environment.md#the-doctor-report)).

### Example

A repository with 19.0 branches and 15.0 branches, the 15.0 files of an earlier setup kept in `config/odoo-15/` (PostgreSQL 14 published on port 5415, databases `cc15_`):

```toml
# Example only: corpus-cafe/oasis-workspace.toml
workspace_version = 2
odoo_version = '19.0'

[tooling]
environment = 'environments/corpus-cafe-{series}'
config = 'config/odoo.conf'
env_file = 'config/.env'
compose = 'config/compose.yml'
requirements = 'config/requirements/{series}'
addons_paths = ['.']
db_service = 'db'
dev_prefix = 'cc_dev_'
test_prefix = 'cc_test_'
logs = 'logs/{series}'
data_dir = 'data/{series}'

[series."15.0"]
config = 'config/odoo-15/odoo.conf'
env_file = 'config/odoo-15/.env'
compose = 'config/odoo-15/compose.yml'
dev_prefix = 'cc15_dev_'
test_prefix = 'cc15_test_'
series_exceptions = ['report_xlsx']
```

```text
corpus-cafe/codigo/facturacion        a 15.0 branch: config/odoo-15/odoo.conf, cc15_dev_, logs/15.0, environments/corpus-cafe-15.0
corpus-cafe/codigo/corpus-cafe        a 19.0 branch: config/odoo.conf, cc_dev_, logs/19.0, environments/corpus-cafe-19.0
config/odoo-15/compose.yml            postgres:14-alpine published on 127.0.0.1:5415, its own top-level name
~/.config/oasis/config.toml           community (and enterprise) under [series."15.0"] and [series."19.0"]
```

## Trust

- Trust: a found `oasis-workspace.toml` or `oasis-checkout.toml` is read only when the file and its directory are owned by the current user or root and are not group- or other-writable (a symlinked file is also checked at its target); otherwise every command stops with `Refusing untrusted workspace file <file>: <path> is not owned by the current user or root.` or `Refusing untrusted workspace file <file>: <path> is writable by group or others.` Directories above the workspace's own (for example `/tmp`) are not checked. The [machine file](#machine-file) is checked the same way, with `Refusing untrusted machine file <file>: ...`.

## What the tools read from it

- `tools/config.py` emits the checkout's paths, prefixes and identity, then `LOGS_DIR`, `WORKSPACE_ROOT` (the workspace directory) and, after it, `ODOO_VERSION`, `ODOO_SECOND_PORT_OPTION` and `ODOO_DEMO_OFF_ARGS` (the Odoo series and its options from `tools/odoo_versions.py`, the only file that writes version-specific Odoo options), `ENVIRONMENT_NAME` (the named environment, empty otherwise), `PYTHON_VERSION`, `DATA_DIR` (the resolved `[tooling].data_dir`, empty when absent) and `AGENT_DESTRUCTIVE` (`[tooling].agent_destructive`, `ask` when absent); with `workspace_version = 2` only, last, `WORKSPACE_VERSION=2` and `SERIES_EXCEPTIONS` (the checkout series' exceptions, one per line). Every value, `ODOO_VERSION` first, is the checkout's series', so every tool follows it; version 1 output is unchanged.
- `tools/config.py --origins <checkout>` prints, once the configuration is valid, where its layered values came from (for `doctor`): `MACHINE_FILE` (the machine file read, empty without one), `MACHINE_ENVIRONMENTS_DIR` (its resolved `environments`, empty when absent), `ODOO_SOURCE_FROM` and `ENTERPRISE_SOURCE_FROM` (`machine` or `workspace`; empty without Enterprise), `PROJECT_ENVIRONMENT_FROM` (`checkout` when `oasis-checkout.toml` selects the named environment, else `workspace`) and `CHECKOUT_SLUG_FROM` (`checkout`, `derived` from a linked worktree's directory name, empty without a slug), then, with `workspace_version = 2` only, `ODOO_VERSION_FROM` (`checkout`, `manifests` or `workspace`, see [The checkout's series](#the-checkouts-series)). The assignments above are unchanged. `doctor` shows the non-empty ones as `PASS odoo_source_from=machine:<file>`, `PASS enterprise_source_from=...`, `PASS project_environment_from=workspace:<file>` and `PASS checkout_slug_from=checkout:<file>` (or `derived`), see [The doctor report](checking-environment.md#the-doctor-report).
- Odoo series options: `start` passes the second server port with `ODOO_SECOND_PORT_OPTION` (`--gevent-port` on 19.0) and recognizes it when given; `test-module`, `install-module` (and so `verify-module`) and `init-dev-database` render the demo-off options from `ODOO_DEMO_OFF_ARGS`. On 19.0 the table keeps `--without-demo`, so every Odoo command line is unchanged.
- `worktree-init` only runs `git worktree add` and prints `workspace: <dir>` after the slug line: nothing is copied or linked (see [worktree-init](checkouts-and-worktrees.md#worktree-init)). The new folder reads the main checkout's workspace file, above it or through git; a folder below another workspace file is refused (`The new worktree <path> would read <file>, not the main checkout's <file>; choose another --path.`).
- `init-dev-database` reads `[development]` from the workspace file and `lint-module` reads `[tooling].lint_rcfile` from it, resolved from the workspace file's directory like the other tooling paths. `gc`, the trash and `list-databases` take the slug of another worktree from its `oasis-checkout.toml` (else from the folder name), so the main checkout skips that worktree's namespace; a worktree whose slug cannot be read stops them (exit 2) with `Cannot read the checkout slug of <worktree>: <reason>`.
