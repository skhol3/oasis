# Checkouts and worktrees

Each checkout of a project (the main checkout and every linked git worktree) gets its own
databases, server, port and logs. The PostgreSQL service is one and shared.

```mermaid
flowchart TD
    D["Checkout directory"] --> G{"git rev-parse"}
    G -->|"main checkout"| M["kind main, no slug"]
    G -->|"linked worktree"| L["kind linked, slug from the folder name"]
    G -->|"outside git"| N["kind none, no slug"]
    S["oasis-checkout.toml [tooling].checkout_slug"] -.->|"sets the slug of any checkout,<br/>the main one included"| L
    M --> MDB["Databases: dev_prefix + name, test_prefix + name"]
    N --> MDB
    L --> LDB["Databases: dev_prefix + slug_ + name,<br/>test_prefix + slug_ + name"]
    M --> MP["Port: http_port of odoo.conf (8069 when absent)"]
    N --> MP
    L --> LP["Port: first free from http_port + 1 to http_port + 50,<br/>and a free --gevent-port"]
    M --> ML["Logs: dev/logs/odoo19, or [tooling].logs/main"]
    N --> ML
    L --> LL["Logs: its dev/logs/odoo19 (may link to the main checkout's),<br/>or [tooling].logs/slug"]
    D --> REC["Server record: runtime directory / sha256 of the checkout path / server.json"]
```

- [Checkout identity](#checkout-identity): kind and slug.
- [Databases per checkout](#databases-per-checkout): the namespace each checkout may use.
- [Preparing a linked worktree](#preparing-a-linked-worktree): where the workspace file can be and `worktree-init`.
- [Servers and ports per checkout](servers-and-ports.md): one server per checkout.

## Checkout identity

Each checkout of a project gets an identity derived from the folder it runs in, so linked git worktrees (for example the ones Gentle Shell creates for sessions) can later get their own runtime resources. oasis keeps no registry: it runs a read-only `git rev-parse` in the project root and the same folder always gives the same identity.

- The main checkout has kind `main` and no slug. A project outside git has kind `none` and no slug.
- When git cannot report the checkout (not installed, a timeout after 5 s, a non-zero exit, unexpected output; git 2.31 or later is needed for `--path-format`), the reader looks for the first `.git` entry at or above the project root, as git does (ancestors in `GIT_CEILING_DIRECTORIES` are not entered). Without one, the project is outside git (kind `none`). A `.git` file (a linked worktree's gitfile) stops every command with `Cannot determine the checkout identity: git failed in a linked worktree; check git or set [tooling].checkout_slug.` (exit 2), so the worktree never loses its namespace guard; with `checkout_slug` set in its `oasis-checkout.toml` it continues as kind `linked` with that slug, but the main checkout is then unknown (`CHECKOUT_MAIN_ROOT` is empty): commands that start Odoo use an `odoo.conf` inside the worktree as it is and refuse a shared one (`Cannot move the addons_path of <path> to this worktree: git failed, so the main checkout is unknown.`), and compact logs cannot link into the main checkout. A `.git` directory stops every command with `Cannot determine the checkout identity: git failed (<reason>).`, whatever the checkout file sets.
- A linked worktree has kind `linked` and a slug from its directory name. When the name starts with the main checkout's directory name followed by `-`, `_` or `.`, that prefix is dropped. The rest is lowercased and every run of other characters than `a-z` and `0-9` becomes `_`, trimmed at both ends: `acme-shop-feature` next to `acme` gives `shop_feature`, `Feature Branch!` gives `feature_branch`.
- The slug must be 1-20 characters of `a-z`, `0-9` and `_`, starting with a letter or digit. When a name cannot produce one (empty or too long), the reader fails and asks for `[tooling].checkout_slug`.
- Optional `[tooling].checkout_slug` in the checkout's own `oasis-checkout.toml` overrides the slug for that checkout, including the main one (opt-in suffix); the reported kind stays the real one. The workspace file refuses the key, since every checkout reads it. An empty value is invalid: omit the key instead.

```toml
# <checkout>/oasis-checkout.toml, example only.
[tooling]
checkout_slug = 'mrp_2'
```

`/oasis` shows it as `checkout: main`, `checkout: linked worktree, slug shop_feature` or `checkout: main, slug mrp_2 (oasis-checkout.toml)`. The slug selects the checkout's database names (below); the checkout's directory selects its server and port (see [Servers and ports per checkout](servers-and-ports.md)).

## Databases per checkout

The slug goes right after the managed prefix, so each checkout has its own database namespace. A checkout without a slug (the main checkout, unless its `oasis-checkout.toml` sets `checkout_slug`) keeps the previous names.

| Default | Main checkout | Checkout with slug `shop_feature` |
| --- | --- | --- |
| `install-module` target | `<dev_prefix><module>` | `<dev_prefix>shop_feature_<module>` |
| `test-module` and `verify-module` test target (disposable, new per run) | `<test_prefix><module>_r<6 hex>` | `<test_prefix>shop_feature_<module>_r<6 hex>` |
| `verify-module` update target (disposable) | `<test_prefix><module>_r<6 hex>_update` | `<test_prefix>shop_feature_<module>_r<6 hex>_update` |
| `verify-module` update target with only an explicit test database | `<test_prefix><module>_update` | `<test_prefix>shop_feature_<module>_update` |
| configured `test_database = '<test_prefix>shared'` | `<test_prefix>shared` | `<test_prefix>shop_feature_shared` (its sibling `<test_prefix>shop_feature_shared_update`) |

Every command that takes a database (`install-module` with or without `--with-demo`, `update-module`, `odoo-shell`, `start` with `-d`/`--database`, `test-module`, `verify-module`, `create-database`, `drop-database`, `module-status`, `init-dev-database`) requires a managed `<dev_prefix><name>` or `<test_prefix><name>` name; all of them except `drop-database` and `module-status` refuse names ending in the reserved disposable run suffix `_r<6 hex>` (see [Disposable test databases](disposable-test-databases.md)), and all of them refuse names ending in the reserved trash suffix `_trash_<YYYYMMDD>_<HHMMSS>` (see [Database trash](trash.md)). `drop-database` moves the database and its filestore to the trash instead of dropping it; `trash restore` brings it back and `gc --apply --trash` drops it after 7 days. In a checkout with a slug the name must also start with `<dev_prefix><slug>_` or `<test_prefix><slug>_`, so a linked worktree cannot touch the main checkout's databases or another worktree's. The rejection names the checkout and the expected prefixes, and nothing runs.

Not guarded: `start` without `-d`/`--database` uses whatever `db_name` and `--db-filter` the project's `odoo.conf` sets, so keep `db_name` out of a linked worktree's `odoo.conf` and out of an `odoo.conf` shared by several checkouts. Slugs are matched as prefixes: give each worktree a slug that is not the start of another (`wt` would also accept `wt_1`'s databases).

Database names are at most 63 bytes (PostgreSQL's identifier limit, counted in UTF-8 bytes). A test database that gets an `_update` sibling in `verify-module` is at most 56 bytes, and a configured `test_database` must fit in 56 bytes after the slug is inserted. Longer names fail before any database command; disposable names are shortened to fit instead.

`update-module [--compact] <module> <database>` and `odoo-shell` work on existing databases only: a missing database exits 2 with `Database <name> does not exist; create it with install-module or create-database.` and is never created. `install-module` and `create-database` still create their target. `update-module --compact` keeps stdout and stderr in a new run directory of the logs directory and prints `phase=update database=<name> exit=<n>`, `stdout_log=<path>` and `stderr_log=<path>`; a refusal happens before any log is written. oasis never drops a checkout's databases on its own, except the disposable test databases a run created for itself (see [Disposable test databases](disposable-test-databases.md)), the orphans `gc --apply` drops when you run it and the trash entries `gc --apply --trash` drops when you run it (see [Database trash](trash.md)).

## Preparing a linked worktree

### Workspace layout

Every checkout reads one workspace file (see [Workspace file](workspace-file.md)); no folder layout is required. A checkout reads the nearest `oasis-workspace.toml` at or above it, and a linked worktree with none above it reads the one its main checkout reads, found through git, with its slug from its own directory name. Two layouts that work:

- The default of [`oasis setup`](setup.md): the file in the main checkout, untracked (listed in `.git/info/exclude`), with the shared files under `<main checkout>/.oasis/`. Worktrees anywhere read it through git.
- One folder above the checkouts (`oasis setup --workspace <project>`), with the shared files next to the file:

```text
<project>/oasis-workspace.toml             the workspace file
<project>/codigo/<main checkout>           main checkout
<project>/codigo/<main checkout>-<feature> linked worktrees, siblings at the same depth
<project>/config/                          odoo.conf, environment file, compose file, requirements/
<project>/data/                            Odoo data directory ([tooling].data_dir)
<project>/logs/                            compact runs and browser evidence ([tooling].logs)
```

```toml
# In <project>/oasis-workspace.toml, example only: paths relative to that file.
config = 'config/odoo.conf'
env_file = 'config/.env'
compose = 'config/compose.yml'
requirements = 'config/requirements'
logs = 'logs'
```

With `logs`, compact runs (`--compact`) and the browser evidence of `test-module` go to `<project>/logs/<checkout>/run-*`, where `<checkout>` is `main` for the main checkout and the slug for a linked worktree (`<project>/logs/shop_feature/`), so the checkouts need no `dev/` directory at all. Missing directories are created private (0700). `logs` resolves from the workspace file's directory like the other paths, and a run directory that resolves outside it (for example `<checkout>` as a symlink elsewhere) is refused with `Compact logs must remain inside the configured logs directory.` before anything is created. Runs written before 0.8.0 under `<logs>/odoo19/<checkout>/` are never moved or deleted, and `oasis_test_summary` still reads them. Without `logs`, runs stay under each checkout's `dev/logs/odoo19/` (see the end of this section).

### Addons path in a linked worktree

A shared `odoo.conf` may name the main checkout in its `addons_path`. In a linked worktree (`CHECKOUT_KIND=linked`), every command that starts Odoo (`test-module`, `verify-module`, `install-module`, `update-module`, `odoo-shell`, `start`, `init-dev-database`) reads only that option and passes it after `-c` as `--addons-path=<value>`, with each item that is the main checkout's root or lies inside it moved to the worktree's root (`<main>/vendor` becomes `<worktree>/vendor`); other items (Enterprise, OCA, the Odoo addons) stay as they are, in order. Nothing is added when no item names the main checkout, when there is no `addons_path`, or when the worktree's own `odoo.conf` already names the worktree. The main checkout and a project outside git keep their previous command line. An `odoo.conf` that cannot be parsed stops those commands with exit 2 before Odoo starts (`Cannot read addons_path from <path>: invalid configuration file.`); its content is never printed. `init-dev-database` checks it before asking for any password or starting the database service. An `odoo.conf` without `addons_path` needs no rewrite: see [Path-free odoo.conf](path-free-odoo-conf.md).

### worktree-init

`worktree-init` creates a linked worktree that reads the main checkout's workspace file. Run it yourself, in Gentle Shell or in a terminal, from the main checkout or any of its worktrees:

```text
/oasis worktree <feature> <branch>
```

```bash
~/.agents/skills/odoo19/oasis --project /absolute/project worktree-init <feature> <branch> [--path <dir>] [--dry-run] [--resume]
```

- The folder is `<main folder>-<feature>` next to the main checkout, so the feature becomes the checkout slug (`acme` with `shop feature` gives `acme-shop-feature`, slug `shop_feature`). An existing folder is refused, unless you pass `--resume` (below).
- `--path <dir>` (or `--path=<dir>`) creates it at that absolute path instead (`--path requires an absolute path.` otherwise). The slug still comes from the folder name, so it must be `<feature>` or `<main folder>-<feature>` (`Folder <name> would not give the checkout slug <slug>.` otherwise). Refused: a folder inside the Odoo source (`The new worktree <path> would be inside the Odoo source <source>.`), inside another checkout, a linked worktree or any git work tree (`The new worktree <path> would be inside the checkout <checkout>.`), and an existing folder that is not an empty directory (`Worktree folder already exists and is not empty: <path>`). An empty directory is filled; missing parents are created by git. `/oasis worktree` always uses the default folder; pass `--path` in a terminal.
- An existing local branch is checked out; otherwise `origin/<branch>` is tracked when it exists; otherwise the branch is created from the main checkout's `HEAD`. A branch already checked out in another worktree is refused.
- Only `git worktree add` runs: the new worktree reads the workspace file the main checkout reads, above the new folder or, when there is none above it, through git, so nothing is copied or linked. A folder below another workspace file would read that one and is refused (`The new worktree <path> would read <file>, not the main checkout's <file>; choose another --path.`), and a main checkout that finds none is refused (`The main checkout <path> has no oasis-workspace.toml at or above it; prepare the worktree by hand.`). A workspace file inside the main checkout that git tracks is refused too (`<file> is tracked by git in the main checkout <path>: each worktree would read its own committed copy, not this file. Untrack it (git rm --cached oasis-workspace.toml) or keep the workspace file above the checkouts.`): every worktree checks out its own copy and reads it, with paths resolved from that worktree; an untracked one is read through git. A workspace file the new worktree could not read is refused with the error every command gives for it (`Invalid TOML in <file>.` or `Refusing untrusted workspace file <file>: ...`).
- It prints `worktree: <path>`, `branch: <branch> (...)` (`created from HEAD <commit>`, `existing`, `tracking origin/<branch>` or `resumed`), `slug: <slug>` and `workspace: <dir>`. `--dry-run` prints the same lines, then `dry run: nothing changed`, and changes nothing; `/oasis worktree` shows them and asks before creating anything.
- `--resume` accepts an existing folder only when it is a worktree of this repository with `<branch>` checked out, and adds nothing to it. A plain folder, a symlink, another repository's worktree or a worktree on another branch is refused. Without the folder, `--resume` creates the worktree as usual.
- Agents cannot run it: the bash guard blocks it because it adds a worktree and a branch for the user.

### Logs without [tooling].logs

Without `[tooling].logs`, a linked worktree's `dev/logs` may be a link you make to the main checkout's `dev/logs`: in a linked worktree, `--compact` runs accept a log directory that resolves inside the main checkout's `dev/logs/odoo19` (`CHECKOUT_MAIN_ROOT` from `tools/config.py`); any other location outside the project is still refused with `Compact logs must remain inside the project.`
