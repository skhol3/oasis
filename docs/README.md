# oasis documentation

One topic per file. Start from the group that matches what you are doing; the
[project README](../README.md) gives the overview.

## New user

| Documentation | Purpose |
| --- | --- |
| [Install or update](install.md) | `install.sh`, release tags and what gets installed |
| [New project: deliberate setup](project-setup.md) | Profile, entry point and optional project wrappers |
| [Checking the environment](checking-environment.md) | `doctor`, `check-environment` and `lock.sha256` |
| [Workspace file](workspace-file.md) | One `oasis-workspace.toml` for every checkout |
| [Gentle Shell layer](gentle-shell-layer.md) | Installing the package, the agent tools and `/oasis` |

## Daily user

| Documentation | Purpose |
| --- | --- |
| [Action menu](action-menu.md) | `oasis menu` and the Gentle Shell panel (`alt+o`) |
| [Servers and ports per checkout](servers-and-ports.md) | `start`, `stop`, `status`, ports and the database service |
| [Tests and test databases](testing.md) | `test-module`, `verify-module`, `--only`, `--reuse` and compact evidence |
| [Disposable test databases](disposable-test-databases.md) | Per-run databases and `gc` after interrupted runs |
| [Database trash](trash.md) | `drop-database` moves to the trash; `trash`, `trash restore` and `gc --trash` |
| [Fresh development database with role accounts](dev-database.md) | `init-dev-database`, demo data and credentials |
| [Checkouts and worktrees](checkouts-and-worktrees.md) | Checkout identity, databases per checkout and `worktree-init` |
| [Path-free odoo.conf](path-free-odoo-conf.md) | `--addons-path` and `--data-dir` on the command line |
| [Migrating to the workspace file](migrating.md) | `oasis migrate` |
| [Troubleshooting](troubleshooting.md) | Tool-manager shims and known failures |

## Agent and skill author

| Documentation | Purpose |
| --- | --- |
| [Gentle Shell layer](gentle-shell-layer.md) | Agent tools, their output and the prompt context |
| [Bash guard](bash-guard.md) | Which agent bash commands run, wait for the user's confirmation or are blocked; `agent_destructive` |
| [Subagents](subagents.md) | The overlay that gives subagents the `oasis_*` tools |
| [Static inspection without starting Odoo](static-inspection.md) | `model-info`, `view-info`, `xmlid-info` and `module-info` |
| [Lint one module without starting Odoo](lint-module.md) | `lint-module` with the project's Pylint rcfile |
| [Project capability contract](../odoo19-environment/references/project-contract.md) | What the tools read from `[tooling]` |

## Contributor

| Documentation | Purpose |
| --- | --- |
| [Portable verification](verification.md) | Running the bundle's fixture tests |
| [Changelog](../CHANGELOG.md) | Releases and contract changes |
| [Headless Chromium socket path](odoo19-chromium-socket-path-too-long.md) | Incident note: browser tests and a long `TMPDIR` |

Contributor rules are in `AGENTS.md` in the source repository; it is not installed.
