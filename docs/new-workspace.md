# Setting up a new workspace

From a clone of the project's repository to a passing `oasis doctor` and a development database:
`oasis setup` writes the configuration with a generated database account, and you start the service.
No directory layout is required; by default everything stays in the clone. The project is the
fictional `acme`; replace its names, paths and module with your own. The reference of every
option of `setup` is [Setting up a checkout with oasis setup](setup.md), the reference of every
key is [Workspace file](workspace-file.md).

- [Before you start](#before-you-start): the tools and the Odoo source.
- [Quick path](#quick-path): seven steps, from the clone to a development database.
- [What setup writes](#what-setup-writes): the files in the clone and on the machine.
- [Where things go](#where-things-go): three settings files, worktrees, the environment.
- [The example tree](#the-example-tree): one possible layout, a folder per Odoo series.
- [By hand](#by-hand): what setup does for you, step by step.
- [Paths](#paths) and [Environments](#environments): the rules for the values.
- [Adding a worktree](#adding-a-worktree): a second checkout with its own databases.

## Before you start

| You need | Why |
| --- | --- |
| The `oasis` CLI, from [Install or update](install.md) | `~/.agents/skills/odoo19/oasis` below |
| git 2.31 or newer, Docker with its compose plugin, [uv](https://docs.astral.sh/uv/) | `doctor` checks git and Docker; `setup` and `bootstrap` run uv |
| The Odoo 19.0 source, and Enterprise if the project uses it | `setup` asks where it is once per machine |

Get the source into any folder; skip this when another project of this machine already uses it
(the [machine file](workspace-file.md#machine-file) then has it, and setup does not ask again).
Enterprise needs access to Odoo's private repository.

```bash
git clone --branch 19.0 --depth 1 https://github.com/odoo/odoo.git ~/odoo/19.0/source/odoo
git clone --branch 19.0 --depth 1 https://github.com/odoo/enterprise.git ~/odoo/19.0/source/enterprise
```

## Quick path

You or an agent run these: every step is Tier A in the [agent contract](agent-contract.md), so
an agent runs `setup --apply` alone (it creates only what is missing). Inside the clone no
`--project` is needed: the checkout is the git top level of the current directory.

1. Clone the repository (any folder).

   ```bash
   git clone <your repository> ~/src/acme
   cd ~/src/acme
   ```

2. Read the plan; nothing changes.

   ```bash
   ~/.agents/skills/odoo19/oasis setup
   ```

   It infers the series from the module manifests (`19.0.1.0.0` gives `19.0`) and the source
   from the machine file, and asks only what it cannot infer: on the first project of a machine,
   where the Odoo source is and whether Enterprise is used (`--community <dir>` and
   `--enterprise <dir>` or `--no-enterprise` answer without a terminal). Each piece is one
   `create <path>` or `kept <path>` line. Abridged:

   ```text
   checkout: /home/you/src/acme (main)
   series: 19.0 (from the module manifests)
   community: /home/you/odoo/19.0/source/odoo (answered)
   enterprise: none (answered)
   workspace: /home/you/src/acme (new)
   create /home/you/.config/oasis/config.toml (mode 0600):
   create /home/you/src/acme/oasis-workspace.toml (mode 0600):
   exclude /oasis-workspace.toml and /.oasis/ in /home/you/src/acme/.git/info/exclude (this clone only; .gitignore unchanged)
   create /home/you/src/acme/.oasis/config/odoo.conf (mode 0600): path-free; db_port 5432; db_user and db_password empty
   create /home/you/src/acme/.oasis/config/.env (mode 0600): ODOO_DB_USER oasis_acme and a generated ODOO_DB_PASSWORD
   dry run: nothing changed; run with --apply to set up
   ```

3. Apply it.

   ```bash
   ~/.agents/skills/odoo19/oasis setup --apply
   ```

   It creates only the `create` pieces (an existing file is never replaced), checks that the
   checkout loads its configuration, compiles the dependency locks, creates the Python
   environment and prints the next steps with your paths: steps 4 to 6 below. The database
   account is generated in the environment file, which the service and Odoo both read (see
   [The database account](setup.md#the-database-account)): nothing to fill in, and no step needs
   a password read, copied or typed. Never commit that file.

4. Start the database service.

   ```bash
   docker compose --env-file .oasis/config/.env -f .oasis/config/compose.yml up -d --wait
   ```

5. Run `doctor` until it prints `doctor_failures=0`. Each `FAIL` line is followed by a `fix:`
   line with the command or action that fixes it, and `PASS odoo_source_from=machine:<file>`
   shows where a value came from (see [The doctor report](checking-environment.md#the-doctor-report)).

   ```bash
   ~/.agents/skills/odoo19/oasis doctor
   ```

6. Create a development database. It needs a `[development]` table with an
   `administrator_login` in `oasis-workspace.toml` (setup writes none; see
   [the example tree](#the-example-tree) and [Development database](dev-database.md)), and the
   name must start with the `dev_prefix` (`acme_dev_`, from the checkout's name or
   `setup --name`). The passwords are generated into `.oasis/config/acme_dev_manual.logins`
   (mode 0600, never printed); on a terminal it asks each one with the echo off, and Enter
   generates it, so typing is only for your own. Then check the installed packages against the
   locks.

   ```bash
   ~/.agents/skills/odoo19/oasis init-dev-database acme_sale acme_dev_manual
   ~/.agents/skills/odoo19/oasis check-environment --full
   ```

Next, run a module's tests on a disposable database ([Tests and test databases](testing.md)):

```bash
~/.agents/skills/odoo19/oasis test-module --compact acme_sale
```

## What setup writes

Without an existing workspace file, the workspace is the clone itself. Both entries are added to
the clone's `.git/info/exclude`, so `git status` stays clean and the tracked `.gitignore` is not
touched.

```text
~/.config/oasis/config.toml        machine file: the Odoo source of 19.0, for every project
~/src/acme/                        the clone (main checkout)
├── oasis-workspace.toml           workspace file: every checkout of acme reads it
├── .oasis/
│   ├── config/
│   │   ├── .env                   the generated database account: ODOO_DB_USER, ODOO_DB_PASSWORD (0600)
│   │   ├── odoo.conf              path-free and password-free: db_user and db_password empty (0600)
│   │   ├── compose.yml            PostgreSQL 17 on 127.0.0.1, the port odoo.conf connects to
│   │   └── requirements/          runtime.in, dev.in, runtime.txt, dev.txt, lock.sha256
│   ├── data/                      Odoo data directory (filestores)
│   ├── logs/                      compact runs: main/, then one folder per worktree slug
│   └── venv/                      the Python 3.12 environment
└── acme_sale/                     a module of the project
```

Run `setup` again at any time: it prints `kept` for what exists and creates only what is missing
(`nothing to set up` when nothing is). Every piece and its contents are in
[What it creates and what it keeps](setup.md#what-it-creates-and-what-it-keeps). In a checkout of
another Odoo series (a 15.0 branch of a 19.0 project), it adds that series' section to the same
workspace file instead: see [Another Odoo series](setup.md#another-odoo-series).

## Where things go

Each value lives in one place. A lower level overrides the one above it, and `doctor` names where
each layered value came from.

| Level | File | Holds | Where |
| --- | --- | --- | --- |
| Machine | `~/.config/oasis/config.toml` ([machine file](workspace-file.md#machine-file)) | The Odoo source of each series (`community`, `enterprise`) and, optionally, the folder for new environments (`environments`) | `$XDG_CONFIG_HOME/oasis/`; written by setup the first time |
| Project | `oasis-workspace.toml` ([workspace file](workspace-file.md)) | Database prefixes, compose file, `odoo.conf`, environment file, requirements, logs, data, the environment; a source only to override the machine's | The clone's root by default; `setup --workspace <dir>` for any directory at or above the clone; an existing file above the clone is adopted |
| Checkout | `oasis-checkout.toml`, optional ([checkout file](workspace-file.md#checkout-file-and-named-environments)) | `checkout_slug` and the chosen named `environment` | The checkout's root |

- Worktrees: a checkout reads the nearest `oasis-workspace.toml` at or above it; a linked worktree
  with none above it reads its main checkout's, found through git, so it can live in any folder.
  Its slug, and so its databases, port and logs, comes from its own folder name
  ([Checkouts and worktrees](checkouts-and-worktrees.md)).
- The Python environment: any folder that is a Python environment (it has `pyvenv.cfg`) or does
  not exist yet, except the checkout, the Odoo source or a folder that contains either
  ([The Python environment](#the-python-environment)). Setup puts it in `.oasis/venv`, or in
  `<environments>/<name>` when the machine file's entry sets `environments`.

## The example tree

One possible layout, not a requirement: a series folder holds what every Odoo 19.0 project shares
(the source and the environments), and each project keeps its checkouts, configuration, data and
logs below its own folder. Here the series folder is `~/odoo/19.0`; any folder works.

```text
~/odoo/19.0/                          series folder: shared by every 19.0 project
├── source/
│   ├── odoo/                         Odoo Community source, branch 19.0        machine community
│   └── enterprise/                   optional Odoo Enterprise source           machine enterprise
├── environments/                     machine environments
│   ├── acme/                         Python 3.12 environment of acme           environment
│   └── acme-next/                    optional second environment (Python 3.13) [environments.next]
└── projects/
    └── acme/                         the workspace directory
        ├── oasis-workspace.toml      the workspace file: its paths start here
        ├── codigo/
        │   ├── acme/                 main checkout (git): the modules          addons_paths '.'
        │   │   └── acme_sale/        a module of the project
        │   └── acme-shop-feature/    linked worktree of acme, slug shop_feature
        │       └── oasis-checkout.toml  optional: the slug or environment of this checkout
        ├── config/                   .env, odoo.conf, compose.yml, requirements/
        ├── data/                     Odoo data directory (filestores)          data_dir
        └── logs/                     main/ and shop_feature/: compact runs     logs
```

With the clone in `codigo/acme`, setup builds the rest. Write the machine file's `environments`
first, by hand (setup only reads it), so the environment goes to the series folder:

```toml
# ~/.config/oasis/config.toml
[series."19.0"]
community = '/home/you/odoo/19.0/source/odoo'
# enterprise = '/home/you/odoo/19.0/source/enterprise'
environments = '/home/you/odoo/19.0/environments'
```

```bash
cd ~/odoo/19.0/projects/acme/codigo/acme
~/.agents/skills/odoo19/oasis setup --workspace ~/odoo/19.0/projects/acme
~/.agents/skills/odoo19/oasis setup --workspace ~/odoo/19.0/projects/acme --apply
```

With `--workspace`, `config/`, `data/` and `logs/` go directly under that directory, and nothing
is added to `.git/info/exclude`. The workspace file it writes, after the `[development]` table you
add for `init-dev-database`; it names no source, which comes from the machine file:

```toml
# projects/acme/oasis-workspace.toml
workspace_version = 1
odoo_version = '19.0'

[tooling]
environment = '/home/you/odoo/19.0/environments/acme'
config = 'config/odoo.conf'
env_file = 'config/.env'
compose = 'config/compose.yml'
requirements = 'config/requirements'
addons_paths = ['.']
db_service = 'db'
dev_prefix = 'acme_dev_'
test_prefix = 'acme_test_'
logs = 'logs'
data_dir = 'data'

[development]
administrator_login = 'acme_admin'

[[development.users]]
login = 'acme_sales'
name = 'Acme Sales User'
groups = ['sales_team.group_sale_salesman']
```

Relative paths resolve from `projects/acme/`, where the file is; `addons_paths` resolves from each
checkout, so `'.'` is `codigo/acme` for the main checkout and `codigo/acme-shop-feature` for the
worktree. `logs/main/` and `logs/shop_feature/` are created on the first compact run.

## By hand

What setup does for you, for a layout you build yourself or to understand what it creates. The
steps write [the example tree](#the-example-tree); any other folders work the same way.

| Piece | Setup | By hand |
| --- | --- | --- |
| Odoo source of the series | Asks once, writes the machine file | [Step 1](#steps) |
| Workspace file | Writes it without a source; excludes it from git in the clone | [Step 2](#steps) |
| `odoo.conf`, compose file, environment file | Path-free, one free port for both, names only | [Step 3](#steps) |
| Requirement inputs and locks | `runtime.in`, `dev.in`, then compiled | [Step 4](#steps) |
| Python environment | `uv venv` and `uv pip sync` with the series' Python | [Step 5](#steps) |

### Steps

1. Declare the source once per machine. The machine file is read only when it and its folder are
   yours and not writable by group or others.

   ```bash
   mkdir -p -m 700 ~/.config/oasis
   ${EDITOR:-vi} ~/.config/oasis/config.toml    # the [series."19.0"] table of the example tree
   chmod 600 ~/.config/oasis/config.toml
   ```

2. Write `oasis-workspace.toml` as in [the example tree](#the-example-tree), at or above the
   checkouts (or in the main checkout: then list it in `.git/info/exclude`, as setup does, since
   [worktree-init](checkouts-and-worktrees.md#worktree-init) refuses a tracked one). The same trust
   rule applies.

   ```bash
   mkdir -p ~/odoo/19.0/projects/acme/{config/requirements,data,logs}
   chmod go-w ~/odoo/19.0/projects/acme ~/odoo/19.0/projects/acme/oasis-workspace.toml
   ```

3. Write the database service and its account. The compose file needs a top-level `name:`
   (`doctor` checks it); oasis runs it as `docker compose --env-file <env_file> -f <compose>` and
   runs `psql` and `createdb` in the service as `ODOO_DB_USER` with `ODOO_DB_PASSWORD`, on
   `POSTGRES_DB`, so the service carries those variables. `odoo.conf` is
   [path-free](path-free-odoo-conf.md): no `addons_path`, `data_dir` or `db_name`, because oasis
   passes `--addons-path` and `--data-dir` and every checkout shares the file; its `db_port` is
   the port the compose file publishes. It is password-free too: with `db_user` and `db_password`
   empty, every oasis command that starts Odoo gives it the account of the environment file
   ([The database account](setup.md#the-database-account)).

   ```yaml
   # projects/acme/config/compose.yml
   name: acme
   services:
     db:
       image: postgres:17
       environment:
         POSTGRES_DB: postgres
         POSTGRES_USER: ${ODOO_DB_USER}
         POSTGRES_PASSWORD: ${ODOO_DB_PASSWORD}
         ODOO_DB_USER: ${ODOO_DB_USER}
         ODOO_DB_PASSWORD: ${ODOO_DB_PASSWORD}
       ports:
         - '127.0.0.1:5432:5432'
       volumes:
         - db:/var/lib/postgresql/data
       healthcheck:
         test: ['CMD-SHELL', 'pg_isready -U "$${POSTGRES_USER}" -d postgres']
         interval: 2s
         retries: 30
   volumes:
     db:
   ```

   ```ini
   ; projects/acme/config/odoo.conf; Odoo gets the account of config/.env
   [options]
   db_host = 127.0.0.1
   db_port = 5432
   db_user =
   db_password =
   ```

   The environment file holds the database account, one `NAME=value` per line. Generate the
   password straight into the file, so it is never shown (or let `oasis setup --apply` write the
   whole file):

   ```bash
   cd ~/odoo/19.0/projects/acme/config
   (umask 077 && printf 'ODOO_DB_USER=oasis_acme\nODOO_DB_PASSWORD=%s\n' \
     "$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')" > .env)
   chmod 600 odoo.conf
   ```

4. Write the dependency inputs, lock them and fingerprint the locks. `runtime.in` takes Odoo's
   requirements, `dev.in` adds the development tools within the same versions. `python` is the
   Python the workspace declares: 3.12 for `[tooling].environment`, or the `python` of a named
   environment (see [Environments](#environments)).

   ```bash
   python=3.12
   cd ~/odoo/19.0/projects/acme/config/requirements
   printf -- '-r /home/you/odoo/19.0/source/odoo/requirements.txt\n' > runtime.in
   printf -- '-c runtime.txt\n-r runtime.in\npylint\n' > dev.in
   uv pip compile --python-version "$python" runtime.in -o runtime.txt
   uv pip compile --python-version "$python" dev.in -o dev.txt
   sha256sum runtime.in runtime.txt dev.in dev.txt > lock.sha256
   ```

   Only `runtime.in` and `dev.in` are yours to write: `bootstrap --apply` runs the last three
   commands itself when the locks are missing or stale (see
   [Dependency locks](checking-environment.md#dependency-locks)).

5. Create the environment with the same `python` and install the locked packages. Once steps 1
   to 4 are done, `oasis bootstrap --apply` does the same and ends with `check-environment --full`
   (`bootstrap --preview` shows the plan).

   ```bash
   python=3.12
   uv venv --python "$python" ~/odoo/19.0/environments/acme
   uv pip sync --python ~/odoo/19.0/environments/acme/bin/python \
     ~/odoo/19.0/projects/acme/config/requirements/dev.txt
   ```

Then continue with [step 4 of the quick path](#quick-path): start the database service, run
`doctor` (`PASS configuration=workspace` shows the workspace file was found and accepted) and
create a development database.

## Paths

- A relative path in the workspace file resolves from its directory, and may go up with `..`.
  The exception is `addons_paths`: each entry resolves from the checkout, so `'.'` is every
  checkout's own folder. A relative path in the machine file resolves from the machine file's
  directory.
- An absolute path is accepted for every path key (`community`, `enterprise`, `environment`,
  `config`, `env_file`, `compose`, `requirements`, `logs`, `data_dir`, `addons_paths`, the
  `path` of a named environment) and used as written. An absolute addon root is the same folder
  for every checkout.
- `~` and `$HOME` are not expanded: TOML values are taken literally, so `'~/odoo/19.0/source/odoo'`
  is a folder named `~` inside the workspace directory. Write the full path.
- An empty value, or one that is not a string, is refused with `Invalid tooling path: <key>.`

The example tree's paths, written the other way round (the same folders):

```toml
# Example only: [tooling] paths of projects/acme/oasis-workspace.toml.
environment = '../../environments/acme'
config = '/home/you/odoo/19.0/projects/acme/config/odoo.conf'
logs = '/home/you/odoo/19.0/projects/acme/logs'
```

### The Python environment

The environment's folder (`[tooling].environment`, or the `path` of a named environment), once
resolved, may be any folder, with any name and in any place, that is a Python environment (it
has `pyvenv.cfg`, as every `uv venv` or `python -m venv` environment does) or does not exist yet
(`bootstrap` creates it). Two guards stay, even for a folder with `pyvenv.cfg`: it may not be or
contain the checkout, and it may not be or contain the Odoo source. Anything else stops every
command with one of:

- `Unsafe tooling environment target: <folder> is or contains the checkout <checkout>.`
- `Unsafe tooling environment target: <folder> is or contains the Odoo source <source>.`
- `Unsafe tooling environment target: <folder> exists and is not a Python environment (no pyvenv.cfg).`

| Value | Result |
| --- | --- |
| `'../../environments/acme'` | accepted: an environment (it has `pyvenv.cfg`), or not created yet |
| `'/home/you/odoo/19.0/environments/acme'` | accepted: absolute, the same folder |
| `'/opt/venvs/acme'` | accepted: any folder name, once it is an environment or before it exists |
| `'../../environments/acme-new'` | accepted: it does not exist yet; `bootstrap` creates it |
| `'codigo/acme/.venv'` | accepted: inside the main checkout, and the linked worktrees may use it too |
| `'../../environments'` | refused: it exists and is not an environment (it holds them) |
| `'../../source/odoo'` | refused: it is the Odoo source |
| `'../../source'` | refused: it contains the Odoo source |
| `'.'` or `'codigo'` | refused: it contains the checkout |

A folder you create by hand before `bootstrap` (an empty `mkdir`) is refused until it is an
environment: leave it to `bootstrap`, or create it with `uv venv`.

## Environments

Either one environment for every checkout, or named environments that each checkout chooses
from; not both in the same file (`Set either [tooling].environment or [environments] in <file>, not both.`).

- One environment: `[tooling].environment`, as in the example tree. Its Python is 3.12.
- Named environments: `[environments.<name>]` tables with a `path` (the same rules as
  `[tooling].environment`) and a `python` within the range of Odoo 19.0 (3.10 to 3.14). A
  checkout uses `default`, unless its `oasis-checkout.toml` names another one.

```toml
# In oasis-workspace.toml, in place of [tooling].environment:
[environments.default]
path = '../../environments/acme'
python = '3.12'

[environments.next]
path = '../../environments/acme-next'
python = '3.13'
```

```toml
# codigo/acme-shop-feature/oasis-checkout.toml
[tooling]
environment = 'next'
```

With these, the main checkout uses `environments/acme` and the worktree `environments/acme-next`;
`bootstrap` creates each one with its `python`, and `doctor` and `check-environment` check that
its interpreter reports it. Create the second environment as in [step 5](#steps) with
`python=3.13`, or run `bootstrap --apply` in the worktree. `oasis-checkout.toml` may set only
`checkout_slug` and `environment`; see [Workspace file](workspace-file.md#checkout-file-and-named-environments).

## Adding a worktree

`worktree-init` only runs `git worktree add`: the new folder reads the same workspace file (above
it, or through git), gets the slug `shop_feature` and its own databases, port and logs (see
[Checkouts and worktrees](checkouts-and-worktrees.md)). By default the folder is
`<main checkout>-<feature>` next to the main checkout; `--path <dir>` puts it anywhere else.
`--dry-run` prints the plan first.

```bash
~/.agents/skills/odoo19/oasis worktree-init shop-feature shop-feature --dry-run
~/.agents/skills/odoo19/oasis worktree-init shop-feature shop-feature
~/.agents/skills/odoo19/oasis --project ~/src/acme-shop-feature doctor
```

In Gentle Shell, `/oasis worktree shop-feature shop-feature` shows the same plan and asks before
creating anything.
