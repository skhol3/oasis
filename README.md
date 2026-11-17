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

The installed package contains the six `odoo19-*` directories, `tools/`, `project-wrappers/`, `tests/`, `docs/`, the `odoo19` entry point, the Gentle Shell layer (`package.json` and `pi/`), and this README. Restart the agent session or use `/reload` where supported, then check that exactly six skills are discovered. The skill entrypoints are [backend](odoo19-backend/SKILL.md), [security](odoo19-security/SKILL.md), [views/frontend](odoo19-views-frontend/SKILL.md), [testing](odoo19-testing/SKILL.md), [environment](odoo19-environment/SKILL.md), and [module lifecycle](odoo19-module-lifecycle/SKILL.md). See the [project capability contract](odoo19-environment/references/project-contract.md).

## Gentle Shell layer

A thin Pi package (`package.json`, `pi/`) layered over Gentle Shell. It changes nothing in Gentle Shell or Pi; its goal is fewer tokens in Odoo work by wrapping the guarded `odoo19` core with compact output. Install it from a local checkout or from the repository:

```bash
gentle-shell install /absolute/path/to/oasis
gentle-shell install git:github.com/skhol3/oasis
```

Skills still come from `./install.sh` into `~/.agents/skills`, which Gentle Shell and Pi already scan. The layer adds:

- Tools `odoo19_test_module`, `odoo19_module_status`, `odoo19_check_environment` and `odoo19_lint_module` with validated parameters. Test runs return the result line and failures with the end of each traceback; full logs stay under the project's `dev/logs/odoo19/`. Other output is capped at 60 lines (head and tail kept). Test summaries also carry up to five `stats:` lines (tests, time, queries per module) and one `warnings:` line grouping repeated warnings by logger and message.
- Tool `odoo19_find_module`: maps a functional name to technical module names by matching the query words against the technical name and the manifest `name`, `summary` and `category` in the profile's addon roots, so the agent needs no `ls` or `grep`.
- Tool `odoo19_model_info`: wraps `odoo19 model-info` (model, optional field, module, methods, allFields) so the agent learns a model's fields, methods and inheritance without opening large Odoo source files; output is capped at 200 lines.
- Prompt context naming the `odoo19` tools when `.odoo19-agent.toml` is found at or above the working directory.
- A bash guard that blocks the agent's direct `odoo-bin`, `dropdb` and `psql` in Odoo projects and points to the guarded commands. It is a guard rail, not a sandbox: scripts, commands piped into a shell, `ssh`, `su -c` or `python3 -m odoo` are not caught. To bypass it, run the command yourself or disable the package.
- `/odoo19`: a quick status with the profile, addon modules, configured databases, git worktree and checkout identity. It never starts services or queries databases.

Other agents keep using the core (`odoo19` CLI and skills) unchanged.

### Subagents

Gentle Shell subagents (for example `gentle-ai-worker` and `gentle-ai-verify`) receive only the tools in their allowlist, so they do not see the `odoo19_*` tools by default. oasis ships an overlay template, [`pi/agent-overlays/oasis.json`](pi/agent-overlays/oasis.json), that adds the six tools to both agents. Copy it once:

```bash
mkdir -p ~/.gentle-shell/gentle-ai/agent-overlays.d
cp /absolute/path/to/oasis/pi/agent-overlays/oasis.json ~/.gentle-shell/gentle-ai/agent-overlays.d/oasis.json
```

- That folder is user configuration: Gentle Shell updates do not replace it. Copy the template again after an oasis update that changes it.
- If Gentle AI renames an agent, the overlay entry for the old name only produces a notice; update the agent name in your copy.
- `odoo19_test_module` resets the module's test database (the checkout's `<test_prefix>` namespace) before each run, so a verify subagent with the overlay can do so too.
- Without the overlay, subagents can still run the core through bash: `python3 /absolute/path/to/oasis/odoo19 --project <project root> <command>` (for example `test-module --compact <module>`).

## New project: deliberate setup

1. Review the [example project profile](odoo19-environment/assets/odoo19-agent.example.toml) and the actual project's permissions and layout. Only with authorization, fill a **project-local** `.odoo19-agent.toml` with its real paths and namespace; do not copy test fixture values as defaults. The `[tooling]` table is the path and namespace authority for the [tools](tools/config.py); the optional `[development]` account declaration below is consumed only by `init-dev-database`. Other sections guide agents. Do not put credentials in the profile or inspect secret-bearing runtime files.
2. For direct invocation, install the bundle's `odoo19` executable at `~/.agents/skills/odoo19/odoo19` (owner makes it executable). Supply the absolute project directory explicitly; no project wrapper, PATH link, or shell configuration change is required. For example: `~/.agents/skills/odoo19/odoo19 --project /absolute/project check-environment --quick`. Run `~/.agents/skills/odoo19/odoo19 --help` without a project to see the fixed public commands. The entry point selects only packaged `tools/` commands; it does not replace the profile guards or grant operational consent.
3. Alternatively, if the project wants legacy local CLI entrypoints and explicitly authorizes them, review the 18 [project wrapper templates](project-wrappers/common.sh) and copy **only** the selected wrappers to its approved `dev/scripts/` directory. The tested templates derive the project root from that directory depth; another layout requires an explicitly validated adaptation. Do not overwrite existing scripts without separate approval. The wrappers locate global tools at `~/.agents/skills/odoo19/tools`; `ODOO19_TOOLS_DIR` is an explicit test/development override for wrappers, not a global entry point override. Missing installed tools fail clearly. Installing this package does not install wrappers into any project.
4. Keep project configuration, dependency inputs/locks, Compose files, environment variables, data, and runtime/virtualenv **local to the project**. This bundle does not create an environment, start services, install dependencies, access external source trees, or grant permission to operate on databases. `bootstrap --apply`, full diagnostics, and database lifecycle commands need separate explicit consent; no profile or skill discovery implies it.

## Lint one module without starting Odoo

Declare an existing trusted Pylint rcfile in the project's `.odoo19-agent.toml`:

```toml
[tooling]
# Keep the project's other required tooling values.
lint_rcfile = 'dev/lint/.pylintrc'
```

With authorization for the declared paths and installed plugins, run:

```bash
~/.agents/skills/odoo19/odoo19 --project /absolute/project lint-module your_module
```

The project Python must already provide Pylint and pylint-odoo supporting Odoo 19. The command selects the whole module from project-contained tooling addon roots, preserves rcfile rules/plugins, selects Odoo 19/Python 3.12 and disables bytecode/Pylint persistence. It returns raw analyzer stdout/stderr/status; it never installs dependencies, starts services, uses database credentials or automatically fixes warnings. Trusted rcfile hooks/plugins are not sandboxed. Relative rcfile paths resolve from the project root; external paths require explicit access consent. Missing lint config does not affect other commands. `lint-module --help` describes this contract; `verify-module` remains separate.

Run at a relevant baseline and after a Python/manifest work unit, not each edit. See [Pylint guidance and evidence reuse](odoo19-testing/references/pylint-odoo-guidance.md) alongside the independent [SonarQube policy](odoo19-testing/references/evidence-policy.md). Static analysis never replaces functional Odoo checks.


## Summarize a model without starting Odoo

```bash
~/.agents/skills/odoo19/odoo19 --project /absolute/project model-info mrp.production
~/.agents/skills/odoo19/odoo19 --project /absolute/project model-info mrp.production --field state
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
~/.agents/skills/odoo19/odoo19 --project /absolute/project init-dev-database your_module project_dev_manual
```

### Optional native demo loading

```bash
~/.agents/skills/odoo19/odoo19 --project /absolute/project init-dev-database --with-demo your_module project_dev_training
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

The name must be longer than `test_prefix`, contain only letters/digits/underscores, and be at most 56 bytes (reserving `_update` within PostgreSQL's 63-byte identifier limit). Without this setting, module-derived defaults apply. In a checkout with a slug the slug is inserted after `test_prefix` (see *Databases per checkout* below) and the 56 bytes include it. An explicit database argument overrides the test destination; it must still be an approved disposable test database.

After obtaining authorization to reset the exact destinations:

```bash
~/.agents/skills/odoo19/odoo19 --project /absolute/project test-module --compact your_module
~/.agents/skills/odoo19/odoo19 --project /absolute/project verify-module --compact your_module
```

| Command | Destinations and evidence |
| --- | --- |
| `test-module` | Resets the configured destination, installs the module and runs its tests. |
| `verify-module` | Uses that test destination and a separate `<destination>_update` for a fresh install followed by current-code update. With an explicit test destination, its `_update` sibling is used; an explicit third argument overrides it. Without the setting, legacy module-derived defaults remain. This does not prove historical migration. |
| `--compact` | Opt-in summaries preserve phase status and stdout/stderr log paths. Full streams remain in unique private directories under project `dev/logs/odoo19/`; without it, output remains unchanged. Inspect relevant failing log excerpts, not all successful logs. |

The Odoo **test process only** receives a fresh private (0700) short `/tmp/odoo19-test-*` directory as `TMPDIR`, independent of inherited nesting. The caller's environment, runtime probes, database guards, install and update invocations are unchanged. After the child exits, browser `chrome_logs` files and screenshots/videos remaining under its `odoo_tests` tree are copied privately (directories 0700, files 0600) into a unique directory under project `dev/logs/odoo19/`, then only that invocation's scratch is removed. Browser profiles/cookies and evidence symlinks are not collected. No extra normal output is emitted; child stdout/stderr and exit status (including signal-derived status) are preserved, including through `--compact`. Retention or cleanup failure reports the owned scratch path for inspection and returns failure rather than claiming success; failed retention leaves scratch intact. SIGINT/SIGTERM are forwarded to the child before collection; uncatchable termination cannot guarantee collection or cleanup.

This does not change Odoo's skip classification: a successful exit can still include skipped browser tests. Inspect test results and retained diagnostics; the wrapper does not count tests or reinterpret skips. Retained diagnostics can contain application data and require deliberate owner-managed retention; no previous temporary directories or evidence are cleaned automatically.

Both commands support `--help`. Ensure `dev/logs/` is ignored by project version control. Logs can contain application data; do not publish them or collect credentials. Run shared destinations **sequentially**: there is no execution scheduler or lock. Existing active sessions block reset, but that check is not a concurrency lock. Use explicitly approved separate targets for parallel jobs or retained baseline scenarios. Do not invent a new database name for every edit. Preserve failed-run evidence until investigation is complete; a later reset overwrites database state even though prior logs remain.

The setting is **not reset consent** and does not create a database when read. Never reset the manual development database, infer approval from the namespace, terminate sessions automatically, or clean up other databases. Existing databases are left untouched by installing this change. Template/profile changes require the normal authorization.

## Checkout identity

Each checkout of a project gets an identity derived from the folder it runs in, so linked git worktrees (for example the ones Gentle Shell creates for sessions) can later get their own runtime resources. oasis keeps no registry: it runs a read-only `git rev-parse` in the project root and the same folder always gives the same identity.

- The main checkout has kind `main` and no slug. A project outside git has kind `none` and no slug.
- A linked worktree has kind `linked` and a slug from its directory name. When the name starts with the main checkout's directory name followed by `-`, `_` or `.`, that prefix is dropped. The rest is lowercased and every run of other characters than `a-z` and `0-9` becomes `_`, trimmed at both ends: `corpus-cafe-07.1` next to `corpus-cafe` gives `07_1`, `Feature Branch!` gives `feature_branch`.
- The slug must be 1-20 characters of `a-z`, `0-9` and `_`, starting with a letter or digit. When a name cannot produce one (empty or too long), the reader fails and asks for `[tooling].checkout_slug`.
- Optional `checkout_slug` in `[tooling]` overrides the slug for any checkout, including the main one (opt-in suffix); the reported kind stays the real one. An empty value is invalid: omit the key instead.

```toml
# Example only.
checkout_slug = 'mrp_2'
```

`/odoo19` shows it as `checkout: main`, `checkout: linked worktree, slug 07_1` or `checkout: main, slug mrp_2 (profile)`. The slug selects the checkout's database names (below); ports and processes are not per checkout yet.

## Databases per checkout

The slug goes right after the managed prefix, so each checkout has its own database namespace. A checkout without a slug (the main checkout, unless `checkout_slug` is set) keeps the previous names.

| Default | Main checkout | Checkout with slug `07_1` |
| --- | --- | --- |
| `install-module` target | `<dev_prefix><module>` | `<dev_prefix>07_1_<module>` |
| `test-module` and `verify-module` test target | `<test_prefix><module>` | `<test_prefix>07_1_<module>` |
| `verify-module` update target | `<test_prefix><module>_update` | `<test_prefix>07_1_<module>_update` |
| configured `test_database = '<test_prefix>shared'` | `<test_prefix>shared` | `<test_prefix>07_1_shared` (its sibling `<test_prefix>07_1_shared_update`) |

Every command that takes a database (`install-module` with or without `--with-demo`, `update-module`, `odoo-shell`, `start` with `-d`/`--database`, `test-module`, `verify-module`, `create-database`, `drop-database`, `module-status`, `init-dev-database`) requires a managed `<dev_prefix><name>` or `<test_prefix><name>` name. In a checkout with a slug the name must also start with `<dev_prefix><slug>_` or `<test_prefix><slug>_`, so a linked worktree cannot touch the main checkout's databases or another worktree's. The rejection names the checkout and the expected prefixes, and nothing runs.

Not guarded: `start` without `-d`/`--database` uses whatever `db_name` and `--db-filter` the project's `odoo.conf` sets, so keep `db_name` out of a linked worktree's `odoo.conf`. Slugs are matched as prefixes: give each worktree a slug that is not the start of another (`wt` would also accept `wt_1`'s databases).

Database names are at most 63 bytes (PostgreSQL's identifier limit, counted in UTF-8 bytes). A test database that gets an `_update` sibling in `verify-module` is at most 56 bytes, and a configured `test_database` must fit in 56 bytes after the slug is inserted. Longer names fail before any database command.

`update-module` and `odoo-shell` work on existing databases only: a missing database exits 2 with `Database <name> does not exist; create it with install-module or create-database.` and is never created. `install-module` and `create-database` still create their target. oasis never drops a checkout's databases on its own.

### Preparing a linked worktree

A linked worktree needs its own `.odoo19-agent.toml` profile and its own `dev/odoo.conf` whose `addons_path` points at the worktree's addons. It also needs the main checkout's environment file at the path the profile's `env_file` names. Agents are not allowed to create or read environment files, so the user creates that link once:

```bash
ln -s <main>/<env_file path> <worktree>/<env_file path>
```

`dev/logs` may stay a link to the main checkout's `dev/logs`: in a linked worktree, `--compact` runs accept a log directory that resolves inside the main checkout (`CHECKOUT_MAIN_ROOT` from `tools/config.py`); any other location outside the project is still refused with `Compact logs must remain inside the project.` A planned `worktree-init` (0.3.0) will prepare this.

## Portable verification

From any working directory, run `python3 -B -m unittest discover -s <absolute-path-to-global-odoo19>/tests -v`. These fixture tests use isolated synthetic projects and fake tools under the bundle-local `tests/fixturesroot`, which they remove after each test. [Fixture profile](tests/fixture-profile.toml) is test-only, not a project default. The suite requires no customer project checkout, original staging trees, historical baseline, differential reports, or archive. Historical project-specific evidence belongs in a separately verified compressed archive, not in this runtime package. Passing fixture tests does not authorize actual environment or database operations.

## Tool-manager side effects

Before diagnostics, account for executable shims managed by tools such as mise. A version probe such as `uv --version` can trigger a tool-manager download/install before uv starts; `UV_OFFLINE=1` does not constrain mise. Do not call such a probe as strictly read-only unless the underlying executable is already available without automatic installation, or the exact tool-manager action has separate human authorization. The project cleanup verification encountered mise installing uv 0.13.7 this way; no automatic rollback was attempted. This also applies to `check-environment --quick` through the global entry point.
