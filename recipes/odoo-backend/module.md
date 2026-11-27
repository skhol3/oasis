# Recipe: a minimal module

Checked against: every series.

Official docs: 15.0=https://www.odoo.com/documentation/15.0/developer/reference/backend/module.html, 19.0=https://www.odoo.com/documentation/19.0/developer/reference/backend/module.html

Part of the [backend skill](../../SKILL.md). A path in `path:line` is relative to the Odoo source root of the
series written before it (15.0 at commit 3a28e5b0, 19.0 at commit 8a2481dfc). The layout follows
`addons/lunch` (`__manifest__.py`, `__init__.py`, `models/__init__.py`), which has the same shape in both.

The recipes of the code skills build one module, `library`: this one, then [model.md](model.md),
[compute-constraint.md](compute-constraint.md) and [inheritance.md](inheritance.md) of this skill, the
`access` and `record-rules` recipes of `odoo-security`, the `views`, `actions-menus`, `view-inheritance` and
`owl-component` recipes of `odoo-views-frontend`, and the `model-tests` and `tours` recipes of
`odoo-testing`, each under `references/<series>/` of its skill. This recipe gives, final, the files they all
share: the manifest lists every file the other recipes add, `models/__init__.py` every model file and
`security/ir.model.access.csv` the rows of every model. An agent building only one piece keeps the entries of
that piece and drops the others. Every other file is given whole in the recipe that adds it, and a recipe that
repeats a file shows the same copy.

## When to use

A new addon, or a new Python package or manifest key in an existing one: `__manifest__.py`, the
`__init__.py` files that import the models, the `data` list, `assets`, install hooks and controllers. The
fields of a model are in [model.md](model.md); computes and constraints in
[compute-constraint.md](compute-constraint.md); `_inherit` in [inheritance.md](inheritance.md).

## Files

1. `library/__manifest__.py`: `name`, `version`, `depends`, `data`, `assets`, `author`, `license`. The
   directory name is the technical name (`library`).
2. `library/__init__.py`: `from . import models` (plus `controllers`, `wizard`, hooks when there are some).
   It does not import `tests`: Odoo finds the tests package itself.
3. `library/models/__init__.py`: one `from . import <file>` per model file. A file that extends a model
   defined in this module comes after the file that defines it: models are built in import order, and an
   extension of a model not built yet fails with "Model ... does not exist in registry" (15.0
   `odoo/models.py:621-623`; 19.0 `odoo/orm/model_classes.py:173-175`). Extensions of other modules' models
   (`res_partner`) go last.
4. `library/models/library_book.py` ([model.md](model.md)), `library/models/library_loan.py`
   ([compute-constraint.md](compute-constraint.md)), `library/models/library_author.py` and
   `library/models/res_partner.py` ([inheritance.md](inheritance.md)).
5. `library/security/ir.model.access.csv`: rows per model, or only the superuser can use it (the loader
   warns "The models ... have no access rules in module ...", `odoo/modules/loading.py:259` in both series).
6. The manifest `data`, in this order (the order of `addons/lunch/__manifest__.py`, 15.0 lines 24-39, 19.0
   lines 22-37), because each file may refer only to XML ids loaded before it: the groups XML,
   `security/ir.model.access.csv`, record rules, reports, views (each file declares its window action before
   the menu that opens it; the file of root menus last), then `data/*.xml`. Demo records go under `demo`
   (loaded only in demo mode), never `data`. The loader reads each list in order (15.0
   `odoo/modules/loading.py:64`; 19.0 `odoo/modules/loading.py:55`); the official module page states no
   order inside `data`, so this one comes from the loader.
7. The manifest `assets`: bundles of static files, not `data` files.

## Example

`library/__manifest__.py`:

```python id=manifest-version-bundles since=15.0
{
    'name': 'Library',
    'version': '15.0.1.0.0',
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
            'library/static/src/**/*.js',
        ],
        'web.assets_qweb': [
            'library/static/src/**/*.xml',
        ],
        'web.assets_tests': [
            'library/static/tests/tours/**/*',
        ],
    },
    'application': True,
    'installable': True,
}
```

```python id=manifest-version-bundles since=19.0
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

What the manifest lists, by recipe: the three `security/` files come from the `access` and `record-rules`
recipes, `views/library_book_views.xml` from `views`, `views/library_author_views.xml` from
[inheritance.md](inheritance.md), `views/res_partner_views.xml` from `view-inheritance`,
`views/library_menus.xml` from `actions-menus`, `static/src/` from `owl-component` and `static/tests/tours/`
from `tours`. Building only some of them, keep their entries and delete the others: a `data` file that does
not exist stops the install, an asset glob that matches nothing loads nothing.

`depends`: `mail` for `mail.thread` ([inheritance.md](inheritance.md)), `web` for the Owl widget's imports
and bundles; `base` comes with both. No `web_tour`: `mail` depends on it (15.0
`addons/mail/__manifest__.py:11`; 19.0 `addons/mail/__manifest__.py:63`) and it installs itself with `web`
(15.0 `addons/web_tour/__manifest__.py:44`; 19.0 `addons/web_tour/__manifest__.py:70`).

<!-- since=15.0 id=template-bundle -->
`assets` on this series: the JavaScript in `web.assets_backend`, the Owl templates (`*.xml`) in
`web.assets_qweb`, the bundle 15.0 loads XML templates from (`addons/web/__manifest__.py:41`;
`addons/account/__manifest__.py:93`, `:123-125`), and the test tours in `web.assets_tests`
(`addons/account/__manifest__.py:116-118`). A template of `web.assets_qweb` reaches Owl only when it carries
`owl="1"` and sits directly under `<templates>` (`addons/web/static/src/legacy/js/core/session.js:240-243`);
the `owl-component` recipe writes it so.
<!-- end -->

<!-- since=19.0 id=template-bundle -->
`assets` on this series: the JavaScript and the Owl templates together in `web.assets_backend`, the test
tours in `web.assets_tests` (`addons/fleet/__manifest__.py:52-57`).
<!-- end -->

<!-- since=15.0 id=version -->
`version` starts with the series, `15.0.1.0.0`. A version that does not start with `15.0.` gets the series
prefixed, so a manifest copied from 19.0 (`19.0.1.0.0`) silently becomes `15.0.19.0.1.0.0`
(`odoo/modules/module.py:463-466`).
<!-- end -->

<!-- since=19.0 id=version -->
`version` starts with the series, `19.0.1.0.0`, and has 2 to 5 parts (`odoo/modules/module.py:550-554`). A
version of another series (`15.0.1.0.0`) logs "incompatible version" and sets `installable=False`
(`odoo/modules/module.py:465-467`).
<!-- end -->

In both series a `version` of two or three parts (`'1.0'`) gets the series prefixed, and a missing `license`
logs a warning and defaults to `LGPL-3` (15.0 `odoo/modules/module.py:368-370`; 19.0
`odoo/modules/module.py:432-434`).

<!-- since=15.0 id=missing-author -->
A missing `author` is silently `'Odoo S.A.'` (`odoo/modules/module.py:337`), and an empty `depends` stays
empty (`odoo/modules/module.py:340`): write both.
<!-- end -->

<!-- since=19.0 id=missing-author -->
A missing `author` logs "Missing `author` key in manifest" (`odoo/modules/module.py:428-430`), and an empty
`depends` becomes `['base']` (`odoo/modules/module.py:438-440`): write both.
<!-- end -->

<!-- since=15.0 id=python -->
Python: 3.7 to 3.12 (`odoo/__init__.py:19-20`); the default environment is 3.9, so no `match` statement and
no `X | Y` union types evaluated at run time.
<!-- end -->

<!-- since=19.0 id=python -->
Python: 3.10 to 3.14 (`odoo/release.py:39-40`); the default environment is 3.12.
<!-- end -->

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

`library/security/ir.model.access.csv`:

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

The model XML id is `model_` plus the model name with dots as underscores. The rows that name
`group_library_user` and `group_library_manager` need `security/library_groups.xml` of the `access` recipe,
which also explains this matrix; without that file, keep the `base.group_user` row of each model you build
and give it the rights the piece needs.

<!-- since=15.0 id=hook-signature -->
An install hook is a function of the package named in the manifest: `'post_init_hook': 'post_init_hook'` in
`__manifest__.py` and, in `library/__init__.py`, a function that takes the cursor and the registry
(`pre_init_hook(cr)`, `post_init_hook(cr, registry)`, `uninstall_hook(cr, registry)`;
`odoo/modules/loading.py:186`, `:240`, `:534`). Build an environment from them when the hook needs the ORM:

```python
from odoo import SUPERUSER_ID, api

from . import models


def post_init_hook(cr, registry):
    env = api.Environment(cr, SUPERUSER_ID, {})
    env['library.book'].search([('copies', '<', 1)]).write({'copies': 1})
```
<!-- end -->

<!-- since=19.0 id=hook-signature -->
An install hook is a function of the package named in the manifest: `'post_init_hook': 'post_init_hook'` in
`__manifest__.py` and, in `library/__init__.py`, a function that takes an environment
(`pre_init_hook(env)`, `post_init_hook(env)`, `uninstall_hook(env)`; `odoo/modules/loading.py:187`, `:245`,
`:556`):

```python
from . import models


def post_init_hook(env):
    env['library.book'].search([('copies', '<', 1)]).write({'copies': 1})
```
<!-- end -->

The official module page keeps hooks for a setup or cleanup that "is either extremely difficult or
impossible through the api": prefer data files and model code.

<!-- since=15.0 id=json-route -->
A controller lives in `library/controllers/`, imported by `library/__init__.py`. A route that answers JSON
calls from the web client takes `type='json'`; the only types are `'http'` and `'json'`
(`odoo/http.py:451`, asserted at `odoo/http.py:519`).
<!-- end -->

<!-- since=19.0 id=json-route -->
A controller lives in `library/controllers/`, imported by `library/__init__.py`. A route that answers JSON
calls from the web client takes `type='jsonrpc'`; `type='json'` still works but warns "Since 19.0,
@route(type='json') is a deprecated alias to @route(type='jsonrpc')" (`odoo/http.py:812-818`).
<!-- end -->

## Mistakes

### Write the version of the checkout's series

<!-- since=15.0 id=version-rule -->
Why: a version that does not start with `15.0.` is not refused but rewritten: `19.0.1.0.0` installs as
`15.0.19.0.1.0.0`, greater than any real `15.0.x` version, and later updates and migration scripts compare
against it.

Exceptions: a version of two or three parts (`'1.0'`) is valid in every series: the series is prefixed.

```python
{'name': 'Library', 'version': '19.0.1.0.0', 'depends': ['mail', 'web']}
```

```python
{'name': 'Library', 'version': '15.0.1.0.0', 'depends': ['mail', 'web']}
```
<!-- end -->

<!-- since=19.0 id=version-rule -->
Why: a version of another series makes the module uninstallable (`installable=False`, with an "incompatible
version" warning), so it silently disappears from the apps list.

Exceptions: a version of two or three parts (`'1.0'`) is valid in every series: the series is prefixed.

```python
{'name': 'Library', 'version': '15.0.1.0.0', 'depends': ['mail', 'web']}
```

```python
{'name': 'Library', 'version': '19.0.1.0.0', 'depends': ['mail', 'web']}
```
<!-- end -->

### Depend on every module whose models, groups or views you use

Why: a model that is only installed by chance (`mail.thread` with `depends` on `base`) works on the developer's
database and fails on a fresh one with "inherits from non-existing model".

Exceptions: modules that a listed dependency already pulls in (`base` through `mail`).

```python
{'name': 'Library', 'depends': ['base']}
```

```python
{'name': 'Library', 'depends': ['mail', 'web']}
```

### List each data file after the files it refers to

Why: the loader reads `data` in order, so a menu before its action or an access row before its group stops
the install with "External ID not found".

Exceptions: files that refer to no XML id of the module may go anywhere after the security files.

```python
{
    'data': [
        'views/library_menus.xml',
        'security/ir.model.access.csv',
        'security/library_groups.xml',
    ],
}
```

```python
{
    'data': [
        'security/library_groups.xml',
        'security/ir.model.access.csv',
        'views/library_menus.xml',
    ],
}
```

### Import every model file

Why: a model file not imported by `models/__init__.py` (or `models` not imported by `__init__.py`) silently
defines nothing, and the access CSV then fails on `model_library_loan`.

Exceptions: none.

```python
from . import library_book
```

```python
from . import library_author
from . import library_book
from . import library_loan
from . import res_partner
```

### Give every new model an access row

Why: the loader only warns "have no access rules", and every user but the superuser then gets an access
error on the model.

Exceptions: an `AbstractModel` or a `TransientModel` used only by the superuser; an `_inherit` extension, which
keeps the rows of the model it extends.

```csv
id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink
access_library_book_employee,library.book.employee,model_library_book,base.group_user,1,0,0,0
```

```csv
id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink
access_library_book_employee,library.book.employee,model_library_book,base.group_user,1,0,0,0
access_library_loan_employee,library.loan.employee,model_library_loan,base.group_user,1,0,0,0
```

### Write the hook signature of the checkout's series

<!-- since=15.0 id=hook-rule -->
Why: a hook written for 19.0 (`post_init_hook(env)`) is called with `(cr, registry)` and fails the install with
a `TypeError`.

Exceptions: none; prefer data files when they can do the job.

```python
def post_init_hook(env):
    env['library.book'].search([]).write({'copies': 1})
```

```python
from odoo import SUPERUSER_ID, api


def post_init_hook(cr, registry):
    env = api.Environment(cr, SUPERUSER_ID, {})
    env['library.book'].search([]).write({'copies': 1})
```
<!-- end -->

<!-- since=19.0 id=hook-rule -->
Why: a hook written for 15.0 (`post_init_hook(cr, registry)`) is called with one environment and fails the
install with a `TypeError`.

Exceptions: none; prefer data files when they can do the job.

```python
def post_init_hook(cr, registry):
    cr.execute("UPDATE library_book SET copies = 1")
```

```python
def post_init_hook(env):
    env['library.book'].search([]).write({'copies': 1})
```
<!-- end -->

### Write the route type of the checkout's series

<!-- since=15.0 id=route-rule -->
Why: `type='jsonrpc'` does not exist on this series: the route decorator asserts the type is `'http'` or
`'json'`, so the module fails to load.

Exceptions: `type='http'` routes are written the same in every series.

```python
from odoo import http


class LibraryController(http.Controller):
    @http.route('/library/books', type='jsonrpc', auth='user')
    def books(self):
        return http.request.env['library.book'].search_read([], ['name'])
```

```python
from odoo import http


class LibraryController(http.Controller):
    @http.route('/library/books', type='json', auth='user')
    def books(self):
        return http.request.env['library.book'].search_read([], ['name'])
```
<!-- end -->

<!-- since=19.0 id=route-rule -->
Why: `type='json'` is a deprecated alias here: it works, but every load warns and the alias will go.

Exceptions: `type='http'` routes are written the same in every series.

```python
from odoo import http


class LibraryController(http.Controller):
    @http.route('/library/books', type='json', auth='user')
    def books(self):
        return http.request.env['library.book'].search_read([], ['name'])
```

```python
from odoo import http


class LibraryController(http.Controller):
    @http.route('/library/books', type='jsonrpc', auth='user')
    def books(self):
        return http.request.env['library.book'].search_read([], ['name'])
```
<!-- end -->

### Write `auto_install`, not `active`

Why: no manifest loader reads an `active` key, so the module never installs itself; the 19.0 module page
calls it "Deprecated. Replaced by `auto_install`."

Exceptions: none.

```python
{'name': 'Library Mail Bridge', 'depends': ['library', 'mail'], 'active': True}
```

```python
{'name': 'Library Mail Bridge', 'depends': ['library', 'mail'], 'auto_install': True}
```

### Set `license` and `author`

Why: the install works without them, but the defaults and their warnings fill the log and hide real ones.

Exceptions: none.

```python
{'name': 'Library', 'depends': ['mail', 'web']}
```

```python
{'name': 'Library', 'depends': ['mail', 'web'], 'author': 'Your Company', 'license': 'LGPL-3'}
```

<!-- since=15.0 id=python-syntax -->
### Write Python the series' interpreter runs

Why: the 15.0 environment runs Python 3.9 by default, so a `match` statement is a `SyntaxError` when the
module is imported.

Exceptions: an environment that pins a newer interpreter, still at most 3.12.

```python
def label(state):
    match state:
        case 'lost':
            return 'Lost'
        case _:
            return 'On the shelf'
```

```python
def label(state):
    if state == 'lost':
        return 'Lost'
    return 'On the shelf'
```
<!-- end -->

<!-- since=19.0 id=python-syntax -->
<!-- end -->

## Verify

- `oasis --project <root> module-info library` (Gentle Shell: `oasis_module_info`) shows the manifest, the
  models, the security and the `data` order as Odoo will read them; `--section data` prints that order.
- `oasis --project <root> lint-module library` runs Pylint with the project rcfile, without starting Odoo.
- `oasis --project <root> verify-module --compact library` installs, updates and tests on disposable
  databases; `oasis --project <root> test-module --compact library` runs the tests on a fresh install.
- On an existing database, `oasis --project <root> update-module --compact library <database>` reports
  install errors and the "no access rules" warning.
