# Workspace file

One `oasis-workspace.toml` at the project root configures every checkout: checkouts and linked worktrees at any depth below it read the same file, so a new worktree needs no copy of it, and a linked worktree anywhere else reads the main checkout's file through git (see [Discovery](#discovery-precedence-and-versions)). The Odoo source of each series comes from the [machine file](#machine-file); the workspace file sets it only to override it. Review the [example workspace file](../odoo19-environment/assets/oasis-workspace.example.toml). To start a project from an empty folder, follow [Setting up a new workspace](new-workspace.md): the steps, an annotated example tree and accepted and refused paths.

## Layout and example

```text
<project>/oasis-workspace.toml                the workspace file
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

- Keys: only `[series."<x.y>"]` tables of supported series (19.0), each with optional `community`, `enterprise` and `environments`. Relative paths resolve from the machine file's directory; absolute paths are used as written (`~` is not expanded).
- Precedence, each value in one place: `oasis-checkout.toml` (slug, environment name) over `oasis-workspace.toml` over the machine file. A workspace's `[tooling].community` or `[tooling].enterprise` overrides the machine file's; `enterprise = false` turns the machine's Enterprise off for that project. `environments` is where `oasis setup` proposes new environments; it never chooses a checkout's environment, which stays in the workspace file.
- Without a source: a workspace without `[tooling].community`, on a machine whose file gives none for its series, stops every command with `No Odoo source for 19.0: create the machine file <path> with community under [series."19.0"], or set [tooling].community in <workspace file>.` (when the file exists: `No Odoo source for 19.0: set community under [series."19.0"] in the machine file <path>, or [tooling].community in <workspace file>.`).
- Agents: the Gentle Shell layer asks the user before an agent changes it, whatever `agent_destructive` says (see [Bash guard](bash-guard.md#the-setting-files)).
- Checks: the file is trusted like a workspace file (see [Trust](#trust); the refusal says `machine file`) and checked whole, every series, whichever series the project uses. Errors stop every command (exit 2): `Invalid TOML in <file>.`, `Unknown key <key> in <file>; the machine file holds only [series."<version>"] tables.`, `Invalid [series] in <file>.`, `Unknown series <v> in <file>; supported: 19.0.`, `Invalid [series.<v>] in <file>.`, `Unknown key series.<v>.<key> in <file>; use community, enterprise or environments.` and `Invalid machine path series.<v>.<key> in <file>.`

## Discovery, precedence and versions

- Discovery: the checkout root is the `--project` directory; without `--project`, the git top level of the current directory (the current directory itself outside git; when git fails inside a repository the command stops with `Cannot determine the project root of <dir>: git failed (<reason>); pass --project.`). In Gentle Shell it is the git top level of the session directory, compared by real path, so a session directory reached through a symlink resolves to the checkout root. oasis walks up from it to the nearest `oasis-workspace.toml`, as git finds `.git`, up to the filesystem root. When none is found and the checkout is a linked git worktree, oasis asks git for its main checkout (`git rev-parse --git-common-dir`) and uses the file the main checkout reads, so a worktree can live in any directory; its slug still comes from its own directory name, its `oasis-checkout.toml` and `addons_paths` from its own root, and the other paths from the workspace file's directory. The upward search comes first, so a workspace file above the worktree wins, and the file found through git is checked like any other (see [Trust](#trust)). Without one every command stops with `Missing tooling configuration: no oasis-workspace.toml at or above <checkout>.` (exit 2).
- A checkout that still has the per-checkout file of earlier versions is refused before anything runs, also next to a workspace file; [Migrating to the workspace file](migrating.md) converts it.
- Versions: the top level must set `workspace_version = 1` and `odoo_version = '19.0'`. Any other value stops every command with `Unsupported workspace_version <v> in <file>.` or `Unsupported odoo_version <v> in <file>; supported: 19.0.` (`<v>` in JSON form: strings in quotes, `(missing)` when absent). A file that is not valid TOML gives `Invalid TOML in <file>.`

## Tooling keys

- `[tooling]` keys: `community` and `enterprise`, both optional (the [machine file](#machine-file) gives them; set here they override it, and `enterprise = false` means no Enterprise for this project), `environment` (or named `[environments]`, below), `config`, `env_file`, `compose`, `requirements`, `addons_paths`, `db_service`, `dev_prefix` and `test_prefix` (`<name>_dev_` and `<name>_test_`), and optional `test_database`, `logs`, `data_dir`, `lint_rcfile` (see [Lint module](lint-module.md)) and `agent_destructive`; the guards are in [Project contract](../odoo19-environment/references/project-contract.md). An optional `[development]` table declares the accounts of `init-dev-database` (see [Development database](dev-database.md)); advisory sections such as `[odoo].version` must agree with `[tooling]`. `version` and `python_version` are not keys: they derive from `odoo_version` (the series' default Python, 3.12 on 19.0, or the selected named environment's `python`) and are refused when set (`[tooling].<key> is derived in a workspace; remove it from <file>.`). Every relative path resolves from the workspace file's directory, except `addons_paths`, which resolves from each checkout (`'.'` is the checkout itself), because the modules live in every checkout. Absolute paths are accepted for every path key and used as written; `~` and `$HOME` are not expanded. The environment target rule: once resolved, it may be any directory, whatever its name or place, that is a Python environment (it has `pyvenv.cfg`) or does not exist yet (`bootstrap` creates it); it may not be or contain the checkout, nor be or contain the Odoo source, even with a `pyvenv.cfg`. Otherwise every command stops with `Unsafe tooling environment target: <dir> is or contains the checkout <checkout>.`, `Unsafe tooling environment target: <dir> is or contains the Odoo source <source>.` or `Unsafe tooling environment target: <dir> exists and is not a Python environment (no pyvenv.cfg).` (see [Paths](new-workspace.md#paths)).
- `agent_destructive` (optional, in the workspace file) decides what the Gentle Shell layer does when an agent runs `drop-database`, `stop --database` or `gc --apply --trash`: `'ask'` (the default) shows the user a dialog first, `'deny'` blocks them, `'allow'` lets them run without a dialog (see [Bash guard](bash-guard.md)). Any other value, or a value that is not a string, stops every command with `Invalid tooling agent_destructive: use ask, deny or allow.` `oasis-checkout.toml` cannot set it, and no tool argument changes it; the agent's changes to the workspace file go through the same dialog (see [Bash guard](bash-guard.md#the-setting-files)); `doctor` prints `PASS agent_destructive=<value>`.

## Checkout file and named environments

- `checkout_slug` is per checkout, so the workspace file refuses it. An optional `oasis-checkout.toml` in the checkout may set only that key and `environment` (the name of a named environment); any other key or table is refused with `oasis-checkout.toml may only set [tooling].checkout_slug and [tooling].environment: <key>` (`tooling.logs`, `odoo`, ...).
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

## Trust

- Trust: a found `oasis-workspace.toml` or `oasis-checkout.toml` is read only when the file and its directory are owned by the current user or root and are not group- or other-writable (a symlinked file is also checked at its target); otherwise every command stops with `Refusing untrusted workspace file <file>: <path> is not owned by the current user or root.` or `Refusing untrusted workspace file <file>: <path> is writable by group or others.` Directories above the workspace's own (for example `/tmp`) are not checked. The [machine file](#machine-file) is checked the same way, with `Refusing untrusted machine file <file>: ...`.

## What the tools read from it

- `tools/config.py` emits the checkout's paths, prefixes and identity, then `LOGS_DIR`, `WORKSPACE_ROOT` (the workspace directory) and, after it, `ODOO_VERSION`, `ODOO_SECOND_PORT_OPTION` and `ODOO_DEMO_OFF_ARGS` (the Odoo series and its options from `tools/odoo_versions.py`, the only file that writes version-specific Odoo options), `ENVIRONMENT_NAME` (the named environment, empty otherwise), `PYTHON_VERSION`, `DATA_DIR` (the resolved `[tooling].data_dir`, empty when absent) and, last, `AGENT_DESTRUCTIVE` (`[tooling].agent_destructive`, `ask` when absent).
- `tools/config.py --origins <checkout>` prints, once the configuration is valid, where its layered values came from (for `doctor`): `MACHINE_FILE` (the machine file read, empty without one), `MACHINE_ENVIRONMENTS_DIR` (its resolved `environments`, empty when absent), `ODOO_SOURCE_FROM` and `ENTERPRISE_SOURCE_FROM` (`machine` or `workspace`; empty without Enterprise), `PROJECT_ENVIRONMENT_FROM` (`checkout` when `oasis-checkout.toml` selects the named environment, else `workspace`) and `CHECKOUT_SLUG_FROM` (`checkout`, `derived` from a linked worktree's directory name, empty without a slug). The assignments above are unchanged.
- Odoo series options: `start` passes the second server port with `ODOO_SECOND_PORT_OPTION` (`--gevent-port` on 19.0) and recognizes it when given; `test-module`, `install-module` (and so `verify-module`) and `init-dev-database` render the demo-off options from `ODOO_DEMO_OFF_ARGS`. On 19.0 the table keeps `--without-demo`, so every Odoo command line is unchanged.
- `worktree-init` only runs `git worktree add` and prints `workspace: <dir>` after the slug line: nothing is copied or linked (see [worktree-init](checkouts-and-worktrees.md#worktree-init)). The new folder reads the main checkout's workspace file, above it or through git; a folder below another workspace file is refused (`The new worktree <path> would read <file>, not the main checkout's <file>; choose another --path.`).
- `init-dev-database` reads `[development]` from the workspace file and `lint-module` reads `[tooling].lint_rcfile` from it, resolved from the workspace file's directory like the other tooling paths. `gc`, the trash and `list-databases` take the slug of another worktree from its `oasis-checkout.toml` (else from the folder name), so the main checkout skips that worktree's namespace; a worktree whose slug cannot be read stops them (exit 2) with `Cannot read the checkout slug of <worktree>: <reason>`.
