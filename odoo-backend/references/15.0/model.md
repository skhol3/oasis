# Recipe: a new model and its fields

Checked against: 15.0.

Official docs: [15.0](https://www.odoo.com/documentation/15.0/developer/reference/backend/orm.html)

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
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.osv import expression


class LibraryBook(models.Model):
    _name = 'library.book'
    _description = 'Library Book'
    _order = 'name, id'

    name = fields.Char(required=True)
    isbn = fields.Char(string='ISBN', index=True)
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
    price = fields.Monetary(currency_field='currency_id', group_operator='avg', help="Replacement cost of one copy.")

    _sql_constraints = [
        ('name_unique', 'UNIQUE (name)', 'A book with this title already exists.'),
    ]

    def name_get(self):
        return [(book.id, f'[{book.isbn}] {book.name}' if book.isbn else book.name) for book in self]

    @api.depends('isbn')
    def _compute_display_name(self):
        super()._compute_display_name()

    @api.model
    def _name_search(self, name, args=None, operator='ilike', limit=100, name_get_uid=None):
        if name and operator in ('ilike', 'like', '=', '=like', '=ilike'):
            domain = expression.AND([args or [], ['|', ('name', operator, name), ('isbn', operator, name)]])
            return self._search(domain, limit=limit, access_rights_uid=name_get_uid)
        return super()._name_search(name, args=args, operator=operator, limit=limit, name_get_uid=name_get_uid)

    @api.constrains('pages')
    def _check_pages(self):
        for book in self:
            if book.pages < 1:
                raise ValidationError(_("%(book)s needs at least one page.", book=book.name))
```

What each part does:

- The ORM is `odoo/models.py`, `odoo/fields.py` and `odoo/api.py`: read field and model behavior there.

- `_description` is the label users see; a model without it logs "The model ... has no _description"
  (15.0 `odoo/models.py:716-717`; 19.0 `odoo/orm/model_classes.py:274-275`).
- `_order` is the default `ORDER BY` of `search` and of the list view; end it with `id` so the order is
  stable. The default is `'id'`.
- `_rec_name` names the field that labels a record; it defaults to `name` when the model has one (the book
  needs none), and a name that is not a field fails with "Invalid _rec_name" (15.0
  `odoo/models.py:3036-3040`; 19.0 `odoo/orm/model_classes.py:435-439`). The loan of
  [compute-constraint.md](compute-constraint.md) has no `name` and sets `_rec_name = 'book_id'`.

- The label of a record is what `name_get` returns, `(id, label)` pairs (`odoo/models.py:1845`, as
  `addons/analytic/models/analytic_account.py:145` adds the code); the many2one fields, the form title and
  the name search show it. The `display_name` field is computed from `name_get` (`odoo/models.py:1828-1843`)
  and depends only on `_rec_name`; the `@api.depends('isbn')` override adds the other field it reads, since
  the dependencies of a compute are collected along the class hierarchy (`odoo/fields.py:516-527`).

- Name search (the many2one input, `name_search`) looks in `_rec_name` only; to search another field
  override `_name_search(name, args, operator, limit, name_get_uid)` and return the ids of `_search`, as
  `addons/analytic/models/analytic_account.py:156-172` does (the default is `odoo/models.py:1916-1929`).

- `group_operator='avg'` sets how a grouped list or pivot aggregates the field (`odoo/fields.py:285`); the
  default for numbers is a sum.

- `index` is a boolean: `index=True` creates a plain btree index (`odoo/fields.py:140`,
  `odoo/modules/registry.py:473-477`).

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
- `active = fields.Boolean(default=True)` makes the book archivable: every search leaves out the records whose
  `active` is false unless its domain names `active` or the context sets `active_test=False` (15.0
  `odoo/models.py:4484-4489`; 19.0 `odoo/orm/models.py:5375-5383`), so lists, many2one inputs and `search` in
  code skip archived books with no domain of their own.
- `Selection` takes a list of `(value, label)` pairs; extend it from another module with `selection_add`
  ([inheritance.md](inheritance.md)).
- `company_id` with `default=lambda self: self.env.company` and the `with_company`, `check_company=True` and
  `_check_company_auto` attributes work the same in both series (`addons/lunch/models/lunch_product.py`,
  15.0 lines 19-29, 19.0 lines 16-26); the multi-company record rule of the `record-rules` recipe filters on
  it.

- `_sql_constraints` (the unique title) and `_check_pages` (a Python constraint) are explained in
  [compute-constraint.md](compute-constraint.md); the `model-tests` recipe tests both. The message of
  `_check_pages` is translated with `_` from `odoo`.

- Code that must check the current user's rights before acting (for example before a `sudo()`) calls
  `check_access_rights(operation)` for the access rows and `check_access_rule(operation)` for the record
  rules of `self` (`odoo/models.py:3559`, `:3565`); there is no `check_access`.

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

Why: on this series the many2one fields and the name search show what `name_get` returns; a
`_compute_display_name` override alone changes the `display_name` field and nothing users see in a
many2one.

Exceptions: none.

```python
from odoo import api, models


class LibraryBook(models.Model):
    _inherit = 'library.book'

    @api.depends('name', 'isbn')
    def _compute_display_name(self):
        for book in self:
            book.display_name = f'[{book.isbn}] {book.name}' if book.isbn else book.name
```

```python
from odoo import models


class LibraryBook(models.Model):
    _inherit = 'library.book'

    def name_get(self):
        return [(book.id, f'[{book.isbn}] {book.name}' if book.isbn else book.name) for book in self]
```

### Depend on every field the label reads

Why: `display_name` is computed from `name_get` but depends only on `_rec_name` (`odoo/models.py:1828`), so a
`name_get` that also reads `isbn` leaves the label stale in the cache after the ISBN changes, in the form and
the many2one fields of the same request; an `_compute_display_name` override with `@api.depends('isbn')` adds
the dependency, since dependencies are collected along the class hierarchy (`odoo/fields.py:516-527`).

Exceptions: a label built from `_rec_name` alone.

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

    def name_get(self):
        return [(book.id, f'[{book.isbn}] {book.name}' if book.isbn else book.name) for book in self]

    @api.depends('isbn')
    def _compute_display_name(self):
        super()._compute_display_name()
```

### Write the field attributes of the checkout's series

Why: `aggregator=` only logs "Field ...: unknown parameter" (`odoo/fields.py:476-481`) and the average is
missing, and `index='btree_not_null'` is merely truthy, so it creates a plain btree index.

Exceptions: `index=True` is valid in every series.

```python
from odoo import fields

price = fields.Monetary(aggregator='avg')
isbn = fields.Char(index='btree_not_null')
```

```python
from odoo import fields

price = fields.Monetary(group_operator='avg')
isbn = fields.Char(index=True)
```

### Check access with the methods of the checkout's series

Why: `check_access` does not exist on this series (`AttributeError`), and `check_access_rights` alone checks
the access rows but not the record rules.

Exceptions: code that does not switch to `sudo()` needs no explicit check: the ORM checks the current user.

```python
def action_mark_lost(self):
    self.check_access('write')
    self.sudo().write({'state': 'lost'})
```

```python
def action_mark_lost(self):
    self.check_access_rights('write')
    self.check_access_rule('write')
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

### Give a `One2many` the `Many2one` it is the inverse of

Why: a `One2many` finds its records through the comodel field named second, so when the comodel has no field
of that name the registry setup fails with a `KeyError` (`odoo/fields.py:3381-3382`) and the module does not
load.

Exceptions: none; the `Many2one` points back to this model.

```python
from odoo import fields, models


class LibraryLoan(models.Model):
    _name = 'library.loan'
    _description = 'Library Loan'

    book = fields.Char()


class LibraryBook(models.Model):
    _inherit = 'library.book'

    loan_ids = fields.One2many('library.loan', 'book_id')
```

```python
from odoo import fields, models


class LibraryLoan(models.Model):
    _name = 'library.loan'
    _description = 'Library Loan'

    book_id = fields.Many2one('library.book', required=True)


class LibraryBook(models.Model):
    _inherit = 'library.book'

    loan_ids = fields.One2many('library.loan', 'book_id')
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

## Changed from earlier series

Oldest supported series.
