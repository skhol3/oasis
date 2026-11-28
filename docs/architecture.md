# How oasis is built

oasis has one door: `oasis <command>`. The skills tell the agent to run it, the Gentle Shell package
(`pi/`: the `oasis_*` tools, `/oasis` and the action panel) runs it, and a person types it. The entry point
checks the command and the project, then runs `tools/<command>`. The bash guard exists only inside Gentle
Shell: it checks the agent's bash commands before they run. An agent in another harness and a person at a
terminal have no guard, so each Tier B script refuses to run without `--confirm <exact name>`.

This page describes the tree as of v0.21.0. The [Known growth problems](#known-growth-problems) are
follow-ups, not plans.

## Layers and call direction

```text
 person (terminal)        agent (skills odoo-*/SKILL.md)        Gentle Shell package (pi/)
        |                          |                       pi/extensions/oasis.ts
        |                          |                       ├─ oasis_* tools (11; Tier A commands only)
        |                          |                       ├─ /oasis [setup|doctor|worktree|menu]
        |                          |                       ├─ panel alt+o: pi/lib/panel.ts, menu.ts,
        |                          |                       │  ui/menu-panel.ts (catalog = `oasis menu --catalog`)
        |                          | agent bash  ────────► └─ guard on tool_call: destructive.ts
        |                          | (in Gentle Shell)           → bash-guard.ts → policy.ts
        |                          |                             → policy.generated.ts (tiers)
        v                          v                                    |
 ┌──────────────────────────────────────────────────────────────────────▼──────┐
 │ oasis (entry point, Python, the repository's root file)                     │
 │ 1. command in COMMANDS, else exit 2 `Unsupported oasis command`             │
 │ 2. project root: --project, else the git top level of the cwd               │
 │ 3. workspace file required, except setup, policy, status --json and doctor  │
 │    (not doctor --environment)                                               │
 │ 4. exec bash tools/<command> with OASIS_PROJECT_ROOT, OASIS_ENTRYPOINT      │
 └──────────────────────────────────────┬──────────────────────────────────────┘
                                        v
 tools/<command>  (29 bash files, found by file name)
   ├─ thin, 3-4 lines: exec python3 -I -B tools/<module>.py      (10 commands)
   └─ bash logic: source common.sh (→ oasis_env.sh, config.py),
      server_args.sh, compact.sh; then Python helpers         (19 commands)
                                        v
 tools/*.py helpers: config.py, runtime_state.py, db_account.py, ... (32 files)
                                        | read
                                        v
 configuration (table below)
                                        | run
                                        v
 runtime: docker compose (the PostgreSQL service; psql runs inside it),
          the project's Python environment, odoo-bin, uv (bootstrap, setup)

 off to the side
   install.sh: git archive of HEAD → ~/.agents/skills/oasis, without AGENTS.md, .gitignore,
               install.sh, odd/, tests/, pi/tests; writes .oasis-install.json (version, commit)
   recipes/<skill>/<recipe>.md → tools/render_recipes.py → odoo-*/references/<series>/<recipe>.md
               (rendered files are committed; the suite runs render_recipes.py --check)
```

| File | Where | Read by |
| --- | --- | --- |
| Machine `config.toml` | `$XDG_CONFIG_HOME/oasis/config.toml`, else `~/.config/oasis/config.toml` | `config.py` |
| `oasis-workspace.toml` | At or above the checkout (a linked worktree may use its main checkout's) | `config.py`; `pi/lib/project.ts` only finds it |
| `oasis-checkout.toml` | The checkout | `config.py` |
| Project `.env` | `[tooling].env_file` | `db_account.py`, docker compose |
| `odoo.conf` | `[tooling].config` | `odoo_addons_path.py`, `db_account.py`, Odoo |

`config.py` reads the three TOML files and resolves the paths of the others. It prints shell assignments,
which `common.sh` evaluates; Python tools load it as a module. See [Workspace file](workspace-file.md).

## Commands by job

From `COMMANDS` in the entry point. Every file is under `tools/`.

| Job | Command | Files |
| --- | --- | --- |
| Setup and environment | `setup` | `setup`, `setup.py` |
| | `bootstrap` | `bootstrap`, `locks.py`, `environment_origin.py`, `log_dirs.py`; ends by running `doctor --environment --full` |
| | `doctor` | `doctor`, `doctor.py`, `code_python.py`; `--environment`: `environment_checks.sh`, `check_environment.py`, `locks.py`, `audit-dependencies` |
| | `audit-dependencies` | `audit-dependencies`, `audit_dependencies.py` (run by the project's Python) |
| | `worktree-init` | `worktree-init`, `worktree_init.py` |
| Database | `setup-postgres` | `setup-postgres` (`compose up` of the service) |
| | `recreate-postgres-volume` | `recreate-postgres-volume`, `db_account.py` |
| | `create-database` | `create-database`; `--plan`: `database_plan.py`; creation: `dev_users.py`, `dev_users_runtime.py` (inside Odoo's Python) |
| | `drop-database` | `drop-database`, `trash.py` |
| | `list-databases` | `list-databases` (`common.sh` queries) |
| Server | `start` | `start`, `server_args.sh`, `compact.sh`, `runtime_state.py` |
| | `restart` | `restart`, `server_args.sh`, `runtime_state.py`, then `start --detach` |
| | `stop` | `stop`, `runtime_state.py` |
| | `status` | `status`, `runtime_state.py`; `--json`: `status_json.py` |
| | `odoo-shell` | `odoo-shell` (odoo-bin shell) |
| Modules and tests | `install-module` | `install-module`, `odoo_versions.py` |
| | `update-module` | `update-module`, `compact.sh` |
| | `module-status` | `module-status` |
| | `test-module` | `test-module`, `test_temp.py`, `compact.sh`, `odoo_versions.py` |
| | `verify-module` | `verify-module`, `test_temp.py`; runs `test-module`, `install-module`, `update-module`, `module-status` |
| | `lint-module` | `lint-module`, `lint_module.py` |
| Inspection (no Odoo started) | `model-info` | `model-info`, `model_info.py` |
| | `module-info` | `module-info`, `module_info.py` (loads `model_info.py`, `xml_info.py`) |
| | `view-info`, `xmlid-info` | `view-info`, `xmlid-info`, `xml_info.py` |
| Maintenance and interface | `gc` | `gc`, `gc.py`, `trash.py`, `test_temp.py` |
| | `trash` | `trash`, `trash.py` |
| | `policy` | `policy`, `policy.py` |
| | `menu` | `menu`, `actions.py` |

`recipe_evals.py`, `recipe_module.py` and `render_recipes.py` sit in `tools/` but no command runs them.
They are repository tools for the [release gate](release-gate.md) and the recipes.

## Shared modules

The users are the files that load, import, source or run the module. Comments don't count. Counted with
grep on the v0.21.0 tree.

| Module | Owns | Users |
| --- | --- | --- |
| `config.py` | The configuration: TOML files, series, checkout identity, git reading, missing-configuration messages | 16: the entry point, `common.sh`, `pi/extensions/oasis.ts` and 13 Python tools |
| `common.sh` | The shell runtime: config assignments, runtime checks, database name guards, psql in the service, disposable databases, `confirm_command` | 21: 19 command scripts, `environment_checks.sh`, `test_temp.py` |
| `runtime_state.py` | Server records, port probes, run locks, the compose lock, the menu's last action | 10: `common.sh`, `start`, `restart`, `stop`, `actions.py`, `doctor.py`, `gc.py`, `status_json.py`, `test_temp.py`, `pi/extensions/oasis.ts` |
| `odoo_addons_path.py` | The Odoo command-line options (`-c`, `--addons-path`, `--data-dir`) and odoo.conf reading | 8: `common.sh`, `server_args.sh`, `actions.py`, `dev_users.py`, `doctor.py`, `setup.py`, `test_temp.py`, `trash.py` |
| `db_account.py` | The database account in `.env` and odoo.conf, the probe, the compose project | 6: `common.sh`, `environment_checks.sh`, `recreate-postgres-volume`, `dev_users.py`, `doctor.py`, `setup.py` |
| `locks.py` | The dependency locks and `lock.sha256`, uv compile | 4: `bootstrap`, `environment_checks.sh`, `setup.py`, `status_json.py` |
| `trash.py` | Moving databases and filestores to the trash and back | 5: `drop-database`, `gc`, `trash`, `common.sh`, `status_json.py` |
| `test_temp.py` | Disposable test databases and their cleanup | 4: `test-module`, `verify-module`, `gc.py`, `trash.py` |
| `odoo_versions.py` | What each Odoo series supports (options, Python, capabilities) | 6 direct: `config.py`, `install-module`, `test-module`, `server_args.sh`, `recipe_evals.py`, `render_recipes.py` (the rest through `config.versions()`) |
| `siblings.py` | Loading a helper next to it by path (for `python3 -I`) | 13 Python tools |
| `server_args.sh` | Server arguments, ports, the databases a server may open | 2: `start`, `restart` |
| `compact.sh` | Run log directories and `server.log` (through `log_dirs.py`) | 6: `bootstrap`, `start`, `test-module`, `update-module`, `verify-module`, `test_temp.py` |
| `oasis_env.sh` | `OASIS_*` variables, `usage_name`, `program_name` | 11: `common.sh` and 10 command scripts (every bash tool through `common.sh`) |
| `environment_checks.sh` | The `doctor --environment` checks | 1: `doctor.py` (`bootstrap` reaches it through `tools/doctor`) |

## Policy: one table, three enforcers

| Piece | Role |
| --- | --- |
| `tools/policy.py` | `OPERATIONS`: each operation, its tier (A: the agent alone; B: a person confirms; C: a person only) and why; `CONFIRM`: what `--confirm` takes |
| `oasis policy --json` | The table for any agent or harness ([Agent contract](agent-contract.md)) |
| `pi/lib/policy.generated.ts` | Generated by `python3 -B tools/policy.py --typescript`; `tests/test_policy.py` fails when it drifts, when a `COMMANDS` entry has no row, and when the tables in [agent-contract.md](agent-contract.md) and [bash-guard.md](bash-guard.md) differ |

Who enforces it:

1. **The guard (Gentle Shell only).** `pi/extensions/oasis.ts` routes every `tool_call` to
   `destructive.ts` (`toolCallRouter`). `bash-guard.ts` (`classifyBash`) finds the programs and oasis
   commands in command position, and `policy.ts` (`operationOf`) maps each one to its row. Tier C is
   blocked (`odoo-bin`, `dropdb` and `psql` only in Odoo projects). Tier B, and an edit of a setting
   file, opens a dialog: the user types the database name (`drop-database`) or `yes` within 2 minutes.
   `[tooling].agent_destructive` = `deny` or `allow` replaces the dialog, but `allow` never covers a
   setting file. Details: [Bash guard](bash-guard.md).
2. **The scripts (everywhere).** A Tier B script refuses without `--confirm <exact name>`, changes
   nothing and prints the exact command to run. `common.sh` `confirm_command` builds that line. The
   check is in `drop-database`, `create-database`, `recreate-postgres-volume`, `gc` (`--apply --trash`)
   and `worktree_init.py`. `dev_users.py` checks it again for direct calls. `stop --database` has no
   `--confirm`: only a person or the dialog confirms it.
3. **The menu.** `tools/actions.py` asks the person to type the name or `yes` and then adds `--confirm`.
   `menu` is Tier C: agents run the commands it lists ([Action menu](action-menu.md)).

## How to add a command

On the current tree, one new command touches these places.

The suite fails until you change these 7:

- [ ] `tools/<command>`: a bash file. Add `tools/<module>.py` when the logic is Python.
- [ ] `COMMANDS` in `oasis`. Also `UNCONFIGURED_COMMANDS` when it runs without a workspace file.
- [ ] `PUBLIC` in `tests/test_global_cli.py`.
- [ ] A row in `OPERATIONS` in `tools/policy.py`. A Tier B row also needs a `CONFIRM` entry and the
      refusal in the script.
- [ ] `pi/lib/policy.generated.ts`: `python3 -B tools/policy.py --typescript`.
- [ ] The table in `docs/agent-contract.md`: `--markdown`.
- [ ] The table in `docs/bash-guard.md`: `--guard`.

By convention, 4 more:

- [ ] `tests/test_<command>.py`, with synthetic fixtures.
- [ ] A docs page and its row in [docs/README.md](README.md).
- [ ] The README.
- [ ] `CHANGELOG.md`.

Only when the command is in the menu or is an agent tool, up to 6 more:

- [ ] A menu action in `tools/actions.py`.
- [ ] An agent tool: `registerTool` in `pi/extensions/oasis.ts` (and an argument builder in
      `pi/lib/tools.ts`).
- [ ] The tool name in `OASIS_TOOLS` in `pi/lib/activation.ts`.
- [ ] The tool name in both lists of `pi/agent-overlays/oasis.json`.
- [ ] The tool name in `tests/test_pi_layer.py`.
- [ ] A special case in `bash-guard.ts`, when a Tier B helper can be run by its own file name (like
      `worktree_init.py`).

## Known growth problems

Follow-ups, one line each:

- **Loop:** `oasis menu` → `tools/actions.py` runs `oasis --project <root> <command>` again (`actions.py:403`, `:639`, `:658`).
- **Loop:** `common.sh` `list_checkout_databases` imports `trash.py` → `test_temp.py`, which runs `bash common.sh <function>` (`common.sh:384-405`, `test_temp.py:43-56`).
- **Round trip, not a cycle:** `doctor.py` → `environment_checks.sh` → `common.sh` → `config.py` again, then `locks.py` (`doctor.py:581`).
- **Tools call tools past the entry point:** `bootstrap:154` → `tools/doctor`, `verify-module:137-156` → 4 tools, `restart:138` → `start`, `environment_checks.sh:91` → `audit-dependencies`, `database_plan.py:227` → `create-database`.
- **Side doors:** `pi/extensions/oasis.ts` runs `tools/config.py` and `tools/runtime_state.py` directly (`CONFIG_PY`, `RUNTIME_STATE_PY`) for the status, the test summary, `agent_destructive` and the panel.
- **Too many jobs:** `tools/setup.py` (2500 lines), `tools/runtime_state.py` (1123), `tools/config.py` (1030), `pi/lib/bash-guard.ts` (877), `pi/lib/menu.ts` (838), `tools/actions.py` (705), `pi/extensions/oasis.ts` (664), `tools/doctor.py` (642), `tools/common.sh` (548).
- **No rule for shell or Python:** 19 commands keep their logic in bash and 10 in Python. Some rules exist in both, like the database name guards in `common.sh` and their copy in `dev_users.py:135`.
- **Three ways to load a helper:** `siblings.load` (13 tools), plain `import config` under `python3 -B` (`gc.py`, `trash.py`, `test_temp.py`, `dev_users.py`) and `sys.path.insert` under `-I` (`status_json.py:31`, `database_plan.py:39`, `common.sh:390`). `siblings.py:3-5` says a tool never imports a helper.
- **`-I` or `-B` without a rule:** most helpers run as `python3 -I -B`, but `config.py` (`common.sh:12`), `trash.py`, `gc.py`, `test_temp.py` and `dev_users.py` run as `python3 -B`.
- **`oasis_*` tools written by hand:** 11 names in `pi/extensions/oasis.ts`, `pi/lib/activation.ts`, `pi/agent-overlays/oasis.json` (twice) and `tests/test_pi_layer.py`. None comes from `COMMANDS` or the policy table.
- **Command list copied:** `COMMANDS` in `oasis` and `PUBLIC` in `tests/test_global_cli.py`.
- **Usage lines without the command:** `usage_name()` (`tools/oasis_env.sh:13`) prints the path of the entry point. So `verify-module`, `drop-database`, `stop` and 9 more bash tools print `Usage: /…/oasis <module> …`. `gc`, `restart`, `trash` and the Python tools add the command;
  `install-module` and `create-database` print the bare command name instead.
