# Setting up a new workspace

From an empty folder to a checkout where `oasis doctor` passes, a development database and a
first test run, with one `oasis-workspace.toml` for every checkout of the project. The project
is the fictional `acme`; replace its names, paths and module with your own. The reference for
every key is [Workspace file](workspace-file.md).

- [The example tree](#the-example-tree): every folder and the workspace file that points at it.
- [Steps](#steps): the commands, in order.
- [Paths](#paths): relative and absolute values, and the rule for the Python environment.
- [Environments](#environments): one environment, or named ones chosen per checkout.

## The example tree

One series folder holds what every project of Odoo 19.0 shares (the Odoo source and the Python
environments); each project keeps its checkouts, configuration, data and logs below its own
folder. Here the series folder is `~/odoo/19.0`; any folder works.

```text
~/odoo/19.0/                          series folder: shared by every 19.0 project
├── source/
│   ├── odoo/                         Odoo Community source, branch 19.0        community
│   └── enterprise/                   optional Odoo Enterprise source           enterprise
├── environments/
│   ├── acme/                         Python 3.12 environment of acme           environment
│   └── acme-next/                    optional second environment (Python 3.13) [environments.next]
└── projects/
    └── acme/                         the workspace directory
        ├── oasis-workspace.toml      the workspace file: every path below starts here
        ├── codigo/
        │   ├── acme/                 main checkout (git): the modules          addons_paths '.'
        │   │   └── acme_sale/        a module of the project
        │   └── acme-shop-feature/    linked worktree of acme, slug shop_feature
        │       └── oasis-checkout.toml  optional: the slug or environment of this checkout
        ├── config/
        │   ├── .env                  environment file: database user and password   env_file
        │   ├── odoo.conf             path-free Odoo configuration              config
        │   ├── compose.yml           the PostgreSQL service                    compose
        │   └── requirements/         runtime.in, runtime.txt, dev.in, dev.txt, lock.sha256
        ├── data/                     Odoo data directory (filestores)          data_dir
        └── logs/                     compact runs and browser evidence         logs
            ├── main/                 the main checkout's runs
            └── shop_feature/         the linked worktree's runs
```

The matching workspace file; each path is relative to `projects/acme/`, where the file is:

```toml
# projects/acme/oasis-workspace.toml
workspace_version = 1
odoo_version = '19.0'

[tooling]
community = '../../source/odoo'
# enterprise = '../../source/enterprise'
environment = '../../environments/acme'
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

`addons_paths` is the only path that resolves from each checkout: `'.'` is `codigo/acme` for the
main checkout and `codigo/acme-shop-feature` for the worktree. `logs/main/` and
`logs/shop_feature/` are created on the first compact run.

## Steps

The commands run in a terminal, by you. `~/.agents/skills/odoo19/oasis` is the installed entry
point (see [Install or update](install.md)); `--project` always takes the absolute path of a
checkout.

1. Create the folders.

   ```bash
   mkdir -p ~/odoo/19.0/source ~/odoo/19.0/environments
   mkdir -p ~/odoo/19.0/projects/acme/{codigo,config/requirements,data,logs}
   ```

2. Get the Odoo source, and Enterprise if the project uses it (it needs access to Odoo's
   private repository). Set `enterprise` in the workspace file only when you have it.

   ```bash
   git clone --branch 19.0 --depth 1 https://github.com/odoo/odoo.git ~/odoo/19.0/source/odoo
   git clone --branch 19.0 --depth 1 https://github.com/odoo/enterprise.git ~/odoo/19.0/source/enterprise
   ```

3. Get the main checkout: clone the project's repository, or start a new one.

   ```bash
   git clone <your repository> ~/odoo/19.0/projects/acme/codigo/acme
   # or: git init ~/odoo/19.0/projects/acme/codigo/acme
   ```

4. Write the dependency inputs, lock them and fingerprint the locks. `runtime.in` takes Odoo's
   requirements (the `-r` path is relative to the `.in` file), `dev.in` adds the development
   tools within the same versions. `python` is the Python the workspace declares for the
   environment: 3.12 for `[tooling].environment`, as here, or the `python` of a named
   environment (see [Environments](#environments)).

   ```bash
   python=3.12
   cd ~/odoo/19.0/projects/acme/config/requirements
   printf -- '-r ../../../../source/odoo/requirements.txt\n' > runtime.in
   printf -- '-c runtime.txt\n-r runtime.in\npylint\n' > dev.in
   uv pip compile --python-version "$python" runtime.in -o runtime.txt
   uv pip compile --python-version "$python" dev.in -o dev.txt
   sha256sum runtime.in runtime.txt dev.in dev.txt > lock.sha256
   ```

   Only `runtime.in` and `dev.in` are yours to write: `bootstrap --apply` (step 5) runs the
   last three commands itself, with the declared Python, when the locks are missing or no
   longer match their inputs, and leaves current locks byte-identical (see
   [Dependency locks](checking-environment.md#dependency-locks)).

5. Create the Python environment, with the same `python`, and install the locked packages into
   it. The environment's folder may be any folder the
   [environment rule](#the-python-environment) accepts; here it sits in `environments/`. Each
   block sets `python` itself, so it also works in a new shell.

   ```bash
   python=3.12
   uv venv --python "$python" ~/odoo/19.0/environments/acme
   uv pip sync --python ~/odoo/19.0/environments/acme/bin/python \
     ~/odoo/19.0/projects/acme/config/requirements/dev.txt
   ```

   Once steps 6 to 8 are done, `oasis --project <checkout> bootstrap --preview` shows the same
   plan and `bootstrap --apply` carries it out: it compiles the locks of step 4 when they are
   missing or stale (the preview then says `planned_action=compile_locks_then_...`), creates the
   environment with the declared Python, syncs `dev.txt`, saves the packages it found before as
   `bootstrap-before.txt` in the checkout's log directory (`logs/main/` here), and ends with
   `check-environment --full`, which needs the database service running.

6. Write the compose file and the environment file. The compose file needs a top-level `name:`
   (`doctor` checks it); oasis runs it as `docker compose --env-file <env_file> -f <compose>`
   and runs `psql` and `createdb` in the service as `ODOO_DB_USER` with `ODOO_DB_PASSWORD`, on
   `POSTGRES_DB`, so the service must carry those variables.

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

   ```text
   # projects/acme/config/.env: choose your own local password; never commit this file.
   ODOO_DB_USER=odoo
   ODOO_DB_PASSWORD=<a local password>
   ```

7. Write a path-free `odoo.conf`: no `addons_path` and no `data_dir`, because oasis passes
   `--addons-path` (from `enterprise`, each checkout's `addons_paths` and `community`) and
   `--data-dir` on the command line (see [Path-free odoo.conf](path-free-odoo-conf.md)). Leave
   out `db_name` too: every checkout shares this file.

   ```ini
   ; projects/acme/config/odoo.conf
   [options]
   db_host = 127.0.0.1
   db_port = 5432
   db_user = odoo
   db_password = <the password of config/.env>
   http_port = 8069
   ```

   ```bash
   chmod 600 ~/odoo/19.0/projects/acme/config/.env ~/odoo/19.0/projects/acme/config/odoo.conf
   ```

8. Write `projects/acme/oasis-workspace.toml` as in [the example tree](#the-example-tree). oasis
   reads it only when the file and its folder are yours and not writable by group or others.

   ```bash
   chmod go-w ~/odoo/19.0/projects/acme ~/odoo/19.0/projects/acme/oasis-workspace.toml
   ```

9. Run `doctor` until it prints `doctor_failures=0`, fixing the first `FAIL` each time (the
   checks and their messages are in [Checking the environment](checking-environment.md)); then
   run the quick environment check.

   ```bash
   ~/.agents/skills/odoo19/oasis --project ~/odoo/19.0/projects/acme/codigo/acme doctor
   ~/.agents/skills/odoo19/oasis --project ~/odoo/19.0/projects/acme/codigo/acme check-environment --quick
   ```

   `PASS configuration=workspace` shows that the workspace file was found and accepted.
   `--quick` checks the requirement files and their fingerprint, the environment's Python (the
   declared one), the virtualenv, uv, the Odoo version and the compose file; it skips the
   installed packages, the dependency audit and PostgreSQL (`SKIP ...=use_--full`).

10. Create a development database with the role accounts of `[development]`; it asks for each
    password with the echo off (see [Development database](dev-database.md)). The name must start
    with `dev_prefix`. It starts the database service, so `check-environment --full` can then
    check the installed packages against the locks (`dev.txt`), audit the dependencies and query
    PostgreSQL.

    ```bash
    ~/.agents/skills/odoo19/oasis --project ~/odoo/19.0/projects/acme/codigo/acme init-dev-database acme_sale acme_dev_manual
    ~/.agents/skills/odoo19/oasis --project ~/odoo/19.0/projects/acme/codigo/acme check-environment --full
    ```

11. Run the module's tests on a disposable database, with a compact summary (see
    [Tests and test databases](testing.md)).

    ```bash
    ~/.agents/skills/odoo19/oasis --project ~/odoo/19.0/projects/acme/codigo/acme test-module --compact acme_sale
    ```

12. Add a linked worktree for a feature. In a workspace, `worktree-init` only runs
    `git worktree add`: the new folder `codigo/acme-shop-feature` reads the same workspace file,
    gets the slug `shop_feature` and its own databases, port and logs (see
    [Checkouts and worktrees](checkouts-and-worktrees.md)). `--dry-run` prints the plan first.

    ```bash
    ~/.agents/skills/odoo19/oasis --project ~/odoo/19.0/projects/acme/codigo/acme worktree-init shop-feature shop-feature --dry-run
    ~/.agents/skills/odoo19/oasis --project ~/odoo/19.0/projects/acme/codigo/acme worktree-init shop-feature shop-feature
    ~/.agents/skills/odoo19/oasis --project ~/odoo/19.0/projects/acme/codigo/acme-shop-feature doctor
    ```

    In Gentle Shell, `/oasis worktree shop-feature shop-feature` shows the same plan and asks
    before creating anything.

## Paths

- A relative path resolves from the directory of `oasis-workspace.toml`, and may go up with
  `..` (`'../../source/odoo'` above). The exception is `addons_paths`: each entry resolves
  from the checkout, so `'.'` is every checkout's own folder.
- An absolute path is accepted for every path key (`community`, `enterprise`, `environment`,
  `config`, `env_file`, `compose`, `requirements`, `logs`, `data_dir`, `addons_paths`, the
  `path` of a named environment) and used as written. An absolute addon root is the same folder
  for every checkout.
- `~` and `$HOME` are not expanded: TOML values are taken literally, so `'~/odoo/19.0/source/odoo'`
  is a folder named `~` inside the workspace directory. Write the full path.
- An empty value, or one that is not a string, is refused with `Invalid tooling path: <key>.`

The tree above, written with absolute paths instead (the same files):

```toml
# Example only: the [tooling] paths of projects/acme/oasis-workspace.toml, absolute.
community = '/home/you/odoo/19.0/source/odoo'
environment = '/home/you/odoo/19.0/environments/acme'
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
its interpreter reports it. Create the second environment as in step 5 with `python=3.13`, or
run `bootstrap --apply` in the worktree. `oasis-checkout.toml` may set only
`checkout_slug` and `environment`; see [Workspace file](workspace-file.md#checkout-file-and-named-environments).
