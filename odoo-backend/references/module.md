# Recipe: a minimal module

Checked against: 15.0, 19.0.

Official docs: [19.0](https://www.odoo.com/documentation/19.0/developer/reference/backend/module.html), [15.0](https://www.odoo.com/documentation/15.0/developer/reference/backend/module.html)

Part of the [backend skill](../SKILL.md). Paths in `path:line` are relative to the Odoo source root: a bare
path is the 19.0 source (commit 8a2481dfc), a path marked 15.0 is the 15.0 source (commit 3a28e5b0). The
layout follows `addons/lunch` (19.0 `addons/lunch/__manifest__.py`, `addons/lunch/__init__.py`,
`addons/lunch/models/__init__.py`).

The twelve recipes of the code skills build one module, `library`, in this order: this one,
[model.md](model.md), [compute-constraint.md](compute-constraint.md), [inheritance.md](inheritance.md), the
security recipes [access.md](../../odoo-security/references/access.md) and
[record-rules.md](../../odoo-security/references/record-rules.md), the views recipes
[views.md](../../odoo-views-frontend/references/views.md),
[actions-menus.md](../../odoo-views-frontend/references/actions-menus.md),
[view-inheritance.md](../../odoo-views-frontend/references/view-inheritance.md) and
[owl-component.md](../../odoo-views-frontend/references/owl-component.md), then the tests
[model-tests.md](../../odoo-testing/references/model-tests.md) and
[tours.md](../../odoo-testing/references/tours.md). Each file is given whole in one recipe; the manifest,
`security/ir.model.access.csv` and `tests/__init__.py`, which several recipes need, are the same final file
in every recipe that shows them.

## When to use

A new addon, or a new Python package or manifest key in an existing one: `__manifest__.py`, the
`__init__.py` files that import the models, the `data` list and install hooks. The fields of a model are in
[model.md](model.md); computes and constraints in [compute-constraint.md](compute-constraint.md);
`_inherit` in [inheritance.md](inheritance.md).

## Files

1. `library/__manifest__.py`: `name`, `version`, `depends`, `data`, `assets`, `author`, `license`. The
   directory name is the technical name (`library`).
2. `library/__init__.py`: `from . import models` (plus `controllers`, `wizard`, hooks when there are some).
   It does not import `tests`: Odoo finds the tests package itself.
3. `library/models/__init__.py`: one `from . import <file>` per model file. A file that extends a model
   defined in this module comes after the file that defines it: models are built in import order, and an
   extension of a model not built yet fails with "Model ... does not exist in registry"
   (`odoo/orm/model_classes.py:175`; 15.0 `odoo/models.py:623`). Extensions of other modules' models
   (`res_partner`) go last.
4. `library/models/library_book.py` ([model.md](model.md)), `library/models/library_loan.py`
   ([compute-constraint.md](compute-constraint.md)), `library/models/library_author.py` and
   `library/models/res_partner.py` ([inheritance.md](inheritance.md)).
5. `library/security/ir.model.access.csv`: one row per model, or only the superuser can use it (the loader
   warns "The models ... have no access rules in module ...", `odoo/modules/loading.py:259` in both series;
   the rows and the groups they name are in the [access recipe](../../odoo-security/references/access.md)).
6. The manifest `data`, in this order (the order of `addons/lunch/__manifest__.py:22-37`), because each file
   may refer only to XML ids loaded before it: the groups XML, `security/ir.model.access.csv`, record rules,
   reports, views (each file declares its window action before the menu that opens it; the file of root
   menus last), then `data/*.xml`. Demo records go under `demo` (loaded only in demo mode), never `data`. The
   loader reads each list in order (`odoo/modules/loading.py:55`; 15.0 `odoo/modules/loading.py:64`); the
   official module page states no order inside `data`, so this one comes from the loader.
7. The manifest `assets`: JavaScript and Owl templates in `web.assets_backend`, test tours in
   `web.assets_tests` (`addons/fleet/__manifest__.py:52-55`). They are not `data` files.

## Example

`library/__manifest__.py`, final: it lists every file the later recipes add.

```python
{
    'name': 'Library',
    'version': '19.0.1.0.0',
    'summary': 'Books, authors and loans',
    'category': 'Services',
    'author': 'Your Company',
    'license': 'LGPL-3',
    'depends': ['mail', 'web'],
    'data': [
        'security/library_groups.xml',
        'security/ir.model.access.csv',
        'security/library_rules.xml',
        'views/library_book_views.xml',
        'views/library_author_views.xml',
        'views/res_partner_views.xml',
        'views/library_menus.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'library/static/src/**/*',
        ],
        'web.assets_tests': [
            'library/static/tests/tours/**/*',
        ],
    },
    'application': True,
    'installable': True,
}
```

`depends`: `mail` for `mail.thread` ([inheritance.md](inheritance.md)), `web` for the Owl widget's imports
and bundle; `base` comes with both. No `web_tour`: on 19.0 `mail` depends on it
(`addons/mail/__manifest__.py:63`) and it installs itself with `web` (`addons/web_tour/__manifest__.py:70`).

`library/__init__.py`:

```python
from . import models
```

`library/models/__init__.py`:

```python
from . import library_author
from . import library_book
from . import library_loan
from . import res_partner
```

`library/security/ir.model.access.csv` (the model XML id is `model_` plus the model name with dots as
underscores; the groups and this matrix are explained in the
[access recipe](../../odoo-security/references/access.md)):

```csv
id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink
access_library_book_employee,library.book.employee,model_library_book,base.group_user,1,0,0,0
access_library_book_user,library.book.user,model_library_book,group_library_user,1,1,1,0
access_library_book_manager,library.book.manager,model_library_book,group_library_manager,1,1,1,1
access_library_loan_employee,library.loan.employee,model_library_loan,base.group_user,1,0,0,0
access_library_loan_user,library.loan.user,model_library_loan,group_library_user,1,1,1,0
access_library_loan_manager,library.loan.manager,model_library_loan,group_library_manager,1,1,1,1
access_library_author_employee,library.author.employee,model_library_author,base.group_user,1,0,0,0
access_library_author_user,library.author.user,model_library_author,group_library_user,1,1,1,0
access_library_author_manager,library.author.manager,model_library_author,group_library_manager,1,1,1,1
```

An install hook is a function of the package named in the manifest: `'post_init_hook': 'post_init_hook'`
in `__manifest__.py` and `def post_init_hook(env):` in `library/__init__.py` (19.0 form; see *Changed in*).
The official module page keeps hooks for a setup or cleanup that "is either extremely difficult or
impossible through the api": prefer data files and model code.

## Changed in

| Point | Since | Before | Source |
|---|---|---|---|
| Python: 3.10 to 3.14; the default environment is 3.12 | 19.0 | 3.7 to 3.12 (15.0 `odoo/__init__.py:19-20`), 3.9 by default: no `match` statement and no union types with the pipe operator evaluated at run time | `odoo/release.py:39-40` |
| Install and uninstall hooks take `env`: `pre_init_hook(env)`, `post_init_hook(env)`, `uninstall_hook(env)` | 19.0 | `pre_init_hook(cr)`, `post_init_hook(cr, registry)`, `uninstall_hook(cr, registry)` (15.0 `odoo/modules/loading.py:186`, `240`, `534`) | `odoo/modules/loading.py:187`, `odoo/modules/loading.py:245`, `odoo/modules/loading.py:556` |
| A missing `author` logs "Missing `author` key in manifest" | 19.0 | silently `'Odoo S.A.'` (15.0 `odoo/modules/module.py:337`) | `odoo/modules/module.py:430` |
| An empty `depends` becomes `['base']` | 19.0 | kept empty (15.0 `odoo/modules/module.py:340`) | `odoo/modules/module.py:438-440` |
| A `version` of another series (`15.0.1.0.0` on 19.0) logs "incompatible version" and sets `installable=False`; a version needs 2 to 5 parts | 19.0 | any version not starting with the series gets it prefixed, so `19.0.1.0.0` on 15.0 becomes `15.0.19.0.1.0.0` (15.0 `odoo/modules/module.py:463-467`) | `odoo/modules/module.py:466`, `odoo/modules/module.py:554` |

A *Since* the source does not state is 19.0: the point changed after 15.0, by 19.0 at the latest.

Same in both series: a missing `license` logs a warning and defaults to `LGPL-3` (`odoo/modules/module.py:434`;
15.0 `odoo/modules/module.py:370`); a `version` of two or three parts (`'1.0'`) gets the series prefixed.

## Mistakes

- A manifest copied from another series: its `version` makes the module uninstallable (19.0) or is silently
  rewritten to `15.0.19.0.1.0.0` (15.0). Write the checkout's series.
- `depends` missing a module whose models, groups or views are used (`mail` for `mail.thread`,
  `product` for `product.product`): install order then decides whether it works, and it fails on a
  fresh database. Depend on what you use, not on what happens to be installed.
- A file in `data` that refers to an XML id of a later file (a menu before its action, an ACL before its
  group): "External ID not found" at install.
- A model file not imported in `models/__init__.py`, or `models` not imported in `__init__.py`: the model
  silently does not exist and `model_library_book` is not found by the CSV.
- No `ir.model.access.csv` row for a new model: the loader only warns, and every user but the superuser
  gets an access error.
- A 15.0 hook signature on 19.0 (`post_init_hook(cr, registry)`): `TypeError` at install. On 15.0, build an
  environment yourself from `cr` and `registry` when needed.
- `'active': True` copied from old code: the 19.0 module page says "Deprecated. Replaced by `auto_install`.",
  and the manifest loader of neither series reads an `active` key (`odoo/modules/module.py`). Write
  `auto_install` when that is meant.
- Missing `license` or `author`: install works, but the log fills with warnings that hide real ones.
- Python syntax newer than the checkout's Python (a `match` statement on a 15.0 environment of Python 3.9).

## Verify

- `oasis --project <root> module-info library` (Gentle Shell: `oasis_module_info`) shows the manifest, the
  models, the security and the `data` order as Odoo will read them; `--section data` prints that order.
- `oasis --project <root> lint-module library` runs Pylint with the project rcfile, without starting Odoo.
- `oasis --project <root> verify-module --compact library` installs, updates and tests on disposable
  databases; `oasis --project <root> test-module --compact library` runs the tests on a fresh install.
- On an existing database, `oasis --project <root> update-module --compact library <database>` reports
  install errors and the "no access rules" warning.
