# Recipe: a new model and its fields

Checked against: 19.0.

Official docs: [19.0](https://www.odoo.com/documentation/19.0/developer/reference/backend/orm.html)

Part of the [backend skill](../../SKILL.md). A path in `path:line` is relative to the Odoo source root of the
series written before it (15.0 at commit 3a28e5b0, 19.0 at commit 8a2481dfc), or of this series when none is
written. The example, the `library.book` of the `library` module the recipes build ([module.md](module.md)),
follows `addons/lunch/models/lunch_product.py` and `lunch_supplier.py` (fields, company and currency) and
`addons/analytic/models/analytic_account.py` (display name and name search).

## When to use

A module needs a new business object (its own table): a `models.Model` with `_name`. For a field added to
an existing model use `_inherit` ([inheritance.md](inheritance.md)); computed fields, constraints and
`create`/`write` overrides are in [compute-constraint.md](compute-constraint.md); the module skeleton is in
[module.md](module.md).

## Files

1. `library/models/library_book.py`: one model per file, file named after the model. This recipe gives its
   final content; [compute-constraint.md](compute-constraint.md) repeats the same copy for its loans.
2. `library/models/__init__.py`: `from . import library_book` among the imports of [module.md](module.md).
3. `library/security/ir.model.access.csv`: the rows of `model_library_book` ([module.md](module.md)).
4. Views, the action and the menu: the `views` and `actions-menus` recipes of `odoo-views-frontend`, listed in
   the manifest `data` after the CSV.

## Example

`library/models/library_book.py`, final: its fields are the ones the other recipes use (`user_id` and
`company_id` for the record rules, `pages`, `copies` and `author_id` for the views, the widget and the tests),
and it refers to no model of another recipe:

```python
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class LibraryBook(models.Model):
    _name = 'library.book'
    _description = 'Library Book'
    _order = 'name, id'
    _rec_names_search = ['name', 'isbn']

    name = fields.Char(required=True)
    isbn = fields.Char(string='ISBN', index='btree_not_null')
    author_id = fields.Many2one('res.partner', string='Author', index=True)
    date_published = fields.Date()
    pages = fields.Integer(default=1)
    copies = fields.Integer(default=1)
    loan_duration = fields.Integer(string='Loan Days', default=14)
    state = fields.Selection(
        [('available', 'Available'), ('borrowed', 'Borrowed'), ('lost', 'Lost')],
        default='available', required=True,
    )
    borrower_id = fields.Many2one('res.partner', string='Borrower')
    active = fields.Boolean(default=True)
    user_id = fields.Many2one('res.users', string='Librarian', default=lambda self: self.env.user)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)
    currency_id = fields.Many2one('res.currency', related='company_id.currency_id')
    price = fields.Monetary(currency_field='currency_id', aggregator='avg', help="Replacement cost of one copy.")

    _name_unique = models.Constraint('UNIQUE (name)', 'A book with this title already exists.')

    @api.depends('name', 'isbn')
    def _compute_display_name(self):
        for book in self:
            book.display_name = f'[{book.isbn}] {book.name}' if book.isbn else book.name

    @api.constrains('pages')
    def _check_pages(self):
        for book in self:
            if book.pages < 1:
                raise ValidationError(self.env._("%(book)s needs at least one page.", book=book.name))
```

What each part does:

- The ORM lives in `odoo/orm/` (`models.py`, `fields*.py`, `decorators.py`, `environments.py`,
  `commands.py`), re-exported by `odoo/fields`, `odoo/models` and `odoo/api` (`odoo/fields/__init__.py:5`,
  `odoo/models/__init__.py:7`, `odoo/api/__init__.py:5`): read field and model behavior there.

- `_description` is the label users see; a model without it logs "The model ... has no _description"
  (15.0 `odoo/models.py:716-717`; 19.0 `odoo/orm/model_classes.py:274-275`).
- `_order` is the default `ORDER BY` of `search` and of the list view; end it with `id` so the order is
  stable. The default is `'id'`.
- `_rec_name` names the field that labels a record; it defaults to `name` when the model has one (the book
  needs none), and a name that is not a field fails with "Invalid _rec_name" (15.0
  `odoo/models.py:3036-3040`; 19.0 `odoo/orm/model_classes.py:435-439`). The loan of
  [compute-constraint.md](compute-constraint.md) has no `name` and sets `_rec_name = 'book_id'`.

- The label of a record is `display_name`, computed by `_compute_display_name` from `_rec_name`
  (`odoo/orm/models.py:1437-1452`); override it, with `@api.depends` on the fields it reads, to build
  another label, as `addons/analytic/models/analytic_account.py:105` does. `name_get` no longer exists.

- Name search looks in the fields of `_rec_names_search` (`odoo/orm/models.py:433`, read by
  `_search_display_name` at `:1455-1468`); for anything else override `_search_display_name(operator, value)`
  and return a domain, as `addons/analytic/models/analytic_account.py:18` lists its fields. `_name_search` no
  longer exists.

- `aggregator='avg'` sets how a grouped list or pivot aggregates the field; `group_operator` is a
  deprecated alias since 18.0 (`odoo/orm/fields.py:485-487`).

- `index` names a kind: `True` or `'btree'`, `'btree_not_null'` (the ISBN, often empty), `'trigram'`
  (`odoo/orm/fields.py:109-117`).

- `Monetary` takes its currency from `currency_field`, which defaults to `currency_id`; the named field must
  exist on the model, or setup fails with "Field ... with unknown currency_field" (15.0
  `odoo/fields.py:1487-1498`; 19.0 `odoo/orm/fields_numeric.py:223-234`). A related `currency_id`, as here
  and in `addons/lunch/models/lunch_product.py` (15.0 line 29, 19.0 line 26), is the usual source.
- `Many2one` with `required=True` defaults to `ondelete='restrict'` (`company_id`), otherwise to
  `'set null'` (`author_id`); `required` with `'set null'` is refused (15.0 `odoo/fields.py:2732-2737`; 19.0
  `odoo/orm/fields_relational.py:282-286`). A `One2many` needs the comodel's `Many2one` back to this model,
  and its values are written with `Command` (`from odoo.fields import Command`; 15.0
  `odoo/fields.py:3002`; 19.0 `odoo/fields/__init__.py:19`).
- `author_id` and `borrower_id` point to contacts (`res.partner`), so the book needs no model of another
  recipe; an author of [inheritance.md](inheritance.md) owns such a contact.
- `Selection` takes a list of `(value, label)` pairs; extend it from another module with `selection_add`
  ([inheritance.md](inheritance.md)).
- `company_id` with `default=lambda self: self.env.company` and the `with_company`, `check_company=True` and
  `_check_company_auto` attributes work the same in both series (`addons/lunch/models/lunch_product.py`,
  15.0 lines 19-29, 19.0 lines 16-26); the multi-company record rule of the `record-rules` recipe filters on
  it.

- `_name_unique` (a `models.Constraint`) and `_check_pages` (a Python constraint) are explained in
  [compute-constraint.md](compute-constraint.md); the `model-tests` recipe tests both. The message of
  `_check_pages` is translated with `self.env._` (`odoo/orm/environments.py:315`).

- Code that must check the current user's rights before acting (for example before a `sudo()`) calls
  `check_access(operation)`, which checks the access rows and the record rules of `self` and raises, or
  `has_access(operation)`, which returns a boolean (`odoo/orm/models.py:4106`, `:4123`);
  `check_access_rights` and `check_access_rule` are deprecated since 18.0 (`odoo/orm/models.py:4166-4183`).

## Mistakes

### Give every model a description and an access row

Why: without `_description` the log warns at every start, and without an access row the model works for the
superuser only.

Exceptions: none.

```python
from odoo import fields, models


class LibraryBook(models.Model):
    _name = 'library.book'

    name = fields.Char(required=True)
```

```python
from odoo import fields, models


class LibraryBook(models.Model):
    _name = 'library.book'
    _description = 'Library Book'

    name = fields.Char(required=True)
```

### Set `_rec_name` on a model without `name`

Why: the label becomes `library.loan,7` and the name search warns that there is no field to search.

Exceptions: a model that overrides its display name and name search itself.

```python
from odoo import fields, models


class LibraryLoan(models.Model):
    _name = 'library.loan'
    _description = 'Library Loan'

    book_id = fields.Many2one('library.book', required=True)
```

```python
from odoo import fields, models


class LibraryLoan(models.Model):
    _name = 'library.loan'
    _description = 'Library Loan'
    _rec_name = 'book_id'

    book_id = fields.Many2one('library.book', required=True)
```

### Build the label with the method of the checkout's series

Why: `name_get` and `_name_search` are never called on this series, so a method copied from older code
silently leaves the default label and search.

Exceptions: none.

```python
from odoo import models


class LibraryBook(models.Model):
    _inherit = 'library.book'

    def name_get(self):
        return [(book.id, f'[{book.isbn}] {book.name}' if book.isbn else book.name) for book in self]
```

```python
from odoo import api, models


class LibraryBook(models.Model):
    _inherit = 'library.book'

    @api.depends('name', 'isbn')
    def _compute_display_name(self):
        for book in self:
            book.display_name = f'[{book.isbn}] {book.name}' if book.isbn else book.name
```

### Write the field attributes of the checkout's series

Why: `group_operator=` still works but warns as deprecated at every start, which hides real warnings.

Exceptions: `index=True` is valid in every series.

```python
from odoo import fields

price = fields.Monetary(group_operator='avg')
isbn = fields.Char(index=True)
```

```python
from odoo import fields

price = fields.Monetary(aggregator='avg')
isbn = fields.Char(index='btree_not_null')
```

### Check access with the methods of the checkout's series

Why: `check_access_rights` and `check_access_rule` are deprecated aliases here and warn on each call;
`check_access` does both checks.

Exceptions: code that does not switch to `sudo()` needs no explicit check: the ORM checks the current user.

```python
def action_mark_lost(self):
    self.check_access_rights('write')
    self.check_access_rule('write')
    self.sudo().write({'state': 'lost'})
```

```python
def action_mark_lost(self):
    self.check_access('write')
    self.sudo().write({'state': 'lost'})
```

### Point a `Monetary` field to a currency field of the model

Why: setup asserts the currency field exists, so the module fails to install.

Exceptions: none; a model without a currency of its own takes the company's through a related field.

```python
from odoo import fields, models


class LibraryBook(models.Model):
    _name = 'library.book'
    _description = 'Library Book'

    price = fields.Monetary()
```

```python
from odoo import fields, models


class LibraryBook(models.Model):
    _name = 'library.book'
    _description = 'Library Book'

    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)
    currency_id = fields.Many2one('res.currency', related='company_id.currency_id')
    price = fields.Monetary(currency_field='currency_id')
```

### Keep `ondelete='set null'` off required many2one fields

Why: a required field cannot be emptied when its target is deleted, so setup refuses the field.

Exceptions: none.

```python
from odoo import fields

company_id = fields.Many2one('res.company', required=True, ondelete='set null')
```

```python
from odoo import fields

company_id = fields.Many2one('res.company', required=True, ondelete='restrict')
```

### Give a new model a name of its own

Why: a `_name` another module already defines, without `_inherit`, builds that model again from this class
alone and drops the other module's definition of it from the registry (15.0 `odoo/models.py:620-637`; 19.0
`odoo/orm/model_classes.py:172-189`); with itself in `_inherit` it is an extension
([inheritance.md](inheritance.md)). Neither gives a table of its own.

Exceptions: an extension is meant: then write `_inherit` alone.

```python
from odoo import models


class LibraryBook(models.Model):
    _name = 'product.template'
    _description = 'Library Book'
```

```python
from odoo import models


class LibraryBook(models.Model):
    _name = 'library.book'
    _description = 'Library Book'
```

## Verify

- `oasis --project <root> model-info library.book` (Gentle Shell: `oasis_model_info`) lists the fields,
  their attributes and the methods as defined in source; `--field price` shows one field and its overrides.
- `oasis --project <root> module-info library --section models` lists the models the module defines and
  extends; `--section security` the ACL rows per model.
- `oasis --project <root> verify-module --compact library` installs on a fresh database, updates and runs
  the tests; a new stored field also needs `oasis --project <root> update-module --compact library <database>`
  on an existing database.

## Changed from 15.0

- `book-display-name-search`: `from odoo import api, fields, models`
- `orm-source`: The ORM lives in `odoo/orm/` (`models.py`, `fields*.py`, `decorators.py`, `environments.py`,
- `display-name`: The label of a record is `display_name`, computed by `_compute_display_name` from `_rec_name`
- `name-search`: Name search looks in the fields of `_rec_names_search` (`odoo/orm/models.py:433`, read by
- `aggregator`: `aggregator='avg'` sets how a grouped list or pivot aggregates the field; `group_operator` is a
- `index-kinds`: `index` names a kind: `True` or `'btree'`, `'btree_not_null'` (the ISBN, often empty), `'trigram'`
- `sql-constraint`: `_name_unique` (a `models.Constraint`) and `_check_pages` (a Python constraint) are explained in
- `access-check`: Code that must check the current user's rights before acting (for example before a `sudo()`) calls
- `label-rule`: Why: `name_get` and `_name_search` are never called on this series, so a method copied from older code
- `attributes-rule`: Why: `group_operator=` still works but warns as deprecated at every start, which hides real warnings.
- `check-access-rule`: Why: `check_access_rights` and `check_access_rule` are deprecated aliases here and warn on each call;
