# oasis — portable Odoo 19 agent bundle

*Odoo Agent Skills & Infrastructure Scripts.* This repository is the source of the reusable global package installed at `~/.agents/skills/odoo19`, **not a seventh skill** and not a project staging directory. Contributor rules are in `AGENTS.md` in the source repository (not installed).

Built with Gentle Shell (`github.com/Gentleman-Programming/gentle-shell`).

## Install or update

Releases follow Semantic Versioning and are tagged `vX.Y.Z`; see the [changelog](CHANGELOG.md). Install a released version of the Gentle Shell layer with `gentle-shell install git:github.com/skhol3/oasis@v0.1.0`.

With owner authorization, commit the change, run the test suite, then run `install.sh` from this repository:

```bash
python3 -B -m unittest discover -s tests
./install.sh                                  # installs HEAD into ~/.agents/skills/odoo19
./install.sh --target /absolute/scratch/odoo19 # try it somewhere else first
```

The installer copies the committed HEAD only (uncommitted edits are never installed), drops repository-only files (`AGENTS.md`, `.gitignore`, `install.sh`), records the installed version (from `package.json`) and commit in `.oasis-install.json`, and moves the previous install to `${XDG_STATE_HOME:-~/.local/state}/oasis/backups/`, outside any skill discovery directory. `OASIS_STATE_DIR` overrides that state directory.

The installed package contains the six `odoo19-*` directories, `tools/`, `project-wrappers/`, `tests/`, `docs/`, the `oasis` entry point (and its `odoo19` alias), the Gentle Shell layer (`package.json` and `pi/`), and this README. Restart the agent session or use `/reload` where supported, then check that exactly six skills are discovered. The skill entrypoints are [backend](odoo19-backend/SKILL.md), [security](odoo19-security/SKILL.md), [views/frontend](odoo19-views-frontend/SKILL.md), [testing](odoo19-testing/SKILL.md), [environment](odoo19-environment/SKILL.md), and [module lifecycle](odoo19-module-lifecycle/SKILL.md). See the [project capability contract](odoo19-environment/references/project-contract.md).

## Gentle Shell layer

A thin Pi package (`package.json`, `pi/`) layered over Gentle Shell. It changes nothing in Gentle Shell or Pi; its goal is fewer tokens in Odoo work by wrapping the guarded `oasis` core with compact output. Install it from a local checkout or from the repository:

```bash
gentle-shell install /absolute/path/to/oasis
gentle-shell install git:github.com/skhol3/oasis
```

Skills still come from `./install.sh` into `~/.agents/skills`, which Gentle Shell and Pi already scan. The layer adds:

- Tools `oasis_test_module`, `oasis_module_status`, `oasis_check_environment` and `oasis_lint_module` with validated parameters. Test runs return the result line and failures with the end of each traceback; full logs stay under the project's `dev/logs/odoo19/`, or `<logs>/odoo19/<main|slug>/` with `[tooling].logs`. Other output is capped at 60 lines (head and tail kept). Test summaries also carry up to five `stats:` lines (tests, time, queries per module) and one `warnings:` line grouping repeated warnings by logger and message. They always end with a control line, `log: <lines> lines, <errors> errors, <warnings> warnings`, counted over the full stdout and stderr logs and never capped: lines match `cat stdout.log stderr.log | wc -l`, errors are ERROR/CRITICAL lines except `odoo.tests.result`, and warnings are WARNING lines except `odoo.tests.*`, so the summary can be checked against the logs.
- Tool `oasis_find_module`: maps a functional name to technical module names by matching the query words against the technical name and the manifest `name`, `summary` and `category` in the profile's addon roots, so the agent needs no `ls` or `grep`.
- Tool `oasis_model_info`: wraps `oasis model-info` (model, optional field, module, methods, allFields) so the agent learns a model's fields, methods and inheritance without opening large Odoo source files; output is capped at 200 lines.
- Prompt context naming the `oasis_*` tools when `.odoo19-agent.toml` is found at or above the working directory, or, without one, an `oasis-workspace.toml` (see *Workspace file*; the project root is then the git top level of the working directory).
- A bash guard that blocks the agent's direct `odoo-bin`, `dropdb` and `psql` in Odoo projects and points to the guarded commands. In every session it also blocks the agent from running `worktree-init` (through `oasis` or `odoo19`, `tools/worktree-init` or `worktree_init.py`, `--dry-run` included), which only the user runs. It is a guard rail, not a sandbox: scripts, commands piped into a shell, `ssh`, `su -c` or `python3 -m odoo` are not caught. To bypass it, run the command yourself or disable the package.
- `/oasis`: a quick status with the profile, addon modules, configured databases, git worktree, checkout identity and this checkout's server (`server: running on port <port> (pid <pid>)` or `server: stopped`, read from the runtime record). It never starts services or queries databases. `/oasis setup` installs the subagent overlay (see Subagents). `/oasis doctor` shows the `oasis doctor` report (see *Checking the environment*); there is no agent tool for it. `/oasis worktree <feature> <branch>` creates a prepared linked worktree after confirmation (see *Preparing a linked worktree*).

The `oasis_*` tools are active only in sessions started inside an Odoo 19 project (a directory with `.odoo19-agent.toml` or `oasis-workspace.toml` at or above it), so other projects pay no tokens for them; `/oasis` is available everywhere.

Aliases from before 0.4.0: `/odoo19` runs the same command as `/oasis` (same subcommands), and each `oasis_*` tool is also registered as an `odoo19_*` alias with the same parameters and implementation. The aliases are never activated by the layer, so they cost no tokens; an overlay or allowlist that still names them keeps working, and `/oasis setup` reports such an overlay as outdated.

Other agents keep using the core (`oasis` CLI and skills) unchanged.

### Subagents

Gentle Shell subagents (for example `gentle-ai-worker` and `gentle-ai-verify`) receive only the tools in their allowlist, so they do not see the `oasis_*` tools by default. oasis ships an overlay template, [`pi/agent-overlays/oasis.json`](pi/agent-overlays/oasis.json), that adds the six tools to both agents. Run `/oasis setup` once in Gentle Shell (it asks before writing); oasis reminds you at session start when the overlay is missing or outdated.

- `/oasis setup` writes only `agent-overlays.d/oasis.json` under the Gentle AI config home (`$GENTLE_PI_CONFIG_HOME` when it is an absolute path, else `~/.gentle-shell/gentle-ai`). It works outside an Odoo project, does nothing when the overlay is already up to date, and only the user can run it: no agent tool triggers it. Start a new session or `/reload` afterwards.
- That folder is user configuration: Gentle Shell updates do not replace it. Run `/oasis setup` again after an oasis update that changes the template.
- If Gentle AI renames an agent, the overlay entry for the old name only produces a notice until an oasis update renames it.
- `oasis_test_module` runs each test on a new disposable database of the checkout's `<test_prefix>` namespace and drops it at the end (an explicit `database` or a configured `test_database` is reset and reused instead), so a verify subagent with the overlay can do so too. Its summary line then ends with `database_lifecycle=disposable dropped=<yes|no>`. There is no agent tool for `oasis gc`: removing leftovers is up to the user.
- Without the overlay, subagents can still run the core through bash: `python3 /absolute/path/to/oasis/oasis --project <project root> <command>` (for example `test-module --compact <module>`).

## New project: deliberate setup

1. Review the [example project profile](odoo19-environment/assets/odoo19-agent.example.toml) and the actual project's permissions and layout. Only with authorization, fill a **project-local** `.odoo19-agent.toml` with its real paths and namespace; do not copy test fixture values as defaults. The `[tooling]` table is the path and namespace authority for the [tools](tools/config.py); the optional `[development]` account declaration below is consumed only by `init-dev-database`. Other sections guide agents. Do not put credentials in the profile or inspect secret-bearing runtime files.
2. For direct invocation, install the bundle's `oasis` executable at `~/.agents/skills/odoo19/oasis` (owner makes it executable). `odoo19`, next to it, is a compatibility alias: the same dispatcher, with every command, option, exit code and output identical; only help and usage name the program invoked. Supply the absolute project directory explicitly; no project wrapper, PATH link, or shell configuration change is required. For example: `~/.agents/skills/odoo19/oasis --project /absolute/project check-environment --quick`. Run `~/.agents/skills/odoo19/oasis --help` without a project to see the fixed public commands. The entry point selects only packaged `tools/` commands; it does not replace the profile guards or grant operational consent.
3. Alternatively, if the project wants legacy local CLI entrypoints and explicitly authorizes them, review the 18 [project wrapper templates](project-wrappers/common.sh) and copy **only** the selected wrappers to its approved `dev/scripts/` directory. The tested templates derive the project root from that directory depth; another layout requires an explicitly validated adaptation. Do not overwrite existing scripts without separate approval. The wrappers locate global tools at `~/.agents/skills/odoo19/tools`; `ODOO19_TOOLS_DIR` is an explicit test/development override for wrappers, not a global entry point override. Missing installed tools fail clearly. Installing this package does not install wrappers into any project.
4. Keep project configuration, dependency inputs/locks, Compose files, environment variables, data, and runtime/virtualenv **local to the project**. This bundle does not create an environment, start services, install dependencies, access external source trees, or grant permission to operate on databases. `bootstrap --apply`, full diagnostics, and database lifecycle commands need separate explicit consent; no profile or skill discovery implies it.

## Checking the environment

Two commands, for two questions:

- `oasis --project /absolute/project doctor` asks *can oasis work here at all?* It checks the environment contract up front and is read-only: it never starts a service, never connects to a database and never prints file contents. In Gentle Shell, `/oasis doctor` (or `/odoo19 doctor`) shows the same report.
- `check-environment [--quick|--full]` asks *does the project environment match its locks?* It checks the requirement files and their fingerprint, the virtualenv, uv and `compose config`; `--full` also checks installed packages, audits dependencies and queries PostgreSQL.

`doctor` prints one `PASS|WARN|FAIL <check>[=<value>]` line per check, then `doctor_failures=<n>`, and exits 1 when `n > 0` (a `WARN` does not count), else 0. A check that needs another one is left out when that one failed.

| Check | Passes when | Otherwise |
| --- | --- | --- |
| `configuration` | the profile or workspace file loads; the value is `legacy` or `workspace` | `FAIL configuration=<error>`; the checks after `proc` are left out |
| `odoo_version` | always, when the configuration loads (only supported series load) | |
| `git` | `git --version` reports 2.31 or newer | `FAIL git=missing`, `FAIL git=<version> minimum=2.31` |
| `docker`, `docker_compose` | `docker` is on PATH and `docker compose version` succeeds | `FAIL docker=missing` (no `docker_compose` line), `FAIL docker_compose=unavailable` |
| `flock` | `flock` is on PATH | `WARN flock=missing`: the database service starts without the cross-checkout lock |
| `proc` | `/proc` is mounted | `WARN proc=missing`: server records cannot tell a live server |
| `python` | the environment's Python exists and reports the expected version (3.12, or the named environment's) | `FAIL python=missing`, `FAIL python=<found> expected=<version>` |
| `odoo_release` | `odoo/release.py` of the Odoo source declares `odoo_version` | `FAIL odoo_release=<found> expected=<version>` |
| `odoo_conf` | odoo.conf exists and parses | `FAIL odoo_conf=missing\|unreadable\|invalid`; in a workspace checkout, `WARN odoo_conf=addons_path,data_dir` (the options it still holds that oasis passes on the command line) |
| `compose` | the compose file declares a top-level `name:` | `FAIL compose=missing`, `FAIL compose=missing_top_level_name` |
| `env_file` | the env file exists (never opened) | `FAIL env_file=missing` |
| `logs_dir`, `data_dir` | the directory, or its nearest existing parent, is writable; `data_dir` only with `[tooling].data_dir` | `FAIL logs_dir=not_writable` |
| `http_port` | the port `start` would use is free, or is this checkout's running server (`server=this_checkout`) | `WARN http_port=<port> in_use` |

Tools are found on PATH, as `command -v` finds them, never through a tool manager; the only programs doctor runs are `git --version`, `docker compose version` and the environment's Python (for its version). A tool-manager shim on PATH can still install on first use (see *Tool-manager side effects*). No agent tool runs doctor.

## Workspace file

One `oasis-workspace.toml` at the project root can replace the profile of every checkout: checkouts and linked worktrees at any depth below it read the same file, so a worktree needs no profile copy. Review the [example workspace file](odoo19-environment/assets/oasis-workspace.example.toml).

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

- Discovery: the checkout root is the `--project` directory (in Gentle Shell, the git top level of the session directory, compared by real path, so a session directory reached through a symlink resolves to the checkout root). When it has no `.odoo19-agent.toml`, oasis walks up from it to the nearest `oasis-workspace.toml`, as git finds `.git`, up to the filesystem root. A directory with a `.odoo19-agent.toml` on the way ends the search. Without either file every command keeps the error `Missing tooling configuration: <checkout>/.odoo19-agent.toml`.
- Precedence: a checkout with its own `.odoo19-agent.toml` is read exactly as before and ignores the workspace file. Legacy profiles keep working; nothing has to move.
- Versions: the top level must set `workspace_version = 1` and `odoo_version = '19.0'`. Any other value stops every command with `Unsupported workspace_version <v> in <file>.` or `Unsupported odoo_version <v> in <file>; supported: 19.0.` (`<v>` in JSON form: strings in quotes, `(missing)` when absent). A file that is not valid TOML gives `Invalid TOML in <file>.`
- `[tooling]` takes the profile's keys and guards (prefixes, `test_database`, `logs`, `data_dir`, `enterprise`, and the advisory sections such as `[odoo].version`), except `version` and `python_version`: they derive from `odoo_version` (Python 3.12, or the selected named environment's `python`) and are refused when set (`[tooling].<key> is derived in a workspace; remove it from <file>.`). Every path resolves from the workspace file's directory, except `addons_paths`, which resolves from each checkout (`'.'` is the checkout itself), because the modules live in every checkout. The environment target keeps the profile rule: inside the checkout, or in a directory whose name ends in `environments`.
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

- Trust: a found `oasis-workspace.toml` or `oasis-checkout.toml` is read only when the file and its directory are owned by the current user or root and are not group- or other-writable (a symlinked file is also checked at its target); otherwise every command stops with `Refusing untrusted workspace file <file>: <path> is not owned by the current user or root.` or `Refusing untrusted workspace file <file>: <path> is writable by group or others.` Directories above the workspace's own (for example `/tmp`) are not checked. A legacy profile keeps its previous rules.
- `tools/config.py` emits the same assignments as for a profile, plus `WORKSPACE_ROOT` (the workspace directory, empty for a profile). After it, for a profile too, come `ODOO_VERSION`, `ODOO_SECOND_PORT_OPTION` and `ODOO_DEMO_OFF_ARGS` (the Odoo series and its options from `tools/odoo_versions.py`, the only file that writes version-specific Odoo options), `ENVIRONMENT_NAME` (the named environment, empty otherwise), `PYTHON_VERSION` and `DATA_DIR` (the resolved `[tooling].data_dir`, empty when absent). Checkout identity, slugs and database names are unchanged.
- Odoo series options: `start` passes the second server port with `ODOO_SECOND_PORT_OPTION` (`--gevent-port` on 19.0) and recognizes it when given; `test-module`, `install-module` (and so `verify-module`) and `init-dev-database` render the demo-off options from `ODOO_DEMO_OFF_ARGS`. On 19.0 the table keeps `--without-demo`, so every Odoo command line is unchanged.
- `worktree-init`, when the main checkout has no profile and finds a workspace file, only runs `git worktree add` and prints `workspace: <dir>` after the slug line: nothing is copied or linked. The new folder must be below the workspace directory (`The new worktree <path> would not be under the workspace <dir>; prepare the worktree by hand.` otherwise). A main checkout with a profile keeps the shared or legacy layout.
- In a checkout without a profile, `init-dev-database` reads `[development]` from the workspace file and `lint-module` reads `[tooling].lint_rcfile` from it, resolved from the workspace file's directory like the other tooling paths. `gc` takes the slug of another worktree without a profile from its `oasis-checkout.toml` (else from the folder name), so the main checkout skips that worktree's namespace.

## Lint one module without starting Odoo

Declare an existing trusted Pylint rcfile in the project's `.odoo19-agent.toml`:

```toml
[tooling]
# Keep the project's other required tooling values.
lint_rcfile = 'dev/lint/.pylintrc'
```

With authorization for the declared paths and installed plugins, run:

```bash
~/.agents/skills/odoo19/oasis --project /absolute/project lint-module your_module
```

The project Python must already provide Pylint and pylint-odoo supporting Odoo 19. The command selects the whole module from project-contained tooling addon roots, preserves rcfile rules/plugins, selects Odoo 19/Python 3.12 and disables bytecode/Pylint persistence. It returns raw analyzer stdout/stderr/status; it never installs dependencies, starts services, uses database credentials or automatically fixes warnings. Trusted rcfile hooks/plugins are not sandboxed. Relative rcfile paths resolve from the project root; external paths require explicit access consent. Missing lint config does not affect other commands. `lint-module --help` describes this contract; `verify-module` remains separate.

Run at a relevant baseline and after a Python/manifest work unit, not each edit. See [Pylint guidance and evidence reuse](odoo19-testing/references/pylint-odoo-guidance.md) alongside the independent [SonarQube policy](odoo19-testing/references/evidence-policy.md). Static analysis never replaces functional Odoo checks.


## Summarize a model without starting Odoo

```bash
~/.agents/skills/odoo19/oasis --project /absolute/project model-info mrp.production
~/.agents/skills/odoo19/oasis --project /absolute/project model-info mrp.production --field state
```

`model-info <model> [--field <name>] [--module <technical>] [--methods] [--all-fields]` prints a compact summary of one model: where it is defined (with `_inherit` mixins and `_inherits` delegations), the modules that extend it, its fields with type, comodel, label and literal flags, field overrides in extensions and methods per module. It scans the profile's Odoo source (`odoo/addons`, `addons`), optional Enterprise source and `[tooling].addons_paths`, prefilters files by the quoted model name and parses them with `ast`: no Odoo or project code is imported or executed, and no environment, service or database is used. Odoo/Enterprise `test_*` modules and `tests/`, `migrations/`, `upgrades/`, `static/` directories are skipped; mixin fields are not expanded. By default the field list stops at 40 (`--all-fields` lifts it) and methods list public names with a count of private ones; `--module` restricts the details to one module and lists all its methods, `--methods` adds decorators and `super()` calls, `--field` shows one field's definition and overrides with `file:line`. An unknown model exits 1 with `model not found: <model>`; invalid arguments exit 2. `model-info --help` describes the format.

## Fresh development database with role accounts

Use the global `init-dev-database` command for a **new, explicitly authorized development database**. By default it initializes Odoo without demo data, configures the administrator, installs one project module, and creates the project-declared role accounts. Pass `--with-demo` explicitly to use Odoo's native demo loader. `create-database` (empty PostgreSQL database), `install-module`, `update-module`, `start`, and test commands do not provision these users.

Declare non-secret accounts in the project's `.odoo19-agent.toml`:

```toml
[development]
administrator_login = 'local_admin'

[[development.users]]
login = 'planner'
name = 'Development Planner'
groups = ['your_module.group_planner']
```

Replace the example group with an actual installed `res.groups` XML ID. Additional `[[development.users]]` entries declare other roles; omit them when only the administrator is needed. Every role account receives `base.group_user` plus its declared groups, limited to the initial company. The module must define its roles outside demo data. Logins must be unique and names/groups nonempty; unknown keys, including credentials, are rejected.

From an interactive terminal, run the full executable path with the actual module and a fresh database name under the project's `[tooling].dev_prefix`:

```bash
~/.agents/skills/odoo19/oasis --project /absolute/project init-dev-database your_module project_dev_manual
```

### Optional native demo loading

```bash
~/.agents/skills/odoo19/oasis --project /absolute/project init-dev-database --with-demo your_module project_dev_training
```

This opts in to native Odoo demo loading for base, installed dependencies, and the selected module's manifest `demo` files. It does not generate product records or import custom scenario scripts. Demo data is module-owned; the global tool contains no customer catalog. Without the flag, no demo is loaded and optional demo environment modules are not installed.

When a project's native demo XML needs optional modules not declared as addon dependencies, declare them explicitly in the same `[development]` table:

```toml
[development]
administrator_login = 'local_admin'
demo_modules = ['purchase_stock']
```

`demo_modules` is optional and defaults to an empty list. Entries must be unique Odoo technical module names (letters, digits and underscores). Only with `--with-demo`, the tool installs them sequentially in declared order, using the native loader, before installing the selected module. This does not change any addon's `depends`, and does not broaden the selected project module roots. Odoo itself resolves the optional modules through its configured addon paths; a missing module or installation failure retains the new database and reports failure. The declaration is not permission to install modules or operate services. Choose native demo user logins that do not collide with configured manual accounts: account collisions are refused without overwriting them.

`--with-demo` remains restricted to fresh development databases. It cannot load demo into an existing database, enable it for tests, reset credentials, or modify previously created project data. No project configuration is automatically edited by this command.

### Credential entry and recovery

The command requests and confirms each password with terminal echo disabled. It refuses piped password entry, test/unmanaged databases, and existing databases; it never resets existing credentials. Passwords are not passed in arguments or environment variables, saved to files, or relayed in logs. Do not put them in the profile, shell commands, or chat. A failed setup retains the new database for inspection and reports a sanitized error; no automatic deletion or retry occurs. Base initialization, module installation, and account creation are separate phases; role accounts are created in one transaction. Tests continue to create their own actors independently.

Before modifying an installed bundle without a source checkout, make and validate a complete backup. Recover only affected files after preserving unrelated later edits; a reinstall may overwrite local changes. Fresh database initialization is not permission to modify an existing database.

## Reusable test destinations and compact evidence

Keep manual development data in a persistent development database. For sequential automated checks, optionally declare one reusable destination in the project's existing `[tooling]` table:

```toml
# Example only: use the project's actual test namespace.
test_database = 'sample_test_suite'
```

The name must be longer than `test_prefix`, contain only letters/digits/underscores, not end in the reserved run suffix `_r<6 hex>` (optionally `_update`; `test-module` and `verify-module` refuse it), and be at most 56 bytes (reserving `_update` within PostgreSQL's 63-byte identifier limit). Without this setting, each run uses its own disposable database (see *Disposable test databases* below). In a checkout with a slug the slug is inserted after `test_prefix` (see *Databases per checkout* below) and the 56 bytes include it. An explicit database argument overrides the test destination; it must still be an approved disposable test database.

After obtaining authorization to reset the exact destinations:

```bash
~/.agents/skills/odoo19/oasis --project /absolute/project test-module --compact your_module
~/.agents/skills/odoo19/oasis --project /absolute/project verify-module --compact your_module
```

| Command | Destinations and evidence |
| --- | --- |
| `test-module` | Resets the configured destination (or the explicit one), installs the module and runs its tests. Without either, it runs on a new disposable database. |
| `verify-module` | Uses that test destination and a separate `<destination>_update` for a fresh install followed by current-code update. With an explicit test destination and a configured one, its `_update` sibling is used; with only an explicit one, `<test_prefix><module>_update`; an explicit third argument overrides it. Without either, both are disposable: the run's database and its `_update` sibling. This does not prove historical migration. |
| `--compact` | Opt-in summaries preserve phase status and stdout/stderr log paths. Full streams remain in unique private directories under project `dev/logs/odoo19/` (with `[tooling].logs`, under `<logs>/odoo19/<main|slug>/`; see Preparing a linked worktree); without it, output remains unchanged. Inspect relevant failing log excerpts, not all successful logs. |

The Odoo test process also gets `--http-port=<free port>` and the Odoo series' second port option (`--gevent-port=<free port>` on 19.0, the port HttpCase tests use) right after the configuration options: two distinct ports the system hands out as free on 127.0.0.1 just before the run, so `test-module` and the tests phase of `verify-module` (with or without `--compact`) never collide with a running development server, even one with workers. The install and update phases and the rest of the command line are unchanged.

The Odoo **test process only** receives a fresh private (0700) short `/tmp/odoo19-test-*` directory as `TMPDIR`, independent of inherited nesting. The caller's environment, runtime probes, database guards, install and update invocations are unchanged. After the child exits, browser `chrome_logs` files and screenshots/videos remaining under its `odoo_tests` tree are copied privately (directories 0700, files 0600) into a unique directory under project `dev/logs/odoo19/` (or the `[tooling].logs` directory of the checkout), then only that invocation's scratch is removed. Browser profiles/cookies and evidence symlinks are not collected. No extra normal output is emitted; child stdout/stderr and exit status (including signal-derived status) are preserved, including through `--compact`. Retention or cleanup failure reports the owned scratch path for inspection and returns failure rather than claiming success; failed retention leaves scratch intact. SIGINT/SIGTERM are forwarded to the child before collection; uncatchable termination cannot guarantee collection or cleanup.

This does not change Odoo's skip classification: a successful exit can still include skipped browser tests. Inspect test results and retained diagnostics; the wrapper does not count tests or reinterpret skips. Retained diagnostics can contain application data and require deliberate owner-managed retention; no previous temporary directories or evidence are cleaned automatically.

Both commands support `--help`. Ensure `dev/logs/` (or a `[tooling].logs` directory inside the checkout) is ignored by project version control. Logs can contain application data; do not publish them or collect credentials. Run shared destinations (an explicit or configured database) **sequentially**: there is no execution scheduler or lock for them. Existing active sessions block reset, but that check is not a concurrency lock. Disposable databases are private to their run, so default runs may run in parallel. Use explicitly approved separate targets for retained baseline scenarios; do not invent explicit database names for every edit. Preserve failed-run evidence until investigation is complete: a disposable database is dropped at the end of its run, and a later reset overwrites a shared destination, even though prior logs remain.

The setting is **not reset consent** and does not create a database when read. Never reset the manual development database, infer approval from the namespace, or terminate sessions of a shared destination automatically; only a run's own disposable databases and `gc --apply` close sessions and drop databases. Existing databases are left untouched by installing this change. Template/profile changes require the normal authorization.

### Disposable test databases

Without an explicit database argument and without a configured `test_database`, `test-module` and the tests phase of `verify-module` use a new database for every run:

- Name: `<test_prefix><module>_r<6 hex>` (`<test_prefix><slug>_<module>_r<6 hex>` in a checkout with a slug), random per run. When it would exceed 56 bytes, the module part becomes its first characters plus `_` and the first 4 hex of the module name's SHA-256, so the name is at most 56 bytes and `verify-module`'s `<name>_update` sibling still fits in 63. A test prefix and slug that leave no room exit 2 before anything runs.
- Reserved names: a name ending in `_r` + 6 lowercase hex, optionally followed by `_update`, belongs to these runs. An explicit database argument or a configured `test_database` with such a name is refused with `Database names ending in _r<6 hex> are reserved for disposable runs: <name>` (exit 2, nothing runs) by `test-module`, `verify-module`, `create-database`, `install-module`, `update-module`, `odoo-shell`, `start -d`/`--database` and `init-dev-database`. `drop-database` and `module-status` accept them (cleanup and inspection), and so does `gc`. The phases of a disposable `verify-module` run use its names because that `verify-module` process holds their live run locks.
- Before the database exists, the run creates a lock `runs/<database>.json` (`pid`, `started_at`, `database`, `project_root`, `argv`; 0600) in the checkout's private runtime state directory (see *Servers and ports per checkout*). The lock is created exclusively (`O_EXCL` on its final path, then written and fsynced): when a lock of that name already exists, live or left by a killed run, the run exits 2 with `Disposable test database is locked: <name>` and touches neither that lock nor the database. A name that already exists as a database is refused (`Disposable test database already exists: <name>`, exit 2) and never touched. The database is then created; it becomes the run's own once `createdb` succeeded. When `createdb` fails, the run checks the name again: if the database exists now and no live run of the current user (in any checkout) holds another lock of that name, `createdb` created it before failing, so it is the run's own and is dropped like any other (`Cannot create disposable test database <name>; it was created anyway and is dropped.`); otherwise (for example the name was taken by another run in the meantime) the run reports `Cannot create disposable test database <name>; it was not dropped.`, drops nothing and removes only its own lock. Either way the run exits non-zero and no tests run. When `createdb` itself reports that the name already exists, the database was created by someone else and is never dropped; only a database that `createdb` created before failing for another reason is treated as the run's own. Otherwise the tests run exactly as for a shared destination, and at the end the run always closes the database's sessions, drops it, removes its filestore directory `<data_dir>/filestore/<database>` and removes the lock: after success, after failing tests, and after SIGINT (Ctrl+C) or SIGTERM. `<data_dir>` is `[tooling].data_dir` when it is set (see *Path-free odoo.conf*); otherwise `data_dir` is the only other option read from `odoo.conf` for this, and without an absolute `data_dir` the filestore step is skipped (Odoo's default data directory is not guessed). `gc --apply` removes filestores the same way.
- `tools/test_temp.py` owns this cleanup, because it already owns the signals: `test-module` execs it, so a SIGTERM to the `test-module` process or a Ctrl+C to its process group reaches it; it forwards the signal to Odoo and cleans up when Odoo has ended. `verify-module` takes the locks of both of its databases first (the same exclusive rule; while it takes and records each lock, SIGINT and SIGTERM are deferred and the lock helper runs with them ignored, so a signal then ends the run right after the lock is recorded and no lock is leaked), then checks that both names are free, and from then on drops both from an exit trap (before that, the trap removes only the locks it wrote); Bash runs that trap when the phase in progress returns, so a SIGTERM sent only to `verify-module` takes effect when that phase ends. SIGKILL or a lost machine cannot clean up: `oasis gc` finds what is left.
- With `--compact`, `test-module` runs the tests in a child process: a SIGTERM sent only to the outer process ends it without the summary, while the run still finishes and drops its database; a Ctrl+C reaches both.
- A database that cannot be dropped keeps its lock and is reported on stderr (`Cannot drop disposable test database <name>; run odoo19 gc --apply later.`); the run then exits non-zero.
- With `--compact`, the `test-module` summary gets one line after `phase=tests database=<name> exit=<n>`: `database_lifecycle=disposable dropped=<yes|no>`. It is the run's own cleanup result, which `tools/test_temp.py` writes to the file `database_lifecycle` of the run's log directory: `yes` means the run left no database behind (dropped, or never created, for example because the name was locked); `no` means the drop failed, or the run ended without reporting (killed). `verify-module --compact` prints the same line as its last line, from its own drops of both databases. Without `--compact` neither command prints it. Shared destinations print no such line.

### Cleaning up after interrupted runs

```bash
~/.agents/skills/odoo19/oasis --project /absolute/project gc            # list, change nothing
~/.agents/skills/odoo19/oasis --project /absolute/project gc --apply    # drop them
~/.agents/skills/odoo19/oasis --project /absolute/project gc --all-checkouts
```

`gc` lists the disposable test databases of this checkout's namespace that no live run holds, one `orphan <name>` line each, then `orphans=<n>`; it changes nothing. A run is live while the pid of its lock (in any checkout of the current user) still runs the command line recorded in the lock, so a reused pid does not keep an orphan alive (Linux `/proc`, like server records). With `--apply` it closes each orphan's sessions, drops it, removes its filestore and its stale lock, printing `dropped <name>`. An orphan whose drop fails prints `failed <name>` on stderr, keeps its filestore and lock, and the next orphan is still dropped. The run ends with `dropped=<n>` and `failed=<m>` and exits 1 when `m` is not 0, otherwise 0 (also when there is nothing to do).

- Namespace: a checkout with a slug owns `<test_prefix><slug>_...`; the main checkout (or a project outside git) owns `<test_prefix>...` except the namespaces of its existing linked worktrees (their slugs come from `git worktree list`: the worktree's `checkout_slug`, else the slug of its folder name). Leftovers of a worktree that no longer exists belong to the main checkout. Slugs still match as prefixes: a checkout skips the namespaces of other existing checkouts that start with its own (`wt` skips `wt_1_`).
- `--all-checkouts` lists every namespace of the test prefix. A checkout with a slug may drop only its own databases, so `--apply --all-checkouts` runs only in the main checkout (elsewhere it exits 2 before changing anything).
- Only names with the run suffix are candidates: development databases, test databases without it and the configured `test_database` (with its `_update` sibling) are never touched. Databases of another OS user's runs on the same PostgreSQL server have no visible lock; run `gc --apply` only for your own projects.
- A lock left by a run killed before its database existed has no database for `gc` to find, so it stays (its random name is never reused; locks live in the per-user runtime directory, usually cleared at logout or reboot).
- There is no project wrapper and no agent tool for `gc`; the bash guard does not block it.

## Checkout identity

Each checkout of a project gets an identity derived from the folder it runs in, so linked git worktrees (for example the ones Gentle Shell creates for sessions) can later get their own runtime resources. oasis keeps no registry: it runs a read-only `git rev-parse` in the project root and the same folder always gives the same identity.

- The main checkout has kind `main` and no slug. A project outside git has kind `none` and no slug.
- When git cannot report the checkout (not installed, a timeout after 5 s, a non-zero exit, unexpected output; git 2.31 or later is needed for `--path-format`), the reader looks for the first `.git` entry at or above the project root, as git does (ancestors in `GIT_CEILING_DIRECTORIES` are not entered). Without one, the project is outside git (kind `none`). A `.git` file (a linked worktree's gitfile) stops every command with `Cannot determine the checkout identity: git failed in a linked worktree; check git or set [tooling].checkout_slug.` (exit 2), so the worktree never loses its namespace guard; with `checkout_slug` set it continues as kind `linked` with that slug, but the main checkout is then unknown (`CHECKOUT_MAIN_ROOT` is empty): commands that start Odoo use an `odoo.conf` inside the worktree as it is and refuse a shared one (`Cannot move the addons_path of <path> to this worktree: git failed, so the main checkout is unknown.`), and compact logs cannot link into the main checkout. A `.git` directory stops every command with `Cannot determine the checkout identity: git failed (<reason>).`, whatever the profile sets.
- A linked worktree has kind `linked` and a slug from its directory name. When the name starts with the main checkout's directory name followed by `-`, `_` or `.`, that prefix is dropped. The rest is lowercased and every run of other characters than `a-z` and `0-9` becomes `_`, trimmed at both ends: `acme-shop-feature` next to `acme` gives `shop_feature`, `Feature Branch!` gives `feature_branch`.
- The slug must be 1-20 characters of `a-z`, `0-9` and `_`, starting with a letter or digit. When a name cannot produce one (empty or too long), the reader fails and asks for `[tooling].checkout_slug`.
- Optional `checkout_slug` in `[tooling]` overrides the slug for any checkout, including the main one (opt-in suffix); the reported kind stays the real one. An empty value is invalid: omit the key instead.

```toml
# Example only.
checkout_slug = 'mrp_2'
```

`/oasis` shows it as `checkout: main`, `checkout: linked worktree, slug shop_feature` or `checkout: main, slug mrp_2 (profile)`. The slug selects the checkout's database names (below); the checkout's directory selects its server and port (see *Servers and ports per checkout*).

## Databases per checkout

The slug goes right after the managed prefix, so each checkout has its own database namespace. A checkout without a slug (the main checkout, unless `checkout_slug` is set) keeps the previous names.

| Default | Main checkout | Checkout with slug `shop_feature` |
| --- | --- | --- |
| `install-module` target | `<dev_prefix><module>` | `<dev_prefix>shop_feature_<module>` |
| `test-module` and `verify-module` test target (disposable, new per run) | `<test_prefix><module>_r<6 hex>` | `<test_prefix>shop_feature_<module>_r<6 hex>` |
| `verify-module` update target (disposable) | `<test_prefix><module>_r<6 hex>_update` | `<test_prefix>shop_feature_<module>_r<6 hex>_update` |
| `verify-module` update target with only an explicit test database | `<test_prefix><module>_update` | `<test_prefix>shop_feature_<module>_update` |
| configured `test_database = '<test_prefix>shared'` | `<test_prefix>shared` | `<test_prefix>shop_feature_shared` (its sibling `<test_prefix>shop_feature_shared_update`) |

Every command that takes a database (`install-module` with or without `--with-demo`, `update-module`, `odoo-shell`, `start` with `-d`/`--database`, `test-module`, `verify-module`, `create-database`, `drop-database`, `module-status`, `init-dev-database`) requires a managed `<dev_prefix><name>` or `<test_prefix><name>` name; all of them except `drop-database` and `module-status` refuse names ending in the reserved disposable run suffix `_r<6 hex>` (see *Disposable test databases*). In a checkout with a slug the name must also start with `<dev_prefix><slug>_` or `<test_prefix><slug>_`, so a linked worktree cannot touch the main checkout's databases or another worktree's. The rejection names the checkout and the expected prefixes, and nothing runs.

Not guarded: `start` without `-d`/`--database` uses whatever `db_name` and `--db-filter` the project's `odoo.conf` sets, so keep `db_name` out of a linked worktree's `odoo.conf` and out of an `odoo.conf` shared by several checkouts. Slugs are matched as prefixes: give each worktree a slug that is not the start of another (`wt` would also accept `wt_1`'s databases).

Database names are at most 63 bytes (PostgreSQL's identifier limit, counted in UTF-8 bytes). A test database that gets an `_update` sibling in `verify-module` is at most 56 bytes, and a configured `test_database` must fit in 56 bytes after the slug is inserted. Longer names fail before any database command; disposable names are shortened to fit instead.

`update-module` and `odoo-shell` work on existing databases only: a missing database exits 2 with `Database <name> does not exist; create it with install-module or create-database.` and is never created. `install-module` and `create-database` still create their target. oasis never drops a checkout's databases on its own, except the disposable test databases a run created for itself (see *Disposable test databases*) and the orphans `gc --apply` drops when you run it.

### Preparing a linked worktree

Recommended: the shared layout. Keep the checkouts in one folder and the files they share next to it, so every checkout's profile points at the same configuration:

```text
<project>/codigo/<main checkout>          main checkout
<project>/codigo/<main checkout>-<feature> linked worktrees, siblings at the same depth
<project>/config/                          odoo.conf, environment file, compose file, requirements/
<project>/data/                            Odoo data directory (data_dir in the shared odoo.conf, or [tooling].data_dir)
```

```toml
# Example only: the profile of every checkout in that layout.
config = '../../config/odoo.conf'
env_file = '../../config/.env'
compose = '../../config/compose.yml'
requirements = '../../config/requirements'
logs = '../../logs'
```

With `logs`, compact runs (`--compact`) and the browser evidence of `test-module` go to `<project>/logs/odoo19/<checkout>/run-*`, where `<checkout>` is `main` for the main checkout and the slug for a linked worktree (`<project>/logs/odoo19/shop_feature/`), so the checkouts need no `dev/` directory at all. Missing directories are created private (0700). `logs` resolves from the checkout like the other paths, and a run directory that resolves outside it (for example `odoo19/<checkout>` as a symlink elsewhere) is refused with `Compact logs must remain inside the configured logs directory.` before anything is created. Without `logs`, runs stay under each checkout's `dev/logs/odoo19/` as before (see the end of this section).

The shared `odoo.conf` names the main checkout in its `addons_path`. In a linked worktree (`CHECKOUT_KIND=linked`), every command that starts Odoo (`test-module`, `verify-module`, `install-module`, `update-module`, `odoo-shell`, `start`, `init-dev-database`) reads only that option and passes it after `-c` as `--addons-path=<value>`, with each item that is the main checkout's root or lies inside it moved to the worktree's root (`<main>/vendor` becomes `<worktree>/vendor`); other items (Enterprise, OCA, the Odoo addons) stay as they are, in order. Nothing is added when no item names the main checkout, when there is no `addons_path`, or when the worktree's own `odoo.conf` already names the worktree. The main checkout and a project outside git keep their previous command line. An `odoo.conf` that cannot be parsed stops those commands with exit 2 before Odoo starts (`Cannot read addons_path from <path>: invalid configuration file.`); its content is never printed. `init-dev-database` checks it before asking for any password or starting the database service. An `odoo.conf` without `addons_path` needs no rewrite: see *Path-free odoo.conf*.

### Path-free odoo.conf

`odoo.conf` may leave out everything that depends on where the checkout lives; oasis passes it on the command line of every command that starts Odoo (`test-module`, `verify-module`, `install-module`, `update-module`, `odoo-shell`, `start`, `init-dev-database`, and project helpers that call `run_odoo`), right after `-c <odoo.conf>`:

- `--addons-path=<enterprise>,<addon roots>,<community>/addons` when `odoo.conf` has no `addons_path` in `[options]`: the `enterprise` source when configured, then every `[tooling].addons_paths` root of the checkout in order, then the Community `addons` directory. The main checkout and each linked worktree get their own roots, so nothing is rewritten, also when git fails in a linked worktree that sets `checkout_slug`. A root whose path contains a comma stops the command with `Cannot compose --addons-path: <path> contains a comma.` (exit 2). An `odoo.conf` that names `addons_path` keeps the behaviour above (the main checkout unchanged, a linked worktree rewritten).
- `--data-dir=<path>` when `[tooling].data_dir` is set (optional; in a profile it resolves from the checkout, in a workspace file from that file's directory; an empty or non-string value is refused with `Invalid tooling path: data_dir.`). The filestores of disposable runs and of `gc --apply` are then removed under that directory, and the `data_dir` of `odoo.conf` is not read. Without it nothing is added.
- Ports: `start` already chooses `--http-port` (and a linked worktree's second port); test runs and `start --stop-after-init` get two free ports (see *Reusable test destinations and compact evidence*).

Without `[tooling].data_dir` and with an `addons_path` in `odoo.conf`, every command line is unchanged.

`worktree-init` creates a linked worktree and prepares it. Run it yourself, in Gentle Shell or in a terminal, from the main checkout or any of its worktrees:

```text
/oasis worktree <feature> <branch>
```

```bash
~/.agents/skills/odoo19/oasis --project /absolute/project worktree-init <feature> <branch> [--dry-run] [--resume]
```

- The folder is `<main folder>-<feature>` next to the main checkout, so the feature becomes the checkout slug (`acme` with `shop feature` gives `acme-shop-feature`, slug `shop_feature`). An existing folder is refused, unless you pass `--resume` (below).
- An existing local branch is checked out; otherwise `origin/<branch>` is tracked when it exists; otherwise the branch is created from the main checkout's `HEAD`. A branch already checked out in another worktree is refused.
- An untracked `.odoo19-agent.toml` is copied (one that sets `checkout_slug` is refused, since the worktree would share its databases).
- Shared layout: when the profile's `config`, `env_file`, `compose` and `requirements` all resolve outside the checkouts, the profile is the only thing copied. Its relative paths, and `logs` when it is set, give the same files from the new sibling folder (checked before anything is created; otherwise it refuses). Nothing is linked, no `odoo.conf` is written and no `dev/` is created. The plan starts with `shared config: <directory of odoo.conf>`.
- Legacy layout (any of those four paths inside the checkout): every untracked or ignored entry of the main checkout's `dev/` is linked, except `dev/odoo.conf`, which is copied with mode 0600, the main root replaced by the worktree root in `addons_path` and `db_name` removed, and `dev/runtime`, which is created as a new empty 0700 directory. The `env_file` path is linked to the main checkout's file.
- Existing paths are never replaced. `--resume` accepts an existing folder only when it is a worktree of this repository with `<branch>` checked out. It then adds the missing items and reports the others as `kept existing <path>`. A plain folder, a symlink, another repository's worktree or a worktree on another branch is refused. Without the folder, `--resume` creates the worktree as usual.
- It prints the plan line by line (`copied`, `linked`, `created dir`, `rewrote addons_path`, `removed db_name`, `kept existing`) and never prints the content of `odoo.conf` or the environment file. `--dry-run` prints the same plan and changes nothing; `/oasis worktree` shows it and asks before creating anything. A failure after the worktree exists keeps what was created and reports it; run the terminal command again with `--resume` to finish it (`/oasis worktree` does not pass `--resume` yet).
- Agents cannot run it: the bash guard blocks it because it can link the environment file, which agents may not create or read.

Without `[tooling].logs`, `dev/logs` may stay a link to the main checkout's `dev/logs`: in a linked worktree, `--compact` runs accept a log directory that resolves inside the main checkout's `dev/logs/odoo19` (`CHECKOUT_MAIN_ROOT` from `tools/config.py`); any other location outside the project is still refused with `Compact logs must remain inside the project.`

## Servers and ports per checkout

Each checkout controls only its own Odoo server; the PostgreSQL service is one and shared.

- `start` runs at most one server per checkout and records its pid and HTTP port in `${XDG_RUNTIME_DIR:-/tmp}/oasis-<uid>/<16 hex of sha256(checkout path)>/server.json` (directories 0700, refused when they are symlinks or owned by another user; never inside the repository). Liveness reads `/proc`, so per-checkout servers work on Linux only: a record is live while its pid is a process of the current user whose command line is the Odoo launch (`<python> <odoo-bin> ...`, or `odoo-bin` itself as argv[0]); `<python>` is an interpreter whose name starts with `python` or the profile's `python` that `start` records in `server.json` (realpaths compared, so `pypy3` or a renamed venv binary works); for 10 s after `started_at` any process with that pid counts, because `start` writes the record just before it execs Odoo. A stale or invalid record is removed when read, only if the file still holds what was read. A second `start` while the server lives exits 2 with `Odoo is already running for this checkout: pid <pid>, port <port>.`
- Port: only `-p <port>`, `--http-port <port>` and `--http-port=<port>` are recognized as an explicit port (an abbreviation such as `--http-p` reaches Odoo unchecked and unrecorded); it is used as given (`Port <port> is in use; pass another --http-port or stop the other server.` when busy). Otherwise the main checkout, and a project outside git, use the `http_port` of `odoo.conf` (8069 when absent) and refuse a busy one with `Port <port> is in use; pass --http-port or stop the other server.`; a linked worktree takes the first free port from `http_port + 1` to `http_port + 50`, and also the first free `--gevent-port` after the conf's `gevent_port` (8072 when absent), so two servers with workers never collide. Only these options (and `http_interface`, the address probed) are read from `odoo.conf`. The chosen `--http-port=<port>` goes after the configuration options; a port the user passed is not repeated.
- A port that cannot be bound for another reason than being in use (for example a privileged port) exits 2 with `Cannot bind port <port>: <reason>.` (`permission denied`) before anything runs.
- Simultaneous `start` runs in different checkouts may probe the same free port before either binds it: start servers one at a time.
- Every command that needs the database runs `compose up -d --wait <db_service>` under an exclusive `flock` of `compose-<16 hex of sha256(real path of the compose file)>.lock` (0600) in `${XDG_RUNTIME_DIR:-/tmp}/oasis-<uid>/`, so checkouts that share a compose file start the service one at a time instead of failing with Docker's container name conflict; a command that waits more than 120 s for that lock exits 1 with `Timed out waiting for another checkout to start the database service.`, and without `flock` on `PATH` it prints `WARNING: flock not found; starting the database service without the cross-checkout lock.` and runs `compose up` unlocked.
- Before Odoo starts, `start` prints `odoo19 start: http://localhost:<port> (pid <pid>)` to stderr. `start --help`, `-h` and `--version` go straight to Odoo: no port check, no record.
- `start ... --stop-after-init` (for example `start --stop-after-init -u <module> -d <database>`) is a batch run that serves nothing: no running-server or port check, no record, no banner, and like test runs a free `--http-port=<port>` and a distinct free second port (`--gevent-port=<port>` on 19.0); an explicit port of either kind is passed as given, unchecked, and the other one is still added. It runs while this checkout's server serves; the database guards still apply.
- `stop` sends SIGTERM to this checkout's server, waits up to 20 s and reports `Stopped Odoo for this checkout: pid <pid>, port <port>.` (exit 1 when it does not stop in time); without a server it prints `No Odoo server running for this checkout.` and exits 0. It never stops another checkout's Odoo.
- `stop --database` stops the Compose database service (`compose stop <db_service>`) only when no other checkout has a live server; otherwise it exits 2 with `Refusing to stop the database: Odoo is running for other checkouts:` followed by one `  <checkout> (port <port>, pid <pid>)` line each.
- `status` prints `server: running pid <pid> port <port>` or `server: stopped` for this checkout (`server: unknown (<reason>)` when the runtime state cannot be read, for example a symlinked state directory; the reason is the last line the read wrote to stderr), then `compose ps`. Warnings of a successful read go to stderr unchanged and never into the server line. No temporary file is used, so a missing or non-writable `TMPDIR` does not stop it.

Contract change in 0.3.0: `stop` used to stop every Compose service; use `stop --database` for PostgreSQL.

Contract change in 0.3.0: `test-module` and `verify-module` without an explicit or configured test database used to reset and reuse `<test_prefix>[<slug>_]<module>` (and `..._update`); they now run on disposable databases dropped at the end of each run. Pass that name explicitly, or set `test_database`, to keep a reusable destination. Names ending in `_r<6 hex>` (optionally `_update`) are now reserved for disposable runs and refused by the commands that create or reuse a database. New public command: `gc`.

Contract change in 0.4.0: the entry point is `oasis`, the Gentle Shell tools are `oasis_*` and the command is `/oasis`. `odoo19` (identical commands, options, exit codes and output), `/odoo19` and the inactive `odoo19_*` tools stay as aliases; the install directory `~/.agents/skills/odoo19` and the `odoo19-*` skill names are unchanged. Run `/oasis setup` to move the subagent overlay to the `oasis_*` names.

## Portable verification

From any working directory, run `python3 -B -m unittest discover -s <absolute-path-to-global-odoo19>/tests -v`. These fixture tests use isolated synthetic projects and fake tools under the bundle-local `tests/fixturesroot`, which they remove after each test. [Fixture profile](tests/fixture-profile.toml) is test-only, not a project default. The suite requires no customer project checkout, original staging trees, historical baseline, differential reports, or archive. Historical project-specific evidence belongs in a separately verified compressed archive, not in this runtime package. Passing fixture tests does not authorize actual environment or database operations.

## Tool-manager side effects

Before diagnostics, account for executable shims managed by tools such as mise. A version probe such as `uv --version` can trigger a tool-manager download/install before uv starts; `UV_OFFLINE=1` does not constrain mise. Do not call such a probe as strictly read-only unless the underlying executable is already available without automatic installation, or the exact tool-manager action has separate human authorization. The project cleanup verification encountered mise installing uv 0.13.7 this way; no automatic rollback was attempted. This also applies to `check-environment --quick` through the global entry point.
