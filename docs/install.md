# Install or update

## Released versions

Releases follow Semantic Versioning and are tagged `vX.Y.Z`; see the [changelog](../CHANGELOG.md). Install a released version of the Gentle Shell layer with `gentle-shell install git:github.com/skhol3/oasis@v0.10.0`.

## Installing with install.sh

With owner authorization, commit the change, run the test suite, then run `install.sh` from this repository:

```bash
python3 -B -m unittest discover -s tests
./install.sh                                  # installs HEAD into ~/.agents/skills/odoo19
./install.sh --target /absolute/scratch/odoo19 # try it somewhere else first
```

The installer copies the committed HEAD only (uncommitted edits are never installed), drops repository-only files (`AGENTS.md`, `.gitignore`, `install.sh`), records the installed version (from `package.json`) and commit in `.oasis-install.json`, and moves the previous install to `${XDG_STATE_HOME:-~/.local/state}/oasis/backups/`, outside any skill discovery directory. `OASIS_STATE_DIR` overrides that state directory.

## What gets installed

The installed package contains the six `odoo19-*` directories, `tools/`, `project-wrappers/`, `tests/`, `docs/`, the `oasis` entry point (and its `odoo19` alias), the Gentle Shell layer (`package.json` and `pi/`), and the [README](../README.md). Restart the agent session or use `/reload` where supported, then check that exactly six skills are discovered. The skill entrypoints are [backend](../odoo19-backend/SKILL.md), [security](../odoo19-security/SKILL.md), [views/frontend](../odoo19-views-frontend/SKILL.md), [testing](../odoo19-testing/SKILL.md), [environment](../odoo19-environment/SKILL.md), and [module lifecycle](../odoo19-module-lifecycle/SKILL.md). See the [project capability contract](../odoo19-environment/references/project-contract.md).
