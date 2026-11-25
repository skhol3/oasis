# Gentle Shell layer

A thin Pi package (`package.json`, `pi/`) layered over Gentle Shell. It changes nothing in Gentle Shell or Pi; its goal is fewer tokens in Odoo work by wrapping the guarded `oasis` core with compact output.

## Installing the package

Install it from a release tag (`<tag>`, for example `v0.13.0`; see the [changelog](../CHANGELOG.md)), so the sessions load a fixed copy that work in a local checkout cannot change, then `/reload` open sessions:

```bash
gentle-shell install git:github.com/skhol3/oasis@<tag>
```

To move to another release, remove the installed entry and install the new tag (`gentle-shell list` shows the installed entry), then `/reload` open sessions:

```bash
gentle-shell remove git:github.com/skhol3/oasis@<installed tag>
gentle-shell install git:github.com/skhol3/oasis@<new tag>
```

Installing a local checkout (`gentle-shell install /absolute/path/to/oasis`) loads whatever that directory holds, including a branch under development; use it only to try changes.

## What the layer adds

The package does not bring the skills: they come from `./install.sh` into `~/.agents/skills`, which Gentle Shell already scans (see [Install or update](install.md)). The layer adds:

- [Test runs](#test-runs): `oasis_test_module`, `oasis_test_summary`, `oasis_module_status`,
  `oasis_check_environment` and `oasis_lint_module`.
- [Module updates](#module-updates): `oasis_update_module`.
- [Source inspection tools](#source-inspection-tools): `oasis_find_module`, `oasis_model_info`,
  `oasis_view_info`, `oasis_xmlid_info` and `oasis_module_info`.
- [Prompt context](#prompt-context).
- [Bash guard](bash-guard.md).
- [The /oasis command](#the-oasis-command).

### Test runs

Tools `oasis_test_module`, `oasis_module_status`, `oasis_check_environment` and `oasis_lint_module` with validated parameters. Test runs return the result line and failures with the end of each traceback; full logs stay under the project's `dev/logs/odoo19/`, or `<logs>/<main|slug>/` with `[tooling].logs`. Other output is capped at 60 lines (head and tail kept).

Test summaries also carry up to five `stats:` lines (tests, time, queries per module) and one `warnings:` line grouping repeated warnings by logger and message. They always end with a control line, `log: <lines> lines, <errors> errors, <warnings> warnings`, counted over the full stdout and stderr logs and never capped: lines match `cat stdout.log stderr.log | wc -l`, errors are ERROR/CRITICAL lines except `odoo.tests.result`, and warnings are WARNING lines except `odoo.tests.*`, so the summary can be checked against the logs.

While `oasis_test_module` runs it reports the elapsed time every 15 seconds.

For a suite that takes minutes, run `oasis --project <root> test-module --compact <module>` with the background shell tool and pass what it printed to `oasis_test_summary`, which returns the same summary and reads only the run logs that output names, and only inside this checkout's log locations (from `tools/config.py`): with `[tooling].logs`, `<logs>/<main|slug>/run-<id>/` and, for runs before 0.8.0, `<logs>/odoo19/<main|slug>/run-<id>/`; otherwise `dev/logs/odoo19/run-<id>/` of the checkout and, in a linked worktree, of the main checkout. Symlinks are followed before reading: the real path of each named log must keep that shape inside the real location (a checkout's `dev/logs/odoo19` must resolve inside the checkout or, for a linked worktree, to the main checkout's), so a linked run directory or log file that leads elsewhere is refused. Any other path, a missing log, `..` or a relative path is refused.

`oasis_test_module` takes `only` (`Class` or `Class.method`) to run one test class or one method of the module instead of all of them; when the filter matches nothing, Odoo still reports success, so the summary adds `no test matched only=<value>: check the class and method names`. With `reuse: true` it keeps the test database between runs (see [Reusing the test database while iterating](testing.md#reusing-the-test-database-while-iterating)); the first line then ends with `database_lifecycle=reused mode=<install|update>`.

### Module updates

Tool `oasis_update_module` (module, database): `oasis update-module --compact` on an existing managed database. It returns the exit code, the ERROR/CRITICAL entries with the end of each traceback, grouped warnings, the `log:` control line and the log paths; there is no test result line, since an update runs no tests.

### Source inspection tools

- Tool `oasis_find_module`: maps a functional name to technical module names by matching the query words against the technical name and the manifest `name`, `summary` and `category` in the workspace's addon roots, so the agent needs no `ls` or `grep`.
- Tool `oasis_model_info`: wraps `oasis model-info` (model, optional field, module, methods, allFields) so the agent learns a model's fields, methods and inheritance without opening large Odoo source files; output is capped at 200 lines.
- Tools `oasis_view_info` (model, optional type, module) and `oasis_xmlid_info` (id): wrap `oasis view-info` and `oasis xmlid-info` (see [Views and XML ids without starting Odoo](static-inspection.md#views-and-xml-ids-without-starting-odoo)), so the agent finds a model's views, what extends them and where an XML id is defined or referenced without opening or searching XML files; output is capped at 200 lines.
- Tool `oasis_module_info` (module, optional section): wraps `oasis module-info` (see [Module overview without starting Odoo](static-inspection.md#module-overview-without-starting-odoo)), so the agent sees a module's models, views, menus, actions, security, data files and tests without opening its files; output is capped at 200 lines.

See [Static inspection without starting Odoo](static-inspection.md) for the commands they wrap.

### Prompt context

Prompt context naming the `oasis_*` tools the session has (a session with none, such as a subagent without the overlay, is pointed to the `oasis` CLI instead) and the commands that ask the user first when an `oasis-workspace.toml` is found at or above the working directory (see [Workspace file](workspace-file.md); the project root is the git top level of the working directory). A checkout that still has the per-checkout file of earlier versions is detected too: its context says that file is no longer read and that the user migrates it (see [Migrating to the workspace file](migrating.md)), and every tool returns the refusal of `tools/config.py`.

### Bash guard

A bash guard blocks the agent from running some commands directly and asks the user, in a dialog, before the agent's `drop-database`, `stop --database` or `gc --apply --trash` run, and before the agent changes the workspace file that holds `[tooling].agent_destructive` (which can make them deny or allow); see [Bash guard](bash-guard.md).

### The /oasis command

- `/oasis`: a quick status with the configuration (or its error), addon modules, configured databases, git worktree, checkout identity and this checkout's server (`server: running on port <port> (pid <pid>)` or `server: stopped`, read from the runtime record). It never starts services or queries databases.
- `/oasis setup` installs the subagent overlay, which is for Gentle Shell only (see [Subagents](subagents.md)).
- `/oasis doctor` shows the `oasis doctor` report (see [Checking the environment](checking-environment.md)); there is no agent tool for it.
- `/oasis worktree <feature> <branch>` creates a linked worktree below the workspace file after confirmation (see [Preparing a linked worktree](checkouts-and-worktrees.md#preparing-a-linked-worktree)).
- `/oasis migrate` shows the `oasis migrate` plan and applies it after confirmation (see [Migrating to the workspace file](migrating.md)).
- `/oasis menu` (or `alt+o`) opens the action panel (see [Gentle Shell panel](action-menu.md#gentle-shell-panel) under [Action menu](action-menu.md)).
- Typing `/oasis ` offers its subcommands (`setup`, `doctor`, `migrate`, `worktree`, `menu`). Before the space, from two letters of the name (`/oa`, `/oasis`, `/od`, `/odoo`), the suggestions also list `/oasis <subcommand>` (and `/odoo19 <subcommand>`) with the same descriptions, right after the command itself; Tab inserts `/oasis <subcommand> `, Enter runs it at once (`/oasis worktree` still needs its two arguments). The layer adds them with `ctx.ui.addAutocompleteProvider` on top of the existing provider, once per session; every other completion is that provider's, unchanged.

## Activation and aliases

The `oasis_*` tools are active only in sessions started inside an Odoo project (a directory with `oasis-workspace.toml` at or above it), so other projects pay no tokens for them; `/oasis` is available everywhere.

Aliases from before 0.4.0: `/odoo19` runs the same command as `/oasis` (same subcommands), and each `oasis_*` tool is also registered as an `odoo19_*` alias with the same parameters and implementation. The aliases are never activated by the layer, so they cost no tokens; an overlay or allowlist that still names them keeps working, and `/oasis setup` reports such an overlay as outdated.

Other agents keep using the core (`oasis` CLI and skills) unchanged.

## Subagents

Subagents see the `oasis_*` tools only with the overlay; see [Subagents](subagents.md).
