# Install or update

oasis has two installs, each with its own job. Install both to get everything; neither brings what
the other does.

| Install | What you get | Where it works |
| --- | --- | --- |
| [`./install.sh`](#installing-the-skills-and-the-cli-with-installsh) from this repository | The six `odoo19-*` skills and the `oasis` CLI (with its `odoo19` alias) in `~/.agents/skills/odoo19` | Any agent (Claude Code, Codex, Gentle Shell) and the terminal |
| [The package](#installing-the-package) from a release tag | The `oasis_*` agent tools, `/oasis`, the `alt+o` panel and the bash guard | Gentle Shell |

- The package does not bring the skills: Gentle Shell finds them in `~/.agents/skills`,
  where `install.sh` puts them. It carries its own copy of the CLI for its tools; the
  `~/.agents/skills/odoo19/oasis` path that the skills and docs name comes from `install.sh`.
- `install.sh` copies the package files too, but does not add the tools, `/oasis` or the panel to
  Gentle Shell; only the package install does.
- The `odoo19` names (install directory, skills, CLI alias) stay as they are until a second Odoo
  series is supported; 19.0 is the only one today.

## Released versions

Releases follow Semantic Versioning and are tagged `vX.Y.Z`; the [changelog](../CHANGELOG.md)
lists them. Below, `<tag>` is one of those tags, for example `v0.12.1`.

## Installing the skills and the CLI with install.sh

With owner authorization, commit the change, run the test suite, then run `install.sh` from this repository:

```bash
python3 -B -m unittest discover -s tests
./install.sh                                  # installs HEAD into ~/.agents/skills/odoo19
./install.sh --target /absolute/scratch/odoo19 # try it somewhere else first
```

The installer copies the committed HEAD only (uncommitted edits are never installed), drops repository-only files (`AGENTS.md`, `.gitignore`, `install.sh`), records the installed version (from `package.json`) and commit in `.oasis-install.json`, and moves the previous install to `${XDG_STATE_HOME:-~/.local/state}/oasis/backups/`, outside any skill discovery directory. `OASIS_STATE_DIR` overrides that state directory. Run it again to update.

## Installing the package

From a release tag, so sessions load a fixed copy that work in a local checkout cannot change:

```bash
gentle-shell install git:github.com/skhol3/oasis@<tag>
```

Then `/reload` open sessions, and run `/oasis setup` once for the subagent overlay (see
[Subagents](subagents.md)).

## Moving the package to another release

Remove the installed tag and install the new one, then `/reload` open sessions. `gentle-shell list`
shows the installed entry.

```bash
gentle-shell remove git:github.com/skhol3/oasis@<installed tag>
gentle-shell install git:github.com/skhol3/oasis@<new tag>
```

Installing a local checkout (`gentle-shell install /absolute/path/to/oasis`) loads whatever that
directory holds, including a branch under development; use it only to try changes.

## What gets installed

The `install.sh` target contains the six `odoo19-*` directories, `tools/`, `project-wrappers/`, `tests/`, `docs/`, the `oasis` entry point (and its `odoo19` alias), the Gentle Shell layer (`package.json` and `pi/`), and the [README](../README.md). Restart the agent session or use `/reload` where supported, then check that exactly six skills are discovered. The skill entrypoints are [backend](../odoo19-backend/SKILL.md), [security](../odoo19-security/SKILL.md), [views/frontend](../odoo19-views-frontend/SKILL.md), [testing](../odoo19-testing/SKILL.md), [environment](../odoo19-environment/SKILL.md), and [module lifecycle](../odoo19-module-lifecycle/SKILL.md). See the [project capability contract](../odoo19-environment/references/project-contract.md).
