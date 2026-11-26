# oasis — Odoo development harness

oasis is an Odoo development harness for agents and the terminal: the guarded `oasis` CLI, six
agent skills, and a thin Gentle Shell layer that wraps the CLI with compact, token-saving
output. It runs tests, databases and servers per checkout without letting an agent bypass the
database prefix guards.

Odoo 19.0 is the supported series today; further series are added in
[`tools/odoo_versions.py`](tools/odoo_versions.py), the one table of what differs between them. The `odoo19` names (the install directory
`~/.agents/skills/odoo19`, the `odoo19-*` skills and the `odoo19` alias of `oasis`) stay as they
are until a second series is supported.

*Odoo Agent Skills & Infrastructure Scripts.* This repository is the source of the reusable global package installed at `~/.agents/skills/odoo19`, **not a seventh skill** and not a project staging directory. Contributor rules are in `AGENTS.md` in the source repository (not installed).

Built with Gentle Shell (`github.com/Gentleman-Programming/gentle-shell`).

## Install or update

Two installs, each with its own job. Install both to get everything.

| Install | What you get | Where it works |
| --- | --- | --- |
| `./install.sh` from this repository | The six `odoo19-*` skills and the `oasis` CLI (with its `odoo19` alias) in `~/.agents/skills/odoo19` | Any agent (Claude Code, Codex, Gentle Shell) and the terminal |
| The package from a release tag | The `oasis_*` agent tools, `/oasis`, the `alt+o` panel and the bash guard | Gentle Shell |

The package does not bring the skills; `install.sh` does not add the tools, `/oasis` or the panel
to Gentle Shell.

```bash
# Skills and CLI: from this repository, after the test suite passes
python3 -B -m unittest discover -s tests
./install.sh

# Gentle Shell package: <tag> is a release from the changelog, for example v0.14.0
gentle-shell install git:github.com/skhol3/oasis@<tag>
```

Then `/reload` open sessions. To move the package to another release, remove the installed tag
and install the new one ([Install or update](docs/install.md#moving-the-package-to-another-release)).
Releases are listed in the [changelog](CHANGELOG.md).

[Docs →](docs/install.md) · [Gentle Shell package →](docs/gentle-shell-layer.md#installing-the-package)

## Five-minute start

1. In a clone of the project, read the plan of `oasis setup`, then apply it yourself. It infers
   the series and the source, asks only what it cannot infer, keeps what exists and creates the
   rest: the workspace file, a path-free `odoo.conf`, a PostgreSQL compose file, the locks and the
   environment ([Setting up a new workspace](docs/new-workspace.md)):

   ```bash
   cd /absolute/checkout
   ~/.agents/skills/odoo19/oasis setup            # the plan; nothing changes
   ~/.agents/skills/odoo19/oasis setup --apply    # creates only what is missing
   ```

2. Start the database service and run `doctor` until `doctor_failures=0` (each `FAIL` says how to
   fix it). setup generated the database account in the environment file, which the service and
   Odoo both read; no step needs a password read, copied or typed
   ([The database account](docs/setup.md#the-database-account)):

   ```bash
   docker compose --env-file .oasis/config/.env -f .oasis/config/compose.yml up -d --wait
   ~/.agents/skills/odoo19/oasis doctor
   ```

3. Run a module's tests on a disposable database, with a compact summary:

   ```bash
   ~/.agents/skills/odoo19/oasis test-module --compact your_module
   ```

4. With the package, run `/oasis` for the checkout's status and `alt+o` for the action menu; in
   Gentle Shell, `/oasis setup` shows the status and the `oasis setup` plan and installs the subagent
   overlay.

## Features

### Gentle Shell layer and agent tools

Agent tools (`oasis_test_module`, `oasis_update_module`, `oasis_model_info`, ...) with validated
parameters and compact output, prompt context, the `/oasis` command and a bash guard that keeps
the agent away from direct `odoo-bin`, `dropdb`, `psql` and asks the user before Tier B commands.
[Docs →](docs/gentle-shell-layer.md)

### Agent contract

One policy table in the core (`tools/policy.py`, `oasis policy --json`) lists every
operation, its tier (A: the agent alone; B: the agent proposes, a person confirms; C: a person
only) and why; docs, skills and the bash guard follow it. [Docs →](docs/agent-contract.md)

Contract change in v0.16.0: the Gentle Shell guard takes its tiers from that table. Agents now run
`setup --apply`, `migrate` without `--apply` and `worktree-init --dry-run` (Tier A); `worktree-init`
and `migrate --apply` (Tier B) wait for the user's confirmation in a dialog, honoring
`[tooling].agent_destructive`, like `drop-database`, instead of being blocked; `gc --apply` is
Tier A in the skills too. In the CLI, `drop-database`, `gc --apply --trash`, `migrate --apply` and
`worktree-init` run only with `--confirm <exact name>` (the database, the project root, the
workspace file, the worktree path); without it they exit 2 and name the exact command. The menu,
`/oasis worktree` and `/oasis migrate` pass it after your confirmation. New Tier B command:
`recreate-database-volume --confirm <compose project>` runs `docker compose -p <compose project> down -v`
(the project's containers and networks, every named volume of its compose file and every anonymous
volume of its containers: every database of its PostgreSQL) and starts the service again with the
account of the env file; it replaces a raw `docker compose down -v`.

oasis generates the database account (`oasis setup`, one 0600 env file read by the compose service
and by Odoo; `odoo.conf` stays password-free), so no oasis workflow requires reading, copying or
typing a password, and no command takes or prints one. An existing project keeps its files: setup
fills an env file's empty account variables in place (never adds absent ones) and moves `db_user` and `db_password` out of `odoo.conf`
only when the env file holds the same values (otherwise it warns and changes nothing), and
`init-dev-database` generates the development passwords into `<database>.logins` (mode 0600) unless
you type your own on a terminal. [Docs →](docs/setup.md#the-database-account)

No command needs a terminal: `oasis setup --plan --json` prints the plan as one JSON object (what it
inferred and from where, the changes, the questions with their options, the recommended answer and the
flag that answers each), `--answer <id>=<value>` or `--answers <file.json>` answers them, and the plan
asks in advance about what would fail later (python-ldap 3.4.0 against OpenLDAP 2.6, module
requirements missing or conflicting with Odoo's pins; uv 0.13 gets `UV_LEGACY_TAR_BACKEND=1`). Without a
terminal an unanswered question is listed in the plan and `--apply` refuses, naming its flag.
`oasis status --json` says what is ready, what is missing and the next command to run (an oasis
command, or the `docker compose ... up -d --wait` that starts the database service).
[Docs →](docs/setup.md#questions-and-answers)

### Checkouts and worktrees

The main checkout and every linked worktree get their own database namespace, server, port and
logs; `worktree-init` prepares a new worktree. [Docs →](docs/checkouts-and-worktrees.md)

### Tests and databases

Disposable test databases dropped after each run, a reusable destination when you want one,
`--only` and `--reuse` while fixing a test, `gc` for what interrupted runs leave, and
[development databases with role accounts](docs/dev-database.md). [Docs →](docs/testing.md)

### Static inspection

`model-info`, `view-info`, `xmlid-info` and `module-info` map models, views, XML ids and modules
from source, and `lint-module` runs Pylint, all without starting Odoo.
[Docs →](docs/static-inspection.md)

### Action menu

`oasis menu` in a terminal, or the Gentle Shell panel (`alt+o`), lists the everyday operations
of a checkout and runs them by hand. [Docs →](docs/action-menu.md)

### Environment and workspace file

[`oasis setup`](docs/setup.md) configures a clone, `bootstrap` syncs its environment to the locks
([which one when](docs/setup.md#setup-bootstrap-or-migrate)), `doctor` and `doctor --environment` check the
environment; one [`oasis-workspace.toml`](docs/workspace-file.md) configures every checkout, and
the machine file gives the Odoo source of each series.
[Docs →](docs/checking-environment.md)

Contract change in v0.12.0: the legacy per-checkout profile `.odoo19-agent.toml` is no longer
read. A checkout that still has one is refused (exit 2) with
`<checkout>/.odoo19-agent.toml is the old profile format, no longer read: run oasis migrate --plan to see its conversion to oasis-workspace.toml, then oasis migrate --apply.`;
`doctor` reports it as one `FAIL configuration`. [`oasis migrate`](docs/migrating.md), the only
command that still reads it, converts the profiles of every checkout into one workspace file.

Contract note in v0.16.0 (S5): `check-environment [--quick|--full]` is a deprecated alias of
`doctor --environment [--quick|--full]`. Both names keep working through `oasis` and `odoo19`, the
project wrappers and the tool script, with the same lines, exit codes and usage line as before; the help of
`oasis`, `doctor --help` and the policy table (both Tier A) say so, and the `oasis_check_environment` tool runs
`doctor --environment`. `doctor`'s usage line now names the option: `Usage: <program> doctor
[--environment [--quick|--full]]`. setup, bootstrap and migrate stay three commands (none would be an
identical alias): [which one when](docs/setup.md#setup-bootstrap-or-migrate).

## Documentation

| Documentation | Purpose |
| --- | --- |
| [docs/README.md](docs/README.md) | Index of the documentation by reader |
| [Install or update](docs/install.md) | Which install does what: `install.sh` (skills and CLI) and the package (tools, `/oasis`, panel) |
| [Gentle Shell layer](docs/gentle-shell-layer.md) | The agent tools, prompt context, `/oasis` and aliases |
| [Agent contract](docs/agent-contract.md) | The policy table: each operation's tier (A, B, C) and why, as JSON for any agent |
| [Bash guard](docs/bash-guard.md) | Which agent bash commands run, wait for the user's confirmation or are blocked; `agent_destructive` |
| [Subagents](docs/subagents.md) | The overlay that gives Gentle Shell subagents the `oasis_*` tools |
| [Setting up a new workspace](docs/new-workspace.md) | From a clone to `doctor` and a database with `oasis setup`; where each value lives, an example tree, the steps by hand |
| [Setting up a checkout with oasis setup](docs/setup.md) | `oasis setup`: the plan, then `--apply` creates only what is missing |
| [New project setup](docs/project-setup.md) | Workspace file, entry point and optional project wrappers |
| [Checking the environment](docs/checking-environment.md) | `doctor`, `doctor --environment` (`check-environment`, a deprecated alias) and `lock.sha256` |
| [Workspace file](docs/workspace-file.md) | One `oasis-workspace.toml` for every checkout |
| [Migrating to the workspace file](docs/migrating.md) | `oasis migrate` |
| [Path-free odoo.conf](docs/path-free-odoo-conf.md) | What oasis passes on the Odoo command line |
| [Checkouts and worktrees](docs/checkouts-and-worktrees.md) | Checkout identity, databases per checkout, `worktree-init` |
| [Servers and ports](docs/servers-and-ports.md) | `start`, `stop`, `status` and ports per checkout |
| [Tests and test databases](docs/testing.md) | `test-module`, `verify-module`, `--only`, `--reuse` |
| [Disposable test databases](docs/disposable-test-databases.md) | Per-run databases and `gc` |
| [Database trash](docs/trash.md) | `drop-database` moves to the trash; `trash restore`, `gc --trash` |
| [Development database](docs/dev-database.md) | `init-dev-database` with role accounts and demo data |
| [Static inspection](docs/static-inspection.md) | `model-info`, `view-info`, `xmlid-info`, `module-info` |
| [Lint one module](docs/lint-module.md) | `lint-module` with the project's Pylint rcfile |
| [Action menu](docs/action-menu.md) | `oasis menu` and the Gentle Shell panel |
| [Portable verification](docs/verification.md) | Running the bundle's fixture tests |
| [Troubleshooting](docs/troubleshooting.md) | Tool-manager shims and known failures |
| [Changelog](CHANGELOG.md) | Releases and contract changes |
