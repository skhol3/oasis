# oasis — Odoo Agent Skills & Infrastructure Scripts

## Project

- This repository is the source of the global Odoo 19 agent bundle: the `odoo19` entry point,
  its guarded `tools/`, the `odoo19-*` skills, project wrapper templates and docs.
- Agents never read this repository directly. `install.sh` copies the committed HEAD to
  `~/.agents/skills/odoo19`; uncommitted edits are never installed.
- Code, comments, commit messages and documentation are in English.

## Boundaries

- Editable: everything in this repository.
- Read-only unless the user explicitly authorizes the exact path: `~/.agents/skills/odoo19`
  (install target, changed only through `install.sh`), Odoo projects that use the bundle,
  Odoo source trees, environments and databases.
- Never print or copy credentials: project `.env` files and `odoo.conf` passwords stay where they are.
- Never unpack historical archives under a skill discovery directory.

## Compatibility

Several Odoo projects depend on the installed bundle. Treat as a contract: the `odoo19`
command names and options, `.odoo19-agent.toml` `[tooling]` keys, database prefix guards and
the skill names. Changing or removing any of them needs an explicit decision and a note in
the README.

## Verification

Run before every commit:

```bash
python3 -B -m unittest discover -s tests
```

Tests use synthetic fixtures; they must never touch a real project, database or the install
target. Install only after the suite passes and the change is committed:

```bash
./install.sh            # or ./install.sh --target /absolute/scratch/odoo19 to try it
```

## Releases

Versions follow Semantic Versioning and are tagged on `main` only:

1. In the release pull request, move the `[Unreleased]` entries of `CHANGELOG.md` under the
   new version and set the same `version` in `package.json` (patch: fixes; minor: additions,
   or contract changes while `0.x`; major: contract changes after `1.0.0`). Commit as
   `chore(release): vX.Y.Z`.
2. Merge the pull request to `main`.
3. On the updated `main`, run the test suite, then tag: `git tag -a vX.Y.Z -m "oasis vX.Y.Z"` and push the tag.
4. Publish the GitHub release with the changelog section as notes.

`install.sh` records the installed `version` and commit in `.oasis-install.json`.
