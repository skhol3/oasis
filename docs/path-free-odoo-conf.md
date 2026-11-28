# Path-free odoo.conf

`odoo.conf` may leave out everything that depends on where the checkout lives; oasis passes it on the command line of every command that starts Odoo (`test-module`, `verify-module`, `install-module`, `update-module`, `odoo-shell`, `start`, `create-database`, and project helpers that call `run_odoo`), right after `-c <odoo.conf>`:

- `--addons-path=<enterprise>,<addon roots>,<community>/addons` when `odoo.conf` has no `addons_path` in `[options]`: the `enterprise` source when configured, then every `[tooling].addons_paths` root of the checkout in order, then the Community `addons` directory. The main checkout and each linked worktree get their own roots, so nothing is rewritten, also when git fails in a linked worktree that sets `checkout_slug`. A root whose path contains a comma stops the command with `Cannot compose --addons-path: <path> contains a comma.` (exit 2). An `odoo.conf` that names `addons_path` keeps the behaviour above (the main checkout unchanged, a linked worktree rewritten).
- `--data-dir=<path>` when `[tooling].data_dir` is set (optional; it resolves from the workspace file's directory; an empty or non-string value is refused with `Invalid tooling path: data_dir.`). The filestores of disposable runs and of `gc --apply` are then removed under that directory, and the `data_dir` of `odoo.conf` is not read. Without it nothing is added.
- Ports: `start` already chooses `--http-port` (and a linked worktree's second port); test runs and `start --stop-after-init` get two free ports (see [Reusable test destinations and compact evidence](testing.md#reusable-test-destinations-and-compact-evidence)).

Without `[tooling].data_dir` and with an `addons_path` in `odoo.conf`, every command line is unchanged.
