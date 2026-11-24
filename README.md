# oasis — portable Odoo 19 agent bundle

*Odoo Agent Skills & Infrastructure Scripts.* This repository is the source of the reusable global package installed at `~/.agents/skills/odoo19`, **not a seventh skill** and not a project staging directory. Contributor rules are in `AGENTS.md` in the source repository (not installed).

Built with Gentle Shell (`github.com/Gentleman-Programming/gentle-shell`).

oasis is an Odoo development harness: the guarded `oasis` CLI (with its `odoo19` alias), six
`odoo19-*` agent skills, and a thin Gentle Shell layer that wraps the CLI with compact,
token-saving output. It runs tests, databases and servers per checkout without letting an agent
bypass the database prefix guards.

## Install or update

Install the committed bundle into `~/.agents/skills/odoo19` from this repository, after the test
suite passes:

```bash
python3 -B -m unittest discover -s tests
./install.sh
```

Then install the Gentle Shell layer from a release tag (see the [changelog](CHANGELOG.md)) and
`/reload` open sessions:

```bash
gentle-shell install git:github.com/skhol3/oasis@v0.11.0
```

[Docs →](docs/install.md) · [Gentle Shell package →](docs/gentle-shell-layer.md#installing-the-package)

## Five-minute start

1. Describe the project in one `oasis-workspace.toml` for every checkout, step by step in
   [Setting up a new workspace](docs/new-workspace.md) ([workspace file](docs/workspace-file.md)),
   or in a legacy `.odoo19-agent.toml` profile ([new project setup](docs/project-setup.md)).
2. Check that oasis can work there, then that the environment matches its locks:

   ```bash
   ~/.agents/skills/odoo19/oasis --project /absolute/project doctor
   ~/.agents/skills/odoo19/oasis --project /absolute/project check-environment --quick
   ```

3. Run a module's tests on a disposable database, with a compact summary:

   ```bash
   ~/.agents/skills/odoo19/oasis --project /absolute/project test-module --compact your_module
   ```

4. In Gentle Shell, run `/oasis` for the checkout's status, `/oasis setup` once for the subagent
   overlay, and `alt+o` for the action menu.

## Features

### Gentle Shell layer and agent tools

Agent tools (`oasis_test_module`, `oasis_update_module`, `oasis_model_info`, ...) with validated
parameters and compact output, prompt context, the `/oasis` command and a bash guard that keeps
the agent away from direct `odoo-bin`, `dropdb`, `psql` and the user-run commands.
[Docs →](docs/gentle-shell-layer.md)

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

`doctor` and `check-environment` check the environment; one
[`oasis-workspace.toml`](docs/workspace-file.md) can replace the profile of every checkout, and
[`oasis migrate`](docs/migrating.md) converts existing profiles.
[Docs →](docs/checking-environment.md)

## Documentation

| Documentation | Purpose |
| --- | --- |
| [docs/README.md](docs/README.md) | Index of the documentation by reader |
| [Install or update](docs/install.md) | `install.sh`, release tags and what gets installed |
| [Gentle Shell layer](docs/gentle-shell-layer.md) | The agent tools, prompt context, `/oasis` and aliases |
| [Bash guard](docs/bash-guard.md) | Which agent bash commands run, wait for the user's confirmation or are blocked; `agent_destructive` |
| [Subagents](docs/subagents.md) | The overlay that gives subagents the `oasis_*` tools |
| [Setting up a new workspace](docs/new-workspace.md) | From an empty folder to `doctor`, a database and a test run; example tree and paths |
| [New project setup](docs/project-setup.md) | Workspace file or profile, entry point and optional project wrappers |
| [Checking the environment](docs/checking-environment.md) | `doctor`, `check-environment` and `lock.sha256` |
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
