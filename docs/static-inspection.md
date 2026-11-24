# Static inspection without starting Odoo

These commands read the source of the Odoo series, optional Enterprise and the profile's addon
roots; none of them starts Odoo or uses a database. The Gentle Shell layer wraps them as agent tools
(see [Source inspection tools](gentle-shell-layer.md#source-inspection-tools)).

- [Summarize a model without starting Odoo](#summarize-a-model-without-starting-odoo): `model-info`.
- [Views and XML ids without starting Odoo](#views-and-xml-ids-without-starting-odoo): `view-info` and `xmlid-info`.
- [Module overview without starting Odoo](#module-overview-without-starting-odoo): `module-info`.

To lint a module without starting Odoo, see [Lint one module](lint-module.md).

## Summarize a model without starting Odoo

```bash
~/.agents/skills/odoo19/oasis --project /absolute/project model-info mrp.production
~/.agents/skills/odoo19/oasis --project /absolute/project model-info mrp.production --field state
```

`model-info <model> [--field <name>] [--module <technical>] [--methods] [--all-fields]` prints a compact summary of one model: where it is defined (with `_inherit` mixins and `_inherits` delegations), the modules that extend it, its fields with type, comodel, label and literal flags, field overrides in extensions and methods per module. It scans the profile's Odoo source (`odoo/addons`, `addons`), optional Enterprise source and `[tooling].addons_paths`, prefilters files by the quoted model name and parses them with `ast`: no Odoo or project code is imported or executed, and no environment, service or database is used. Odoo/Enterprise `test_*` modules and `tests/`, `migrations/`, `upgrades/`, `static/` directories are skipped; mixin fields are not expanded. By default the field list stops at 40 (`--all-fields` lifts it) and methods list public names with a count of private ones; `--module` restricts the details to one module and lists all its methods, `--methods` adds decorators and `super()` calls, `--field` shows one field's definition and overrides with `file:line`. An unknown model exits 1 with `model not found: <model>`; invalid arguments exit 2. `model-info --help` describes the format.

## Views and XML ids without starting Odoo

```bash
~/.agents/skills/odoo19/oasis --project /absolute/project view-info sale.order
~/.agents/skills/odoo19/oasis --project /absolute/project view-info sale.order --type form
~/.agents/skills/odoo19/oasis --project /absolute/project xmlid-info sale.view_order_form
```

Both read XML data files from the same roots as `model-info` (Odoo source, optional Enterprise source, the profile's addon roots; first module with a name wins) and skip the same directories (`tests/`, `migrations/`, `upgrades/`, `static/`, `i18n/`, source `test_*` modules). XML is parsed with expat; Python and CSV files are only searched as text. Nothing is imported or executed and no environment, service or database is used.

### view-info

`view-info <model> [--type <tag>] [--module <technical>]` lists the views of one model:

```text
model: coffee.order — 3 views, 3 extensions
form coffee.view_coffee_order_form coffee/views/coffee_order_views.xml:3
  + coffee_loyalty.view_coffee_order_form_loyalty coffee_loyalty/views/coffee_order_views.xml:3 (2 changes)
    + coffee_loyalty.view_coffee_order_form_vip coffee_loyalty/views/coffee_order_views.xml:16 (1 change, mode=primary)
list coffee.view_coffee_order_list coffee/views/coffee_order_views.xml:12 priority=20
unresolved: coffee_shop.view_shop_orphan coffee_shop/views/order_views.xml:18 inherits missing_module.view_gone
skipped: coffee_shop/views/broken.xml (XML error at line 4)
```

- A base view shows its type (the root tag of its arch), XML id, file and line, and `priority=` or `mode=` when set. Types are ordered form, list, kanban, search, then the rest.
- Below it, each `+` line is a view that extends it, indented once per level, with the number of changes it makes (`xpath` elements and elements with a `position` attribute).
- A view without a `model` field takes the model of the view it inherits.
- `--type` keeps the base views of that type with their extensions; `--module` lists only the views that module defines, each extension with `extends <XML id>`.
- `unresolved:` is an extension whose inherited view is not in the scanned roots, followed by the views that extend it; `skipped:` is a file that is not well-formed XML.
- Long lists end with the count of the rest: at most 40 extensions per view (`+<n> more extensions (narrow with --module)`), 10 unresolved and 5 skipped files.
- Exit status: 0 with views, 1 with `no views found for model: <model>`, 2 for a usage error.

### xmlid-info

`xmlid-info <module>.<name>` shows one XML id:

```text
xml id: coffee.action_coffee_order
defined: coffee/views/coffee_order_views.xml:25 record ir.actions.act_window
  name: Coffee Orders
  res_model: coffee.order
  view_mode: list,form
  view_id: coffee.view_coffee_order_list
referenced by (3):
  coffee/views/coffee_order_views.xml:32
  coffee_shop/controllers/main.py:2
  coffee_shop/views/order_views.xml:27
```

- `defined:` names the file, line and kind: `record <model>`, `template` or `menuitem`. Its fields follow in document order (at most 12, values cut at 60 characters; a `ref` is shown as its full id; `arch` is left out). A base view also gets `type:`.
- `also written in:` lists other data files that write on the same id (at most ten). The definition is the record of the module the id belongs to; without one, the first in scan order.
- `extended by (<n>):` lists the views whose `inherit_id` is this id (at most 20).
- `referenced by (<n>):` lists `file:line` of text references in XML, Python and CSV files (at most 20): the full id anywhere, and inside the defining module also the name alone in `ref`, `parent` and `action` attributes, in comma-separated `groups` lists, `%(name)d`, `ref('name')` and CSV cells (such as the group column of `ir.model.access.csv`). Definition lines and the `inherit_id` reference of a data file are not repeated there; another reference on such a line still counts.
- `skipped:` lines name files that mention the id but are not well-formed XML; with `xml id not found: <id>` they go to stderr, since one of them may hold the definition.
- Exit status: 0 when found, 1 with `xml id not found: <id>`, 2 for a usage error.

## Module overview without starting Odoo

```bash
~/.agents/skills/odoo19/oasis --project /absolute/project module-info sale_mrp
~/.agents/skills/odoo19/oasis --project /absolute/project module-info sale_mrp --section security
```

`module-info <module> [--section <name>]` maps one module from its source in about one screen. It finds the module in the same roots as `model-info` (Odoo source, optional Enterprise source, the profile's addon roots; the first module with a name wins, and source `test_*` modules are not modules) and reads only that module's directory: Python with `ast`, XML with expat, CSV with `csv`. Nothing is imported or executed and no environment, service or database is used. `static/`, `i18n/`, `migrations/` and `upgrades/` are skipped, and `tests/` is read only for the tests section.

```text
module: coffee_planner 19.0.1.2.0 — Plan coffee subscriptions
depends: coffee, mail
root: /work/coffee/addons
models: 4 defined, 2 extended
  coffee.subscription "Coffee subscription" (+mail.thread): 4 fields, models/subscription.py:4
  coffee.subscription.line: 2 fields, models/subscription.py:18
  coffee.planner.mixin "Planner mixin" abstract: 0 fields, models/subscription.py:25
  coffee.subscription.renew "Renew subscriptions" transient: 1 field, wizard/renew_wizard.py:4
  extends account.move (+mail.activity.mixin): 2 fields, models/account_move.py:4
  extends res.partner: 1 field, models/res_partner.py:4
views: 5 base, 3 extensions
  coffee.subscription: form view_subscription_form, list view_subscription_list, search view_subscription_search
  coffee.subscription.renew: form view_subscription_renew_form
  (no model): qweb report_subscription_document
  extends account.view_move_form (2): view_move_form_planner, view_move_form_planner_extra
  extends view_subscription_form (1): view_subscription_form_renew
menus: 5
  Planner (menu_planner_root)
    Subscriptions (menu_planner_subscriptions)
    Configuration (menu_planner_config)
      Renew (menu_planner_renew)
  Planner reports (menu_planner_reports) under base.menu_custom
actions: 3
  report action_report_subscription: coffee.subscription "Subscription" qweb-pdf
  window action_subscription: coffee.subscription "Subscriptions"
  server action_server_renew: coffee.subscription "Renew now" (written 2 times)
security: 5 access rules, 2 record rules, 1 group
  group group_planner_manager "Planner manager"
  access coffee.subscription: base.group_user r---, group_planner_manager rwcu
  access coffee.subscription.line: everyone rw--
  access coffee.subscription.renew, res.partner: base.group_user rwc-
  rule rule_subscription_user: coffee.subscription, groups base.group_user, group_planner_manager
  rule rule_subscription_line_global: coffee.subscription.line, global
data: 8 data files, 1 demo, 1 cron, 1 not in manifest, 1 missing
  data: security/security.xml, security/ir.model.access.csv, views/subscription_views.xml, views/account_move_views.xml, report/subscription_report.xml, data/cron.xml, data/a_cron_override.xml, views/missing.xml
  demo: demo/demo.xml
  cron ir_cron_renew "Renew subscriptions": every 2 weeks, coffee.subscription (written 2 times)
  not in manifest: data/unused.xml
  missing on disk: views/missing.xml
tests: 2 files, 3 classes, 3 test methods
  tests/common.py: PlannerCommon
  tests/test_subscription.py: TestSubscription (2 tests), TestRenewWizard (1 test)
skipped: models/broken.py (Python error at line 2)
```

- The header gives the manifest `version`, its `summary` (or `name`), `depends` and the addons root the module was found in. The manifest is the first dict literal of `__manifest__.py` (a leading docstring or comment is fine); when the file cannot be parsed or holds no literal dict, `manifest: unreadable (<reason>)` replaces the `depends:` line and the other sections are still printed.
- `models`: each class that defines a model (`_name`, `"_description"`, `transient` or `abstract`, `(+...)` for `_inherit` mixins) and, as `extends`, each class that extends one (`_inherit` without a new `_name`), with the number of fields the class adds or overrides and its `file:line`.
- `views`: the base views of each model by type, then the extensions of each inherited view with their count. Only the module's own views count.
- `menus`: the menu tree with names and XML ids; a top menu whose parent belongs to another module ends with `under <XML id>`.
- `actions`: window actions with their `res_model`, server actions with their model, reports with their model and type, client and URL actions.
- `security`: the groups the module defines, the `ir.model.access.csv` lines per model with each group and its flags (`r`ead, `w`rite, `c`reate, `u`nlink, `-` when not granted; `everyone` for a line without a group; models with the same access share a line) and record rules with their model and groups (`global` without groups). A model the module does not name elsewhere is shown as its model XML id (`mrp.model_mrp_bom_line`).
- `data`: the manifest `data` and `demo` files in order, crons with their interval and model, XML and CSV files on disk that the manifest does not list, and listed files that do not exist.
- `tests`: the files of `tests/` with their classes and number of test methods.
- An XML id written more than once (a record the module writes again in another file, or twice in one) is shown once, with the fields of its writes applied in load order: the manifest `data` and `demo` files in their order, and document order within a file. So a later write that changes `res_model`, a name or a cron interval is what you see. It is listed where its first loaded write stands, and actions and crons end with `(written <n> times)`, counting loaded writes only.
- Odoo never loads a data file the manifest does not list. Its writes are ignored for an id that a listed file also writes (in the example, `data/unused.xml` renames `action_server_renew`, which changes nothing). An id written only in unlisted files is still shown, from those files in path order (its `(written <n> times)` then counts those writes), and ends with `(not loaded: file not in manifest)`; the files themselves appear under `not in manifest:`. When the manifest cannot be read, every file counts as unlisted: all writes are merged in path order and nothing is marked, and `--section data` starts with `manifest: unreadable (<reason>)`.
- Paths are relative to the module directory, and the module's own XML ids are shown without the module prefix, as its files write them (pass `<module>.<id>` to `xmlid-info`). An empty section prints `<section>: none`; `skipped:` names Python or XML files that could not be parsed.
- Lists stop at 10 lines, and comma-separated lists at 25 names, each ending with `+<n> more (--section <name>)`. `--section models|views|menus|actions|security|data|tests` prints only that section, uncapped.
- Exit status: 0 when found, 1 with `module not found: <module>`, 2 for a usage error (unknown option, invalid module name or section).
