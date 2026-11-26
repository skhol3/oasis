# Setting up a checkout with oasis setup

`oasis setup` configures a checkout for oasis in one command: clone the repository, read the plan,
apply it, then run `doctor`. It infers what it can, asks only what it cannot, keeps everything that
already exists and creates only the missing pieces. The whole flow, from a clone to a development
database, where each value lives and what setup does for you by hand are in
[Setting up a new workspace](new-workspace.md).

```bash
cd /absolute/checkout
~/.agents/skills/odoo19/oasis setup            # the plan; nothing changes
~/.agents/skills/odoo19/oasis setup --apply    # creates the missing pieces
~/.agents/skills/odoo19/oasis doctor
```

```text
oasis [--project <checkout>] setup [--series <x.y>] [--community <dir>] [--enterprise <dir> | --no-enterprise]
                                   [--workspace <dir>] [--name <name>] [--exception <module>]...
                                   [--config-dir <dir>] [--environment <dir> | --python <x.y>]
                                   [--answer <id>=<value>]... [--answers <file.json>] [--apply | --plan [--json]]
```

- [Plan and apply](#plan-and-apply): what is printed, what changes, exit status.
- [What it infers and what it asks](#what-it-infers-and-what-it-asks): the checkout, the series, the source.
- [Questions and answers](#questions-and-answers): flags, `--answer`, `--answers <file.json>`, open questions.
- [The plan as JSON](#the-plan-as-json): `--plan --json` for an agent.
- [Anticipated problems](#anticipated-problems): python-ldap, module requirements, old source archives.
- [What it creates and what it keeps](#what-it-creates-and-what-it-keeps): every file and directory.
- [Another Odoo series](#another-odoo-series): a checkout of a series the workspace file has no section for.
- [The database account](#the-database-account): the generated account, one file, read by the service and Odoo.
- [Next steps](#next-steps): what is left for you.
- [oasis setup and /oasis setup](#oasis-setup-and-oasis-setup): two different commands.

## Plan and apply

- Without `--apply` it prints the plan and changes nothing; the plan ends with
  `dry run: nothing changed; run with --apply to set up`. `--plan` asks for the plan explicitly and
  can never apply: with `--apply` it is a usage error (exit 2), like `--enterprise` with
  `--no-enterprise`. Options are never abbreviated.
- The plan names the checkout, the series, the source and the workspace with where each came from
  (`from the module manifests`, `from the machine file`, `from --community`, `answered`), then one
  line per piece: `create <path>` for a missing one, `kept <path>` for an existing one. The new
  workspace file and the machine file entry are shown in full, indented; the other files by a
  summary line. No password is ever printed: the plan names the generated account by its user name
  (`ODOO_DB_USER oasis_<name> and a generated ODOO_DB_PASSWORD`).
- With `--apply` it prints the same plan, creates the files (each one exclusively, so an existing
  file is never replaced), checks that the checkout loads its configuration
  (`verified: <checkout> loads its configuration from <workspace file>`), compiles the locks, creates
  the environment and prints the [next steps](#next-steps). When the configuration does not load,
  every file it wrote is removed again and it exits 1 with `ERROR: Verification failed (...); every
  change was undone.`
- A failed `uv pip compile`, `uv venv` or `uv pip sync` stops with exit 2 and keeps the files
  already written. After a failed compile or `uv venv`, fix the cause and run `oasis setup --apply`
  again, which keeps them and continues. When setup adds a section to an existing workspace file
  ([Another Odoo series](#another-odoo-series)), a failed compile or `uv venv` undoes every change
  instead (`ERROR: uv pip compile failed; every change was undone.`, `ERROR: uv venv failed (exit <n>);
  every change was undone: fix it, then run oasis setup --apply again.`). After a failed `uv pip sync`
  the environment exists, and a second setup run would keep it without syncing it, so the error names
  the command that completes it: `ERROR: uv pip sync failed (exit <n>); the files above and the environment <environment> are
  kept: fix it, then run oasis --project <checkout> bootstrap --apply to sync it.`
- When nothing is missing it prints the `kept` lines and `nothing to set up: run oasis --project
  <checkout> doctor` (exit 0). Refusals exit 2 with `ERROR: <reason>` and change nothing.
- `setup` and `setup --apply` are Tier A in the [agent contract](agent-contract.md): an agent runs
  them alone, since `--apply` creates only what is missing.

## What it infers and what it asks

- The checkout: `--project`, else the git top level of the current directory (the current
  directory outside git). A linked worktree without a workspace file is refused
  (`<worktree> is a linked worktree of <main>: run oasis setup in the main checkout.`): set up the
  main checkout, and its worktrees then find the workspace file through git.
- The series: `--series`, else the version prefix of the module manifests directly in the checkout
  or one directory below it (`19.0.1.0.0` gives `19.0`), else the single series of the machine
  file, else a question. Manifests of several series, or of one oasis does not support, are refused.
  Versions are read as the series guard reads them: only `<series>.x.y.z` of a supported series or one
  that looks like an Odoo release (`<major>.0`, major 8 to 99) counts, so `1.0` or `1.2.3.4.5` says
  nothing. A configuration whose modules declare another series than its own, an existing one or one
  `--series` asks for, is refused before anything is written (a new one before any question; see
  [Workspace file](workspace-file.md#discovery-precedence-and-versions)).
- The Odoo source: the machine file's entry for the series, else `--community <dir>` (an absolute
  directory whose `odoo/release.py` declares the series) and `--enterprise <dir>` or
  `--no-enterprise`, else a question. A source found near the checkout is only offered
  (`[Enter: <path>]` on a terminal, `found <path>, a suggestion only` otherwise), never chosen.
- The project name, which gives the database prefixes `<name>_dev_` and `<name>_test_` and the compose
  project: the checkout's directory name, lower-cased, or `--name` (2 to 20 lowercase letters,
  digits or underscores, starting with a letter).
- The Python environment, when setup would create one (a new workspace, or a new
  [series section](#another-odoo-series)) and neither `--environment` nor `--python` is given: on a
  terminal it asks whether to create it or to use an existing one, and the Python of a new one
  ([A new environment and its Python](#a-new-environment-and-its-python)). Without a terminal nothing is
  asked: the environment is created with the configuration's Python, as before.
- Questions are asked only when standard input and standard error are a terminal (never with `--json`).
  Otherwise a missing answer is an [open question](#questions-and-answers) that names its flag, for
  example `No Odoo Community source for 19.0 in the machine file <file>: pass --community <dir>.` or
  `Enterprise or not for 19.0: pass --enterprise <dir> or --no-enterprise.`: the plan lists it and
  `--apply` refuses with it (exit 2).
- Every question comes before any change, with or without `--apply`. End of input (Ctrl-D) at a question
  refuses like a missing answer (exit 2); Ctrl-C stops with `ERROR: Interrupted at a question: nothing
  changed.` (exit 130). Either way nothing is written.

## Questions and answers

No command needs a terminal (v0.16.0): every question setup asks on one has a flag, and every
question has an id that `--answer <id>=<value>` (repeatable) or `--answers <file.json>` answers:

| Id | Answer | Same as |
| --- | --- | --- |
| `series` | `<x.y>` | `--series <x.y>` |
| `community` | an absolute directory | `--community <dir>` |
| `enterprise` | an absolute directory, or `none` | `--enterprise <dir>`, `--no-enterprise` |
| `environment` | `create`, or the absolute directory of an existing environment | `--environment <dir>` |
| `python` | `<x.y>` | `--python <x.y>` |
| `python_ldap` | `yes` or `no` | [python-ldap and OpenLDAP 2.6](#python-ldap-and-openldap-26) |
| `requirement:<name>` | `add`, `override` or `skip` (the options it lists) | [Module requirements](#module-requirements) |

```json
{"community": "/srv/odoo/19.0/community", "enterprise": "none", "python_ldap": "yes"}
```

- The file is one JSON object of ids and text answers; anything else, an unknown id, or an answer given
  twice (by a flag and by an answer) is refused (exit 2) and changes nothing. An answer to a question that
  does not arise is not used.
- Without a terminal and without an answer, setup uses the recommended answer only where it did before:
  the environment is created, with the configuration's Python. Every other question is open: the plan
  prints the lines it has, then `open question <id>: <what it needs and the flag that answers it>` and
  `nothing changed: answer the open questions above (docs/setup.md#questions-and-answers), then run with
  --apply to set up` (exit 0). A question setup cannot go on without (the series, the source) ends the
  plan there, and `--apply` refuses with the message it always had. A question of an
  [anticipated problem](#anticipated-problems) does not stop the plan; `--apply` refuses with one
  `ERROR: open question <id>: ...` line per open question, then `ERROR: nothing changed: answer the open
  questions, then run oasis setup --apply again.` (exit 2).
- On a terminal, a question of an anticipated problem is asked like the others: Enter takes the
  recommended answer; an answer that is not an option is asked again.
- `init-dev-database` needs no terminal either: on one it asks each password with the echo off (Enter
  generates one), otherwise it generates them ([Development database](dev-database.md)).

## The plan as JSON

`oasis setup --plan --json` (or `setup --json`) prints the plan as one JSON object on one line and
changes nothing; it never asks, and `--json` with `--apply` is a usage error. The human plan without
`--json` is unchanged. A refusal is still `ERROR: <reason>` on stderr with nothing on stdout (exit 2).
An example, formatted:

```json
{"format": "oasis-setup-plan", "version": 1, "checkout": "/w/shop", "complete": true, "ready_to_apply": false,
 "inferred": {"checkout": {"value": "/w/shop", "origin": "main"},
              "workspace": {"value": "/w/shop", "origin": "new"},
              "series": {"value": "15.0", "origin": "from the module manifests"},
              "community": {"value": "/srv/odoo/15.0", "origin": "from the machine file"},
              "enterprise": {"value": null, "origin": "from the machine file"},
              "name": {"value": "shop", "origin": "from the checkout name"},
              "db_port": {"value": 5433, "origin": "a free port"},
              "environment": {"value": "/w/shop/.oasis/venv", "origin": "new"},
              "python": {"value": "3.9", "origin": "the default of Odoo 15.0"}},
 "changes": [{"kind": "mkdir", "path": "/w/shop/.oasis", "summary": "create the directory /w/shop/.oasis/"},
             {"kind": "create", "path": "/w/shop/.oasis/config/odoo.conf",
              "summary": "create /w/shop/.oasis/config/odoo.conf (mode 0600): path-free; db_port 5433; db_user and db_password empty"},
             {"kind": "compile", "path": "/w/shop/.oasis/config/requirements",
              "summary": "compile /w/shop/.oasis/config/requirements/runtime.txt, dev.txt and lock.sha256 with Python 3.9 (uv pip compile)"}],
 "questions": [{"id": "environment", "text": "Python environment for Odoo 15.0: create /w/shop/.oasis/venv, or use an existing environment",
                "options": [{"value": "create", "label": "create /w/shop/.oasis/venv"}], "recommended": "create",
                "flag": "--environment <dir>", "answer": "create", "origin": "recommended (no terminal)"},
               {"id": "python_ldap",
                "text": "Odoo 15.0 pins python-ldap==3.4.0, which does not build against this machine's OpenLDAP 2.6.8 (no libldap_r): pin python-ldap==3.4.4 in /w/shop/.oasis/config/requirements/overrides.txt?",
                "options": [{"value": "yes", "label": "pin python-ldap==3.4.4 (uv pip compile --override)"},
                            {"value": "no", "label": "keep Odoo's pin: its build may fail"}],
                "recommended": "yes", "flag": "--answer python_ldap=<yes|no>", "answer": null, "origin": null}],
 "open": ["python_ldap"],
 "lines": ["checkout: /w/shop (main)", "series: 15.0 (from the module manifests)", "..."]}
```

| Key | Value |
| --- | --- |
| `format`, `version` | `oasis-setup-plan` and `1`; keys are only ever added within a version. |
| `checkout` | The checkout setup plans for. |
| `complete` | `false` when the plan stopped at a question it cannot go on without; `changes` is then empty. |
| `ready_to_apply` | `complete` and no open question: `--apply` with the same flags and answers would run. |
| `inferred` | Each value setup found, with its `origin`: `checkout` (`main`, `linked`, `outside git`), `workspace` (its directory; `new` or `existing`), `series`, `community`, `enterprise` (`null`: none), `name` (a new workspace), `db_port` (`a free port`, `from <odoo.conf>`, `from <compose file>`), `environment` (`new`, `existing`, `from --environment`, `answered`) and `python`. A plan that stopped lists what it found before. |
| `changes` | Every change `--apply` would make, in order: `kind` (`mkdir`, `create`, `extend` (appended), `fill` (account variables filled in), `edit` (lines removed), `compile`, `environment`), `path`, and `summary` (its plan line). Never a value of the account. |
| `questions` | Every question the plan met: `id`, `text`, `options` (`value`, `label`), `recommended` (or `null`), `flag` (what answers it), and `answer` with its `origin` (`from --answer`, `from --answers`, `recommended (no terminal)`), both `null` while it is open. |
| `open` | The ids of the open questions. |
| `lines` | The human plan, line by line (without the open questions, which are in `questions`). |

## Anticipated problems

When setup writes a new `runtime.in` (a new workspace, or a new [series section](#another-odoo-series)),
it looks for what would make the compile or the sync fail later and asks about it in the plan, before any
change (`tools/known_problems.py`). A kept `overrides.txt` is never edited: setup then asks nothing that
would pin there (python-ldap gets a `WARN` line naming the pin to add yourself).

### python-ldap and OpenLDAP 2.6

Odoo 15.0 pins `python-ldap==3.4.0` (`ldap_override` in `tools/odoo_versions.py`), which links
`libldap_r`, removed in OpenLDAP 2.6. When the source's `requirements.txt` has that pin and this machine
has OpenLDAP 2.6 or later without `libldap_r` (`pkg-config --modversion ldap`, else the libldap names
`ldconfig -p` lists; neither program, no question), the question `python_ldap` (recommended `yes`) pins
`python-ldap==3.4.4` in a new `overrides.txt`, which builds against both:

```text
# Odoo 15.0's python-ldap==3.4.0 does not build against OpenLDAP 2.6 (no libldap_r).
python-ldap==3.4.4
```

### Module requirements

Each `external_dependencies` `python` entry of the checkout's module manifests is compared with the
requirements a new `runtime.in` gives (the source's, the series' and the project's
`requirements-extra.txt`, with `requirements-overrides.txt` replacing what it names), for the
environment's Python on Linux. Import names of another distribution are translated (`ldap` is
`python-ldap`, `dateutil` `python-dateutil`, ...) and standard library modules skipped.

- Missing (no requirement names it): `requirement:<name>`, `add` (recommended: below a comment in the new
  `runtime.in`; setup never edits the project's `requirements-extra.txt`) or `skip`.
- Conflicting (an exact pin that does not satisfy it, such as `cryptography>=3.3.1` against Odoo 15.0's
  `cryptography==2.6.1`): `requirement:<name>`, `override` (recommended: the lowest version it accepts,
  `cryptography==3.3.1`, in a new `overrides.txt`) or `skip`.

### Old source archives

uv 0.13 and later refuse some old source archives (V7 tar headers, such as `PyPDF2==1.26.0` of Odoo
15.0) with `invalid tar identity`. Every uv command of setup and `bootstrap --apply`, and the compile both
run (`tools/locks.py`), gets `UV_LEGACY_TAR_BACKEND=1` when `uv --version` reports 0.13 or later and the
variable is not set (a value you set, even empty, is kept). When a compile still fails with that message,
the error names the remedy instead of the package index: set `UV_LEGACY_TAR_BACKEND=1`, or, when it was
set, pin a version of that package that has a wheel in `overrides.txt`.

## What it creates and what it keeps

| Piece | When it is missing, setup creates |
| --- | --- |
| [Machine file](workspace-file.md#machine-file) entry `[series."<x.y>"]` | `community` and, with Enterprise, `enterprise`. A new file is created with mode 0600; an existing file without the entry gets it appended. An existing entry is used and never edited: a flag that disagrees with it, or an entry without `community`, is refused. |
| `oasis-workspace.toml` | `workspace_version`, `odoo_version`, and `[tooling]` with the environment, `config`, `env_file`, `compose`, `requirements`, `addons_paths` (the directories that hold the modules, `'.'` by default), `db_service = 'db'`, the prefixes, `logs` and `data_dir`; never a source key. Mode 0600. |
| `odoo.conf` | Path-free (no `addons_path`, no `data_dir`; see [Path-free odoo.conf](path-free-odoo-conf.md)): `db_host = 127.0.0.1`, the `db_port` of the compose file, `db_user` and `db_password` empty: Odoo gets the [database account](#the-database-account) of the environment file. Mode 0600. |
| Compose file | `name: oasis-<name>-<6 hex of the workspace directory>` and the PostgreSQL service (`postgres:<postgres_default>` of the series in `tools/odoo_versions.py`: `postgres:17` on 19.0) with the variables oasis uses, published on `127.0.0.1` on the [port](#one-port-for-odooconf-and-the-compose-file) `odoo.conf` connects to. |
| Environment file | The [database account](#the-database-account): `ODOO_DB_USER=oasis_<name>` and a random `ODOO_DB_PASSWORD`, or the `db_user` and `db_password` a kept `odoo.conf` sets; mode 0600. The password is never printed. A kept environment file gets the account in the variables it leaves empty, every other byte kept; a kept `odoo.conf` whose account it holds loses those two lines ([The database account](#the-database-account)). |
| `runtime.in`, `dev.in` | `-r <community>/requirements.txt`, then what the series needs that those requirements do not list (`runtime_requirements` in `tools/odoo_versions.py`: nothing on 19.0, `setuptools<81` on 15.0, [below](#odoo-150-requirements)); `-c runtime.txt` and `-r runtime.in`, to which you add your development tools. With an adopted series folder that holds `requirements-extra.txt`, `runtime.in` also includes it ([Another Odoo series](#the-projects-requirement-files)). |
| `overrides.txt` | With an adopted series folder that holds `requirements-overrides.txt`: `-r <that file>`, given to `uv pip compile` as `--override` ([Another Odoo series](#the-projects-requirement-files)); and the pins of the [anticipated problems](#anticipated-problems) answered `yes` or `override`. |
| Locks | `runtime.txt`, `dev.txt` and `lock.sha256`, compiled with the series' Python by the same code as `bootstrap --apply` when they are missing or stale; current locks are kept, and a lock changed by hand is kept and leaves the environment uncreated. |
| Environment | `uv venv --python <python>` and `uv pip sync` of `dev.txt`, with the series' default Python, `--python <x.y>` or the [answered one](#a-new-environment-and-its-python). An existing environment is kept and not synced (run `bootstrap --apply` for that); `--environment <dir>` (or an answered path) [adopts one](#an-existing-environment) instead of creating it. |
| `logs`, `data_dir` | The directories (mode 0700). |

### One port for odoo.conf and the compose file

`odoo.conf`'s `db_port` and the port the compose file publishes to PostgreSQL's 5432 must be the same:

- Both missing: the first free port from 5432 on `127.0.0.1`.
- Only `odoo.conf` exists: the new compose file publishes its `db_port` (5432, PostgreSQL's default, when it
  has none).
- Only the compose file exists: the new `odoo.conf` gets the port it publishes to 5432, read from a
  short-syntax entry such as `- '127.0.0.1:6001:5432'`, `- "6001:5432"` or `- 6001:5432/tcp` (no YAML
  parser: the long syntax, ranges and variables are not read). When no single such port is found, it gets
  a free port and the plan says `check <odoo.conf>: no port published to 5432 found in <compose file>; set
  db_port <port> to the port it publishes`.
- Both exist: both are kept; when they disagree the plan says `mismatch: <odoo.conf> connects to port <a>
  but <compose file> publishes <b>: make them the same`.

### Where the files go

- Without a workspace file, the workspace is the checkout itself: `oasis-workspace.toml` at its root
  and `config/`, `data/`, `logs/` and the environment `venv/` under `<checkout>/.oasis/`. Both are
  added to the clone's `.git/info/exclude` (never to the tracked `.gitignore`), unless git already
  ignores them, so no directory layout is imposed and nothing new shows in `git status`. The
  environment goes to `<environments>/<name>` instead when the machine file's entry sets
  `environments`.
- `--workspace <dir>` puts the workspace file in `<dir>` instead, an absolute existing directory at
  or above the checkout (`Refusing --workspace <dir>: it is not at or above the checkout <checkout>.`),
  with `config/`, `data/`, `logs/` and `venv/` directly under it, as in the
  [example tree](new-workspace.md#the-example-tree), one possible layout. The directory must be yours and not writable by
  group or others ([Trust](workspace-file.md#trust)).
- With a workspace file at or above the checkout (or found through git), that file is adopted: its
  paths decide where everything goes and only the missing pieces are created. The options that
  answer a new configuration (`--series`, `--name`, `--workspace`, and the source options when the
  configuration already has a source) are then refused (`<option>: <checkout> is already configured
  by <file>; setup only fills what is missing.`). A workspace file without a source gets the machine
  file entry. A checkout that still has the legacy profile is refused before setup runs: run
  [migrate](migrating.md) first. A checkout of another series than the file configures gets a
  section instead ([Another Odoo series](#another-odoo-series)). `--exception` and `--config-dir` apply
  only then; without a workspace file they are refused (`<option>: <checkout> has no workspace file; it
  only applies when setup adds a [series."<x.y>"] section to one.`).

## Another Odoo series

One workspace file can hold [several Odoo series](workspace-file.md#several-series-workspace_version-2).
Run `setup` in a checkout of a series the file has no section for, and the plan adds that section and
that series' files, next to the other series and without touching them:

- The checkout's series: `odoo_version` in its `oasis-checkout.toml`, else the series its module
  manifests declare, the modules of `--exception <module>` (repeatable) and of every section's
  `series_exceptions` left out. Manifests of several supported series are refused as before. A module
  of another series that is not an exception is refused before any question: `The module <module>
  declares Odoo 16.0 (version 16.0.2.0.2 in <manifest>), but <checkout> is an Odoo 15.0 checkout: pass
  --exception <module> to list it in series_exceptions under [series."15.0"], or set its version to
  15.0.x.y.z if it is an Odoo 15.0 module.`
- The machine file entry of the series, when it is missing, exactly as for a new checkout (`--community`,
  `--enterprise` or `--no-enterprise`, else a question). `--series`, `--name` and `--workspace` are refused.
- The workspace file: `add [series."<x.y>"] to <file>:` shows the section, appended after a one-line
  comment; nothing else in the file changes. A `workspace_version = 1` file becomes version 2 by that line
  only (`change workspace_version = 1 to workspace_version = 2 in <file> (that line only)`). The result
  is checked before anything is written: it must parse to the same document plus the section, pass the
  workspace checks, and give every series it configured the same configuration. Otherwise it is
  refused (exit 2), for example `Cannot add [series."15.0"] to <file>: the change would alter the
  configuration of Odoo 19.0 ({series} or a [series] table that version 1 does not read); edit the file
  yourself.`, or, when the version line is not a plain `workspace_version = 1`, `Cannot convert <file> to
  workspace_version 2: no single line workspace_version = 1; set workspace_version = 2 yourself, then
  run oasis setup again.`
- The section sets only what `[tooling]` would otherwise share with the default series (a path that
  already uses `{series}` is left to `[tooling]`): `config`, `env_file`, `compose` and `requirements` in
  `<folder of [tooling].config>/<x.y>/` (`config/15.0/`), the environment next to `[tooling]`'s
  (`environments/acme` gives `environments/acme-15.0`; with the machine file's `environments` for the
  series, `<environments>/<name><major>`), `logs` and `data_dir` in `<logs>/<x.y>` and `<data_dir>/<x.y>`
  (an adopted folder's own, below),
  the prefixes `<name><major>_dev_` and `<name><major>_test_` (`cc_dev_` gives `cc15_dev_`), the source
  when `[tooling]` sets one, and `series_exceptions` from `--exception`.
- Adopted files: a folder next to the default one named for the series (`<x.y>`, `odoo-<major>`,
  `odoo<major>`, `odoo-<x.y>`, `odoo<x.y>` or `<major>`) that holds an `odoo.conf` or a compose file
  (`compose.yml`, `compose.yaml`, `docker-compose.yml`, `docker-compose.yaml`), or the folder
  `--config-dir <dir>` names (an absolute existing directory), is adopted: `adopt <folder> (found):
  odoo.conf, compose.yml, .env, requirements/`. The section points to its files, setup keeps them and
  creates only the missing ones there. The data and logs of the folder stay where they are:
  - When its kept `odoo.conf` sets `data_dir`, that directory is the section's `data_dir` instead of
    `<data_dir>/<x.y>`, read as Odoo reads it (variables and `~` expanded, a relative path from the
    directory setup runs in, as Odoo's working directory), written relative to the workspace file's
    directory when it is below it: `data_dir: <corpus-cafe>/data/odoo-15 (data_dir from
    <corpus-cafe>/config/odoo-15/odoo.conf)`. Only `data_dir` is read from that file. Without one, with
    an empty one, or when the file cannot be read, the default stays; a `data_dir` of several lines or
    with a NUL is refused (`Invalid data_dir in <odoo.conf>: it must be one directory path.`).
  - When `logs/<folder name>` exists next to the folder's parent (`logs/odoo-15` for `config/odoo-15`)
    and is inside the workspace file's directory, it is the section's `logs`: `logs:
    <corpus-cafe>/logs/odoo-15 (named for <corpus-cafe>/config/odoo-15)`; otherwise `<logs>/<x.y>`. A
    `--config-dir` folder outside the workspace (`/home/user/legacy15`) keeps `<logs>/<x.y>`: setup does not
    look for `/home/logs/legacy15`.
  - Either is left out when it is what `[tooling]` already gives the series.

  Two such folders are refused (`Several folders hold Odoo 15.0
  files: <folder>, <folder>; pass --config-dir <dir>.`).
- The missing files as for any checkout ([What it creates](#what-it-creates-and-what-it-keeps)), with
  the series' values: the compose file with its `postgres_default` (`postgres:14` on 15.0) on a free port
  that no other series of the workspace uses, its own compose project (`oasis-<name><major>-...`), the
  requirement inputs of its source (on 15.0 with `setuptools<81`, [below](#odoo-150-requirements)), and the
  locks and environment with its `python_default` (3.9 on 15.0), or the Python of `--python` or of the
  [answer](#a-new-environment-and-its-python).
- A kept `odoo.conf` or compose file of the series that uses a port another series of the workspace
  uses (its `odoo.conf`'s `db_port`, 5432 without one, or the port its compose file publishes) is
  refused before anything is written, since setup never edits a kept file and `doctor` fails two
  series on one port: `Port 5432 of Odoo 15.0 (<odoo.conf> connects to it) is already used by Odoo
  19.0 (<its odoo.conf>); two series of a workspace cannot share a PostgreSQL port: set db_port in
  <odoo.conf> to a port no other series uses, then run oasis setup again.` (with a kept compose file,
  `... and publish the same port to 5432 in <compose file>`; with only a compose file, `(<compose file>
  publishes it) ... publish a port no other series uses to 5432 in <compose file>`).
- Named `[environments]`: a `default` path with `{series}` gives the series its own environment with
  that environment's `python`, and the section sets no `environment`; a path without `{series}` gives
  the section `environment = '<path>-<x.y>'` with the series' `python_default`. When the series does
  not support the `default` environment's `python` (`3.13` on 15.0), the section sets the path with
  `{series}` replaced (or `<environments>/<name><major>` with the machine file's `environments`), so the
  series uses its `python_default`.
- The project's requirement files: see [below](#the-projects-requirement-files); `--environment <dir>`
  adopts an [existing environment](#an-existing-environment) for the series.
- The workspace file and the machine file are edited first. A failed verification, `uv pip compile`
  or `uv venv` gives them back their bytes (their modes are kept), restores the locks the compile
  rewrote and removes every file and directory setup created; a failed `uv pip sync` keeps
  everything, as for any checkout.

After `--apply` the next run in that checkout finds the section and only prints `kept` lines; the
checkouts of the other series read the file as before. Agents may run the plan; `setup --apply` stays
the user's.

For example, corpus-cafe has a 19.0 workspace file and a 15.0 worktree, `codigo/facturacion`, whose
`report_xlsx` declares `16.0.2.0.2`; an earlier setup left the 15.0 files in `config/odoo-15/`
(`odoo.conf` with `db_port = 5415` and `dbfilter = ^cc15_`, `compose.yml` with `postgres:14-alpine` on
5415, `.env`):

```toml
# corpus-cafe/oasis-workspace.toml before, example only.
workspace_version = 1
odoo_version = '19.0'

[tooling]
environment = 'environments/corpus-cafe'
config = 'config/odoo.conf'
env_file = 'config/.env'
compose = 'config/compose.yml'
requirements = 'config/requirements'
addons_paths = ['.']
db_service = 'db'
dev_prefix = 'cc_dev_'
test_prefix = 'cc_test_'
logs = 'logs'
data_dir = 'data'
```

```bash
cd corpus-cafe/codigo/facturacion
~/.agents/skills/odoo19/oasis setup --exception report_xlsx            # the plan
~/.agents/skills/odoo19/oasis setup --exception report_xlsx --apply
```

```text
series: 15.0 (from the module manifests; <corpus-cafe>/oasis-workspace.toml has no [series."15.0"] section)
...
change workspace_version = 1 to workspace_version = 2 in <corpus-cafe>/oasis-workspace.toml (that line only)
add [series."15.0"] to <corpus-cafe>/oasis-workspace.toml:
  # Added by oasis setup: what differs for the Odoo 15.0 checkouts (docs/setup.md#another-odoo-series).
  [series."15.0"]
  environment = 'environments/corpus-cafe-15.0'
  config = 'config/odoo-15/odoo.conf'
  env_file = 'config/odoo-15/.env'
  compose = 'config/odoo-15/compose.yml'
  requirements = 'config/odoo-15/requirements'
  dev_prefix = 'cc15_dev_'
  test_prefix = 'cc15_test_'
  logs = 'logs/15.0'
  data_dir = 'data/15.0'
  series_exceptions = ['report_xlsx']
adopt <corpus-cafe>/config/odoo-15 (found): odoo.conf, compose.yml, .env
kept <corpus-cafe>/config/odoo-15/odoo.conf
kept <corpus-cafe>/config/odoo-15/compose.yml
kept <corpus-cafe>/config/odoo-15/.env
create <corpus-cafe>/config/odoo-15/requirements/runtime.in: -r <15.0 source>/requirements.txt, setuptools<81
...
create the environment <corpus-cafe>/environments/corpus-cafe-15.0 with Python 3.9 (uv venv) and sync dev.txt (uv pip sync)
```

The 19.0 checkouts keep `config/odoo.conf`, `cc_dev_` and their environment; `doctor` in either shows
`PASS series_isolation=19.0,15.0` once the two compose files publish different ports.

### Odoo 15.0 requirements

- The default Python of 15.0 is 3.9, the one Odoo builds its official 15.0 Debian package on
  (`setup/package.dfdebian` of the 15.0 source: `FROM debian:bullseye`; 19.0's is `ubuntu:noble`, Python
  3.12). Older Odoo 15 pins, such as `reportlab` 3.5.59 and `gevent` 21.8.0, have no wheels for later
  Pythons and their sources may not build with a current compiler.
- Odoo 15 imports `pkg_resources` without listing `setuptools`, which provides it: an environment uv
  creates has no `setuptools`, and `uv pip sync` removes it from an environment that has it, so Odoo stops
  with `No module named 'pkg_resources'`. A new 15.0 `runtime.in` therefore requires it, with a comment,
  after the Odoo requirements:

  ```text
  # Odoo 15.0 imports pkg_resources without listing setuptools, which provides it: an environment uv creates has none and uv pip sync would remove it; setuptools advises <81 to keep pkg_resources.
  setuptools<81
  ```

  The plan line says `create <requirements>/runtime.in: -r <source>/requirements.txt, setuptools<81`. A
  kept `runtime.in` is not changed: add the two lines yourself, then `bootstrap --apply` compiles the
  locks again (they are stale once `runtime.in` changes).
- On a machine with OpenLDAP 2.6, the `python-ldap==3.4.0` that Odoo 15 pins does not build from source:
  it links `-lldap_r`, a library OpenLDAP 2.6 no longer has. Put `python-ldap==3.4.4` in the project's
  `requirements-overrides.txt` ([below](#the-projects-requirement-files)); setup and `bootstrap` give it to
  `uv pip compile` as an override.

### The project's requirement files

An adopted series folder (found, or `--config-dir`) may hold the project's own requirement files, which
setup references and never copies or edits:

- `requirements-extra.txt`, the packages the project's modules need besides Odoo's: a new `runtime.in`
  includes it after the Odoo requirements, with `-r <path>` relative to the requirements directory
  (`-r ../requirements-extra.txt` for `<folder>/requirements/`; absolute when either is outside the
  workspace directory).
- `requirements-overrides.txt`, pins that replace Odoo's (an older `cryptography` for an older Python, for
  example): setup creates `<requirements>/overrides.txt` with `-r ../requirements-overrides.txt`, and
  every compile of that directory, by setup or `bootstrap`, passes it to `uv pip compile` as `--override
  overrides.txt` (uv reads the nested `-r`). `lock.sha256` records `overrides.txt`, so adding, changing or
  removing it makes the locks stale ([Dependency locks](checking-environment.md#dependency-locks)).

The plan names them in the `adopt` line, then `create <requirements>/runtime.in: -r <source>/requirements.txt,
-r ../requirements-extra.txt` (on 15.0 `-r <source>/requirements.txt, setuptools<81, -r ../requirements-extra.txt`)
and `create <requirements>/overrides.txt: -r ../requirements-overrides.txt (uv pip
compile --override)`. A `runtime.in` or `overrides.txt` that exists is kept as it is. `lock.sha256` records
`runtime.in` and `overrides.txt`, not the files they include: after you change `requirements-extra.txt` or
`requirements-overrides.txt`, move `lock.sha256` away and run `bootstrap --apply` to compile the locks again.

For example, the corpus-cafe 15.0 runtime above is an environment the user built before oasis,
`billing-o15` (Python 3.8), with `config/odoo-15/requirements-extra.txt` (the packages of its
e-invoicing modules) and `config/odoo-15/requirements-overrides.txt` (`cryptography==3.4.8`,
`pyopenssl==21.0.0`, `python-ldap==3.4.4`). With the same workspace file and the machine file's 15.0
entry:

```bash
cd corpus-cafe/codigo/facturacion
~/.agents/skills/odoo19/oasis setup --exception report_xlsx --environment <environments>/billing-o15
~/.agents/skills/odoo19/oasis setup --exception report_xlsx --environment <environments>/billing-o15 --apply
```

```text
add [series."15.0"] to <corpus-cafe>/oasis-workspace.toml:
  # Added by oasis setup: what differs for the Odoo 15.0 checkouts (docs/setup.md#another-odoo-series).
  [series."15.0"]
  environment = '<environments>/billing-o15'
  python = '3.8'
  config = 'config/odoo-15/odoo.conf'
  env_file = 'config/odoo-15/.env'
  compose = 'config/odoo-15/compose.yml'
  requirements = 'config/odoo-15/requirements'
  dev_prefix = 'cc15_dev_'
  test_prefix = 'cc15_test_'
  logs = 'logs/15.0'
  data_dir = 'data/15.0'
  series_exceptions = ['report_xlsx']
adopt <corpus-cafe>/config/odoo-15 (found): odoo.conf, compose.yml, .env, requirements-extra.txt, requirements-overrides.txt
kept <corpus-cafe>/config/odoo-15/odoo.conf
kept <corpus-cafe>/config/odoo-15/compose.yml
kept <corpus-cafe>/config/odoo-15/.env
create <corpus-cafe>/config/odoo-15/requirements/runtime.in: -r <15.0 source>/requirements.txt, setuptools<81, -r ../requirements-extra.txt
create <corpus-cafe>/config/odoo-15/requirements/dev.in: -c runtime.txt, -r runtime.in
create <corpus-cafe>/config/odoo-15/requirements/overrides.txt: -r ../requirements-overrides.txt (uv pip compile --override)
create <corpus-cafe>/logs/15.0/
create <corpus-cafe>/data/15.0/
compile <corpus-cafe>/config/odoo-15/requirements/runtime.txt, dev.txt and lock.sha256 with Python 3.8 (uv pip compile)
adopt the environment <environments>/billing-o15 (from --environment): Python 3.8 (its pyvenv.cfg); setup never creates, syncs or deletes it
```

After `--apply` the next steps start with `the locks in <corpus-cafe>/config/odoo-15/requirements describe
runtime.in, dev.in and overrides.txt: oasis --project <checkout> bootstrap --apply syncs the adopted
environment <environments>/billing-o15 to them (it changes the packages installed there)`.

### An existing environment

`--environment <dir>` uses an environment you already have instead of creating one, in a new workspace
or in a new [series section](#another-odoo-series) (an existing configuration refuses it, like the other
options: `--environment: <checkout> is already configured by <file>; setup only fills what is missing.`):

- `<dir>` is an absolute existing directory (`--environment requires an absolute existing directory.`)
  with a `pyvenv.cfg` (`--environment <dir> is not a Python environment (no pyvenv.cfg).`). Its Python is
  read from the `version` line of `pyvenv.cfg` (`version_info` as uv and virtualenv write it), never by
  running it, and must be one the series supports: `--environment <dir> has no Python version in its
  pyvenv.cfg (version or version_info).`, `--environment <dir> has Python 3.6, which Odoo 15.0 does not
  support (3.7 to 3.12).`
- The path is written relative to the workspace file's directory when it is below it, else absolute. In a
  series section it is that section's `environment`, with `python = '<3.minor>'` when its Python is not the
  series' default ([Workspace file](workspace-file.md#several-series-workspace_version-2)); in a new
  workspace it is `[tooling].environment`, or, for another Python, the `[environments.default]` table with
  its `path` and `python`.
- The plan says `adopt the environment <dir> (from --environment): Python <x.y> (its pyvenv.cfg); setup
  never creates, syncs or deletes it`. The locks are compiled with that Python; no `uv venv`, no `uv pip
  sync`, and a rollback after a failed compile never touches the environment.
- The next steps say that the locks describe the inputs and that `oasis --project <checkout> bootstrap
  --apply` syncs the adopted environment to them, which changes the packages installed there: read
  `bootstrap --preview` (its `uv pip sync --dry-run`) first.
- On a terminal, the path can also be the answer to the environment question
  ([below](#a-new-environment-and-its-python)): it is checked and adopted exactly as `--environment`, with
  the same refusals, and the plan line says `(answered)` instead of `(from --environment)`.

### A new environment and its Python

When setup would create the environment (a new workspace, or a new series section; not when the
environment's directory already has a `pyvenv.cfg`, which is kept) and neither `--environment` nor
`--python` is given, it asks on a terminal, in the plan and with `--apply` alike:

```text
Python environment for Odoo 15.0: Enter creates <corpus-cafe>/environments/corpus-cafe-15.0, or type the absolute path of an existing environment to use instead:
Python of the new environment <corpus-cafe>/environments/corpus-cafe-15.0, one of 3.7, 3.8, 3.9, 3.10, 3.11, 3.12 [Enter: 3.9]:
```

- A path [adopts that environment](#an-existing-environment), as `--environment` does; Enter creates the
  new one and asks its Python.
- The Pythons offered are every one the series supports (`python` in `tools/odoo_versions.py`); Enter takes
  the marked one, the Python the environment would get without the question (the series' `python_default`,
  or the `python` of a default named environment the series uses). Any other answer is asked again:
  `3.13 is not a Python Odoo 15.0 supports; answer one of 3.7, 3.8, 3.9, 3.10, 3.11, 3.12, or Enter for
  3.9.`
- Enter twice gives the same plan as without a terminal.

`--python <x.y>` gives that Python without asking, also without a terminal. It is refused (exit 2, nothing
changed) when the series does not support it (`--python 3.13 is not a Python Odoo 15.0 supports (3.7 to
3.12).`), with `--environment` (`--python cannot be combined with --environment: an adopted environment
keeps the Python of its pyvenv.cfg.`), when the environment already exists (`--python 3.8: the environment
<dir> exists and is kept; setup creates no environment, so drop --python.`), and in a checkout that is
already configured, like the other options (`--python: <checkout> is already configured by <file>; setup
only fills what is missing.`).

The chosen Python is the one of the plan's `compile ... with Python <x.y>` and `create the environment
<dir> with Python <x.y>` lines, of the locks and of `uv venv --python <x.y>`. When it is not the series'
default it is written to the configuration: in a series section as `python = '<x.y>'` (a series that
would use a default named environment of another Python also gets that environment's path as the
section's `environment`, so the section's `python` applies); in a new workspace as the
`[environments.default]` table with the environment's `path` and that `python`, instead of
`[tooling].environment`.

## The database account

oasis generates the PostgreSQL account of a workspace (one per series) and keeps it in one file, the
environment file (`[tooling].env_file`, by default `config/.env`; mode 0600). No oasis workflow requires
reading, copying or typing a password, and no command takes one as an argument or prints one (output,
logs, errors).

- A new environment file gets `ODOO_DB_USER=oasis_<name>` (`<name>` is the `dev_prefix` without `_dev_`:
  `oasis_shop`, `oasis_shop15` for a second series) and `ODOO_DB_PASSWORD=<32 random characters>`
  (`secrets.token_urlsafe(24)`: letters, digits, `-` and `_`). When a kept `odoo.conf` already sets
  `db_user` or `db_password`, the file gets that value instead, so Odoo and the service keep the account
  they used (quoted when docker compose would otherwise read it differently; a value it cannot hold either
  way is refused: `Cannot copy db_password of <odoo.conf> to <env file>: docker compose would not read its
  value as written; ...`). The user name is `oasis_` and the `dev_prefix` without its `_dev_` suffix (and
  any trailing `_`), so another prefix is never cut short.
- An existing environment file is kept, with one exception: the account variables it assigns an empty
  value (`NAME=`, `NAME=""`, also after `export` or before a ` # comment`, and `NAME= # comment` with only
  a comment; files written by older setups) get the same values a new file would (the kept `odoo.conf`'s, else generated), in place. Every other byte
  is kept and the file ends with mode 0600. The plan says `fill <names> in <env file> (mode 0600; every
  other line kept): <what each gets>`, never a value. A variable the file does not assign is never added:
  a file that assigns neither (another account's naming) is left unchanged, and the plan says `WARN: <env
  file> sets neither ODOO_DB_USER nor ODOO_DB_PASSWORD: setup leaves <env file> unchanged (an existing file
  is respected); to use the account oasis generates, add the empty lines ODOO_DB_USER= and
  ODOO_DB_PASSWORD= to it, then run oasis setup --apply` (doctor: `WARN env_file=unassigned` with the same
  fix). A file that assigns one of them and leaves the other out is kept as it is.
- An existing project's account moves to the environment file ("respects it and offers the move"): when
  a kept `odoo.conf` sets `db_user` or `db_password` (a value other than empty, `False` or `None`) and the
  environment file holds the same values, or gets them from `odoo.conf` in this run, the plan says
  `remove <options> from <odoo.conf> (those lines only): <env file> holds the same account, which oasis
  passes to Odoo`, and `--apply` removes those lines only, every other byte and the mode of `odoo.conf`
  kept: Odoo then gets the same account from the environment file, and the database is untouched. When
  the environment file holds another value or does not set one, the plan says
  `WARN: <env file> does not hold the account <odoo.conf> sets: <options> (another value|not set): both
  files kept, ...` and changes neither file; `doctor` reports it too (`WARN odoo_conf_password`). An option
  repeated, or continued on an indented line, is never edited (a `WARN` line says so).
- The compose service reads it: `docker compose --env-file <env file>` gives `POSTGRES_USER` and
  `POSTGRES_PASSWORD`, which PostgreSQL uses when it initializes a new volume, and the database commands
  run `psql`, `createdb` and `dropdb` in the service with it.
- Odoo reads the same file: `odoo.conf` stays path-free and password-free, and every command that starts
  Odoo (`start`, `restart`, `install-module`, `update-module`, `odoo-shell`, `test-module`,
  `verify-module`, `init-dev-database`) exports `ODOO_DB_USER` and `ODOO_DB_PASSWORD` as `PGUSER` and
  `PGPASSWORD`, which libpq reads when Odoo passes no user or password of its own; they never appear on
  Odoo's command line (`start --print-command` shows none). A `db_user` or `db_password` that `odoo.conf`
  sets (other than empty, `False` or `None`, which Odoo reads as unset) is kept, and that one is not
  exported, since Odoo 19 ranks `PGUSER` and `PGPASSWORD` above `odoo.conf`: an existing project keeps
  working unchanged. When either file cannot be read, nothing is exported and the command runs as before
  (`doctor` reports the file). oasis reads the environment file as docker compose does for literal values:
  unquoted (up to a ` # comment`), in single quotes, or in double quotes; `~` and `null` are those words
  (YAML does not apply to an environment file), and a value that is only a ` # comment` is empty, as
  `doctor` reports it and setup fills it (docker compose alone would read the comment as the value). A value
  Odoo would get that uses
  compose interpolation (`$VAR`, `${VAR}`, any `$` outside single quotes) or a double-quoted escape (`\`)
  is never passed on as written: the command exits 2 with `ERROR: <env file> sets <names> with compose
  interpolation ($) or a double-quoted escape (\), which oasis does not read: write the value literally in
  single quotes.`, and `doctor` and `check-environment` fail `env_file=unsupported_value <names>`, naming
  the variables, never the value.
- `doctor` and `check-environment --full` log in with that account (`postgres_connection`, see
  [The doctor report](checking-environment.md#the-doctor-report)). When the compose service refuses it,
  its volume was initialized with other credentials (the environment file changed after the service first
  started, or a volume from an older setup), and the fix is the Tier B
  `oasis --project <checkout> recreate-database-volume --confirm <compose project>`. That fix is named
  only when `odoo.conf` points at the compose service: `db_host` `127.0.0.1` or `localhost` and the
  `db_port` the compose file publishes to 5432 (5432 without a `db_port`). Another server refusing the
  account gets `correct that account on that server, or set db_host = 127.0.0.1 and the db_port <compose
  file> publishes in <odoo.conf>` instead: recreating the local volume would not change it. oasis reads the
  published port only from short entries such as `- '127.0.0.1:6001:5432'`; when the compose file cannot
  be read, publishes several ports to 5432, or has another entry for it (the long syntax `target: 5432`, a
  variable such as `${DB_PORT:-6001}:5432`, a range, no host port), the fix says that oasis could not read
  the port (`it cannot be read`, `several ports` or `an entry other than - [<address>:]<port>:5432`) and
  names both: the recreate if that server is the compose service, correcting the account if it is not.
- `recreate-database-volume` prints the plan, then runs `docker compose -p <compose project> down -v`:
  it removes the compose project's containers and networks, every named volume of its compose file and
  every anonymous volume of its containers, so every database of its PostgreSQL, the trash included
  (filestores under `data_dir` are not touched). Then it starts the service again with the same `-p`,
  which initializes a new volume with the account of the environment file. The compose project is always
  passed with `-p`; a `COMPOSE_PROJECT_NAME` in the environment or in the environment file that selects
  another project is refused before anything runs (`ERROR: COMPOSE_PROJECT_NAME ... makes docker compose
  use the compose project <other>, not <name> ...`), since the other oasis commands would keep using that
  one. Without `--confirm` and the compose project (the top-level `name:` of the compose file) it changes
  nothing and names the exact command. When `down -v` fails, or the service does not start again after
  it, the command exits 1, says the volume may already be gone (or is), and names the command that starts
  the service again: `docker compose --env-file <env file> -f <compose file> -p <compose project> up -d
  --wait <service>`.

## Next steps

After `--apply`, setup prints what is left, numbered, for example:

```text
next steps:
  1. docker compose --env-file <env file> -f <compose file> up -d --wait
  2. oasis --project <checkout> doctor
  3. add a [development] table with administrator_login to <workspace file> (docs/dev-database.md)
  4. oasis --project <checkout> init-dev-database <module> <name>_dev_manual
```

Nothing asks for an account: setup generated it ([The database account](#the-database-account)).
`bootstrap --apply` is added when setup compiled the locks of an environment it kept. With an
[adopted environment](#an-existing-environment) that step reads `the locks in <requirements> describe
runtime.in and dev.in (or runtime.in, dev.in and overrides.txt): oasis --project <checkout> bootstrap --apply
syncs the adopted environment <dir> to them (it changes the packages installed there)`. Then follow
[Development database](dev-database.md) and [Tests and test databases](testing.md).

## oasis setup and /oasis setup

They are different commands. `oasis setup` (this page) is the command-line tool that configures a
checkout. `/oasis setup` in Gentle Shell installs the subagent overlay (see
[Subagents](subagents.md)) and writes nothing in the project.
