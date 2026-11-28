# Checkout resource rules

Each git checkout of a project (the main checkout or a linked worktree) owns its databases and its Odoo server.

- Each checkout owns its databases: with a checkout slug, names must start with `<dev_prefix><slug>_` or `<test_prefix><slug>_` and defaults include the slug. `install-module`, `update-module` and `odoo-shell` refuse a missing database; create it through `create-database --plan --json` only when the user asks.
- Each checkout controls only its own Odoo server: `start` refuses a second server for the checkout and picks its port (main: `http_port` of `odoo.conf`; linked worktree: the next free one), `stop` stops only that server, and `stop --database` stops the shared PostgreSQL service only when no other checkout serves. Never stop another checkout's server or the database to free a port; pass `--http-port` instead. Test runs use their own free port.
