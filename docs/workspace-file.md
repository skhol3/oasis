# Workspace file

One `oasis-workspace.toml` at the project root can replace the profile of every checkout: checkouts and linked worktrees at any depth below it read the same file, so a worktree needs no profile copy. Review the [example workspace file](../odoo19-environment/assets/oasis-workspace.example.toml).

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
```

## Discovery, precedence and versions

- Discovery: the checkout root is the `--project` directory (in Gentle Shell, the git top level of the session directory, compared by real path, so a session directory reached through a symlink resolves to the checkout root). When it has no `.odoo19-agent.toml`, oasis walks up from it to the nearest `oasis-workspace.toml`, as git finds `.git`, up to the filesystem root. A directory with a `.odoo19-agent.toml` on the way ends the search. Without either file every command keeps the error `Missing tooling configuration: <checkout>/.odoo19-agent.toml`.
- Precedence: a checkout with its own `.odoo19-agent.toml` is read exactly as before and ignores the workspace file. Legacy profiles keep working; nothing has to move.
- Versions: the top level must set `workspace_version = 1` and `odoo_version = '19.0'`. Any other value stops every command with `Unsupported workspace_version <v> in <file>.` or `Unsupported odoo_version <v> in <file>; supported: 19.0.` (`<v>` in JSON form: strings in quotes, `(missing)` when absent). A file that is not valid TOML gives `Invalid TOML in <file>.`

## Tooling keys

- `[tooling]` takes the profile's keys and guards (prefixes, `test_database`, `logs`, `data_dir`, `enterprise`, and the advisory sections such as `[odoo].version`), except `version` and `python_version`: they derive from `odoo_version` (Python 3.12, or the selected named environment's `python`) and are refused when set (`[tooling].<key> is derived in a workspace; remove it from <file>.`). Every path resolves from the workspace file's directory, except `addons_paths`, which resolves from each checkout (`'.'` is the checkout itself), because the modules live in every checkout. The environment target keeps the profile rule: inside the checkout, or in a directory whose name ends in `environments`.

## Checkout file and named environments

- `checkout_slug` is per checkout, so the workspace file refuses it. An optional `oasis-checkout.toml` in the checkout may set only that key and `environment` (the name of a named environment); any other key or table is refused with `oasis-checkout.toml may only set [tooling].checkout_slug and [tooling].environment: <key>` (`tooling.logs`, `odoo`, ...). In a checkout with a profile it is not read.
- Named environments: instead of `[tooling].environment`, the workspace may declare `[environments.<name>]` tables with `path` (relative to the workspace file, with the same rules as `[tooling].environment`) and `python` (`'3.<minor>'`). A checkout uses `default` unless its `oasis-checkout.toml` sets `environment`. Errors: `Unknown environment <name>; <file> declares: <names or (none)>.`, `Unsupported python <v> for environment <name> in <file>; Odoo 19.0 supports 3.10 to 3.14.`, `Invalid [environments] in <file>.`, `Invalid environment <name> in <file>.`, and `Set either [tooling].environment or [environments] in <file>, not both.` The Python of the environment's interpreter must then match that `python`; a profile, and a workspace with `[tooling].environment`, keep Python 3.12.

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

- Trust: a found `oasis-workspace.toml` or `oasis-checkout.toml` is read only when the file and its directory are owned by the current user or root and are not group- or other-writable (a symlinked file is also checked at its target); otherwise every command stops with `Refusing untrusted workspace file <file>: <path> is not owned by the current user or root.` or `Refusing untrusted workspace file <file>: <path> is writable by group or others.` Directories above the workspace's own (for example `/tmp`) are not checked. A legacy profile keeps its previous rules.

## What the tools read from it

- `tools/config.py` emits the same assignments as for a profile, plus `WORKSPACE_ROOT` (the workspace directory, empty for a profile). After it, for a profile too, come `ODOO_VERSION`, `ODOO_SECOND_PORT_OPTION` and `ODOO_DEMO_OFF_ARGS` (the Odoo series and its options from `tools/odoo_versions.py`, the only file that writes version-specific Odoo options), `ENVIRONMENT_NAME` (the named environment, empty otherwise), `PYTHON_VERSION` and `DATA_DIR` (the resolved `[tooling].data_dir`, empty when absent). Checkout identity, slugs and database names are unchanged.
- Odoo series options: `start` passes the second server port with `ODOO_SECOND_PORT_OPTION` (`--gevent-port` on 19.0) and recognizes it when given; `test-module`, `install-module` (and so `verify-module`) and `init-dev-database` render the demo-off options from `ODOO_DEMO_OFF_ARGS`. On 19.0 the table keeps `--without-demo`, so every Odoo command line is unchanged.
- `worktree-init`, when the main checkout has no profile and finds a workspace file, only runs `git worktree add` and prints `workspace: <dir>` after the slug line: nothing is copied or linked. The new folder must be below the workspace directory (`The new worktree <path> would not be under the workspace <dir>; prepare the worktree by hand.` otherwise). A main checkout with a profile keeps the shared or legacy layout.
- In a checkout without a profile, `init-dev-database` reads `[development]` from the workspace file and `lint-module` reads `[tooling].lint_rcfile` from it, resolved from the workspace file's directory like the other tooling paths. `gc` takes the slug of another worktree without a profile from its `oasis-checkout.toml` (else from the folder name), so the main checkout skips that worktree's namespace.

To convert the profiles of an existing project into one workspace file, see [Migrating to the workspace file](migrating.md).
