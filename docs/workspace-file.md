# Workspace file

One `oasis-workspace.toml` at the project root configures every checkout: checkouts and linked worktrees at any depth below it read the same file, so a new worktree needs no copy of it. Review the [example workspace file](../odoo19-environment/assets/oasis-workspace.example.toml). To start a project from an empty folder, follow [Setting up a new workspace](new-workspace.md): the steps, an annotated example tree and accepted and refused paths.

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
community = 'source/odoo'
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

## Discovery, precedence and versions

- Discovery: the checkout root is the `--project` directory (in Gentle Shell, the git top level of the session directory, compared by real path, so a session directory reached through a symlink resolves to the checkout root). oasis walks up from it to the nearest `oasis-workspace.toml`, as git finds `.git`, up to the filesystem root. Without one every command stops with `Missing tooling configuration: no oasis-workspace.toml at or above <checkout>.` (exit 2).
- A checkout that still has the per-checkout file of earlier versions is refused before anything runs, also next to a workspace file; [Migrating to the workspace file](migrating.md) converts it.
- Versions: the top level must set `workspace_version = 1` and `odoo_version = '19.0'`. Any other value stops every command with `Unsupported workspace_version <v> in <file>.` or `Unsupported odoo_version <v> in <file>; supported: 19.0.` (`<v>` in JSON form: strings in quotes, `(missing)` when absent). A file that is not valid TOML gives `Invalid TOML in <file>.`

## Tooling keys

- `[tooling]` keys: `community`, optional `enterprise`, `environment` (or named `[environments]`, below), `config`, `env_file`, `compose`, `requirements`, `addons_paths`, `db_service`, `dev_prefix` and `test_prefix` (`<name>_dev_` and `<name>_test_`), and optional `test_database`, `logs`, `data_dir`, `lint_rcfile` (see [Lint module](lint-module.md)) and `agent_destructive`; the guards are in [Project contract](../odoo19-environment/references/project-contract.md). An optional `[development]` table declares the accounts of `init-dev-database` (see [Development database](dev-database.md)); advisory sections such as `[odoo].version` must agree with `[tooling]`. `version` and `python_version` are not keys: they derive from `odoo_version` (the series' default Python, 3.12 on 19.0, or the selected named environment's `python`) and are refused when set (`[tooling].<key> is derived in a workspace; remove it from <file>.`). Every relative path resolves from the workspace file's directory, except `addons_paths`, which resolves from each checkout (`'.'` is the checkout itself), because the modules live in every checkout. Absolute paths are accepted for every path key and used as written; `~` and `$HOME` are not expanded. The environment target rule: once resolved, it must be inside the checkout or directly in a directory whose name ends in `environments`, and it may not be the checkout or one of its parents, nor be or contain the Odoo source; otherwise every command stops with `Unsafe tooling environment target.` An environment inside one checkout is outside every other checkout, which refuses it, so a workspace keeps its environments in an `environments` directory (see [Paths](new-workspace.md#paths)).
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

- Trust: a found `oasis-workspace.toml` or `oasis-checkout.toml` is read only when the file and its directory are owned by the current user or root and are not group- or other-writable (a symlinked file is also checked at its target); otherwise every command stops with `Refusing untrusted workspace file <file>: <path> is not owned by the current user or root.` or `Refusing untrusted workspace file <file>: <path> is writable by group or others.` Directories above the workspace's own (for example `/tmp`) are not checked.

## What the tools read from it

- `tools/config.py` emits the checkout's paths, prefixes and identity, then `LOGS_DIR`, `WORKSPACE_ROOT` (the workspace directory) and, after it, `ODOO_VERSION`, `ODOO_SECOND_PORT_OPTION` and `ODOO_DEMO_OFF_ARGS` (the Odoo series and its options from `tools/odoo_versions.py`, the only file that writes version-specific Odoo options), `ENVIRONMENT_NAME` (the named environment, empty otherwise), `PYTHON_VERSION`, `DATA_DIR` (the resolved `[tooling].data_dir`, empty when absent) and, last, `AGENT_DESTRUCTIVE` (`[tooling].agent_destructive`, `ask` when absent).
- Odoo series options: `start` passes the second server port with `ODOO_SECOND_PORT_OPTION` (`--gevent-port` on 19.0) and recognizes it when given; `test-module`, `install-module` (and so `verify-module`) and `init-dev-database` render the demo-off options from `ODOO_DEMO_OFF_ARGS`. On 19.0 the table keeps `--without-demo`, so every Odoo command line is unchanged.
- `worktree-init` only runs `git worktree add` and prints `workspace: <dir>` after the slug line: nothing is copied or linked (see [worktree-init](checkouts-and-worktrees.md#worktree-init)). The new folder must be below the workspace directory (`The new worktree <path> would not be under the workspace <dir>; prepare the worktree by hand.` otherwise).
- `init-dev-database` reads `[development]` from the workspace file and `lint-module` reads `[tooling].lint_rcfile` from it, resolved from the workspace file's directory like the other tooling paths. `gc`, the trash and `list-databases` take the slug of another worktree from its `oasis-checkout.toml` (else from the folder name), so the main checkout skips that worktree's namespace; a worktree whose slug cannot be read stops them (exit 2) with `Cannot read the checkout slug of <worktree>: <reason>`.
