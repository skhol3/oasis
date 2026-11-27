# Recipe: computed fields, constraints, indexes and create/write overrides

Checked against: every series.

Official docs: 15.0=https://www.odoo.com/documentation/15.0/developer/reference/backend/orm.html, 19.0=https://www.odoo.com/documentation/19.0/developer/reference/backend/orm.html#constraints-and-indexes

Part of the [backend skill](../../SKILL.md). A path in `path:line` is relative to the Odoo source root of the
series written before it (15.0 at commit 3a28e5b0, 19.0 at commit 8a2481dfc), or of this series when none is
written. The example, the `library.loan` of the `library` module the recipes build ([module.md](module.md)),
follows `addons/lunch/models/lunch_order.py`, `lunch_product.py` and `lunch_supplier.py`.

## When to use

A value derived from other fields (`compute=`), editable or searchable derived values (`inverse=`,
`search=`), a rule records must satisfy (`@api.constrains`, a SQL constraint), a database index, or logic
that must run on every `create` or `write`. The model itself is in [model.md](model.md).

## Files

1. `library/models/library_loan.py`: the fields, their compute/inverse/search methods, the constraints and
   the overrides, in that order inside the class (fields, SQL objects, computes, constraints, CRUD).
2. `library/models/library_book.py`: the book the loans point to, the same copy as [model.md](model.md); it
   carries the other two constraints of the module, the unique title and `_check_pages`.
3. `library/models/__init__.py`: `from . import library_book` and `from . import library_loan`
   ([module.md](module.md)).
4. `library/security/ir.model.access.csv`: the rows of `model_library_book` and `model_library_loan`
   ([module.md](module.md)).
5. A stored field added or changed on an installed module needs a module update, which adds the column
   and computes the stored values of existing records.

## Example

`library/models/library_loan.py`:

```python id=loan-sql-objects-search since=15.0
from datetime import timedelta

from odoo import _, api, fields, models, tools
from odoo.exceptions import UserError, ValidationError


class LibraryLoan(models.Model):
    _name = 'library.loan'
    _description = 'Library Loan'
    _order = 'date desc, id desc'
    _rec_name = 'book_id'

    book_id = fields.Many2one('library.book', required=True, ondelete='cascade', index=True)
    borrower_id = fields.Many2one('res.partner', required=True, index=True)
    company_id = fields.Many2one(related='book_id.company_id', store=True)
    date = fields.Date(required=True, default=fields.Date.context_today)
    date_returned = fields.Date()
    note = fields.Text()
    # stored and editable: set from the book, then the user may change it
    duration = fields.Integer(compute='_compute_duration', store=True, readonly=False)
    # stored, read-only: recomputed when date or duration change
    date_due = fields.Date(compute='_compute_date_due', store=True)
    # not stored, written back through the inverse
    borrower_email = fields.Char(compute='_compute_borrower_email', inverse='_inverse_borrower_email')
    # not stored, searchable through the search method
    is_due_today = fields.Boolean(compute='_compute_is_due_today', search='_search_is_due_today')

    _sql_constraints = [
        ('duration_positive', 'CHECK (duration > 0)', 'The loan duration must be positive.'),
    ]

    def init(self):
        tools.create_index(self.env.cr, 'library_loan_book_date_idx', self._table, ['book_id', 'date'])

    @api.depends('book_id')
    def _compute_duration(self):
        for loan in self:
            loan.duration = loan.book_id.loan_duration

    @api.depends('date', 'duration')
    def _compute_date_due(self):
        for loan in self:
            loan.date_due = loan.date + timedelta(days=loan.duration) if loan.date else False

    @api.depends('borrower_id.email')
    def _compute_borrower_email(self):
        for loan in self:
            loan.borrower_email = loan.borrower_id.email

    def _inverse_borrower_email(self):
        for loan in self:
            loan.borrower_id.email = loan.borrower_email

    @api.depends('date_due')
    def _compute_is_due_today(self):
        today = fields.Date.context_today(self)
        for loan in self:
            loan.is_due_today = loan.date_due == today

    def _search_is_due_today(self, operator, value):
        # The condition arrives as written: `is_due_today = False` is ('=', False).
        if operator not in ('=', '!=') or not isinstance(value, bool):
            raise UserError(_("Due Today can only be searched as true or false."))
        today = fields.Date.context_today(self)
        if (operator == '=') == value:
            return [('date_due', '=', today)]
        return [('date_due', '!=', today)]

    @api.constrains('book_id', 'date_returned')
    def _check_copies(self):
        for loan in self:
            book = loan.book_id
            open_loans = self.search_count([('book_id', '=', book.id), ('date_returned', '=', False)])
            if open_loans > book.copies:
                raise ValidationError(_(
                    "All %(copies)s copies of %(book)s are on loan.",
                    copies=book.copies, book=book.display_name,
                ))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('note'):
                vals['note'] = vals['note'].strip()
        return super().create(vals_list)

    def write(self, vals):
        if vals.get('note'):
            vals = dict(vals, note=vals['note'].strip())
        return super().write(vals)
```

```python id=loan-sql-objects-search since=19.0
from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import ValidationError
from odoo.fields import Domain


class LibraryLoan(models.Model):
    _name = 'library.loan'
    _description = 'Library Loan'
    _order = 'date desc, id desc'
    _rec_name = 'book_id'

    book_id = fields.Many2one('library.book', required=True, ondelete='cascade', index=True)
    borrower_id = fields.Many2one('res.partner', required=True, index=True)
    company_id = fields.Many2one(related='book_id.company_id', store=True)
    date = fields.Date(required=True, default=fields.Date.context_today)
    date_returned = fields.Date()
    note = fields.Text()
    # stored and editable: set from the book, then the user may change it
    duration = fields.Integer(compute='_compute_duration', store=True, readonly=False)
    # stored, read-only: recomputed when date or duration change
    date_due = fields.Date(compute='_compute_date_due', store=True)
    # not stored, written back through the inverse
    borrower_email = fields.Char(compute='_compute_borrower_email', inverse='_inverse_borrower_email')
    # not stored, searchable through the search method
    is_due_today = fields.Boolean(compute='_compute_is_due_today', search='_search_is_due_today')

    _duration_positive = models.Constraint('CHECK (duration > 0)', 'The loan duration must be positive.')
    _book_date_idx = models.Index('(book_id, date)')

    @api.depends('book_id')
    def _compute_duration(self):
        for loan in self:
            loan.duration = loan.book_id.loan_duration

    @api.depends('date', 'duration')
    def _compute_date_due(self):
        for loan in self:
            loan.date_due = loan.date + timedelta(days=loan.duration) if loan.date else False

    @api.depends('borrower_id.email')
    def _compute_borrower_email(self):
        for loan in self:
            loan.borrower_email = loan.borrower_id.email

    def _inverse_borrower_email(self):
        for loan in self:
            loan.borrower_id.email = loan.borrower_email

    @api.depends('date_due')
    def _compute_is_due_today(self):
        today = fields.Date.context_today(self)
        for loan in self:
            loan.is_due_today = loan.date_due == today

    def _search_is_due_today(self, operator, value):
        # A boolean condition arrives as `in` or `not in` with [True] (`is_due_today = False` is
        # `not in [True]`); for `not in` the ORM negates this `in` domain (odoo/orm/fields.py:148-156).
        if operator != 'in':
            return NotImplemented
        return Domain('date_due', '=', fields.Date.context_today(self))

    @api.constrains('book_id', 'date_returned')
    def _check_copies(self):
        for loan in self:
            book = loan.book_id
            open_loans = self.search_count([('book_id', '=', book.id), ('date_returned', '=', False)])
            if open_loans > book.copies:
                raise ValidationError(self.env._(
                    "All %(copies)s copies of %(book)s are on loan.",
                    copies=book.copies, book=book.display_name,
                ))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('note'):
                vals['note'] = vals['note'].strip()
        return super().create(vals_list)

    def write(self, vals):
        if vals.get('note'):
            vals = dict(vals, note=vals['note'].strip())
        return super().write(vals)
```

`library/models/library_book.py`, the same copy as [model.md](model.md):

```python id=book-display-name-search since=15.0
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

```python id=book-display-name-search since=19.0
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

How the parts behave:

- A computed field is not stored unless `store=True`; `readonly=False` makes it editable. Its method assigns
  the field on every record of `self`, never returns it.
- `@api.depends` lists every field the method reads, dotted paths included; on a change of one of them the
  ORM recomputes (stored) or invalidates (not stored). Leaving a path out is how a value is frozen on
  purpose: `duration` depends on `book_id`, not `book_id.loan_duration`, so a later change of the book's
  loan days does not rewrite past loans, as the price of a lunch order line depends on `product_id`, not
  `product_id.price` (`addons/lunch/models/lunch_order.py`, 15.0 lines 173-176, 19.0 lines 225-228). A
  dependency on `id` is refused (15.0 `odoo/api.py:270-271`; 19.0 `odoo/orm/decorators.py:268-269`); use
  `@api.depends_context` for context keys (`uid`, `company`).
- `inverse` receives the records whose computed value was written and writes the sources (here the
  borrower's `email`; `addons/lunch/models/lunch_product.py`, 15.0 lines 35 and 113, 19.0 lines 32 and 104).
- `search` receives an operator and a value and returns a domain that replaces the condition
  (`addons/lunch/models/lunch_product.py`, 15.0 lines 41 and 86, 19.0 lines 38 and 82).
- `@api.constrains` runs after `create`/`write` (and after a stored compute) on the records where one of
  the named fields changed, and raises `ValidationError` (15.0 `odoo/models.py:4282`; 19.0
  `odoo/orm/models.py:4960-4966`). Only plain field names: dotted names are ignored, and a field neither
  stored nor inversible logs "is not writeable" (15.0 `odoo/models.py:778-783`; 19.0
  `odoo/orm/models.py:537-541`).
- A SQL constraint checks one row in the database, faster and race-free (the positive duration, the book's
  unique title); anything that reads other records or relations is a Python constraint (`_check_copies`
  counts the open loans of the book). The database name of a constraint is `<table>_<name>` in both series
  (15.0 `odoo/models.py:753`; 19.0 `odoo/orm/table_objects.py:55-58`), so `library_loan_duration_positive`
  keeps its name from one series to the other.
- `create` takes a list of value dicts under `@api.model_create_multi` and returns the recordset of super;
  a caller may still pass one dict, which the decorator wraps in a list (official ORM page: "The method may
  be called with either a single dict or a list of dicts"; 15.0 `odoo/api.py:414-432`; 19.0
  `odoo/orm/decorators.py:357-369`). `write` takes one dict for every record of `self` and returns `True`.

<!-- since=15.0 id=sql-constraint -->
- SQL constraints are a `_sql_constraints` list of `(name, definition, message)` on the class
  (`odoo/models.py:497`, as `addons/lunch/models/lunch_supplier.py:110-114`).
<!-- end -->

<!-- since=19.0 id=sql-constraint -->
- A SQL constraint is a `models.Constraint(definition, message)` class attribute whose name starts with `_`
  (`odoo/orm/table_objects.py:79`, as `addons/lunch/models/lunch_supplier.py:116`); `_sql_constraints` is
  ignored with "Model attribute '_sql_constraints' is no longer supported" (`odoo/orm/model_classes.py:162-164`).
<!-- end -->

<!-- since=15.0 id=multi-column-index -->
- An index on several columns is raw SQL in `init()`, which runs at every install and update:
  `tools.create_index` creates it unless it exists (`odoo/tools/sql.py:223-229`), as
  `addons/lunch/models/lunch_order.py:79-81` writes `CREATE INDEX IF NOT EXISTS`.
<!-- end -->

<!-- since=19.0 id=multi-column-index -->
- An index on several columns is a `models.Index('(col_a, col_b)')` attribute, a unique one
  `models.UniqueIndex(definition, message)` (`odoo/orm/table_objects.py:125`, `:185`, as
  `addons/lunch/models/lunch_order.py:64`); the ORM creates it at install and update.
<!-- end -->

<!-- since=15.0 id=unique-any-case -->
- A value unique whatever its case (an ISBN, an email): `UNIQUE (isbn)` compares exact values and a `UNIQUE`
  constraint takes columns only, so either normalize the value in `create` and `write` (as the loan strips its
  `note`) and keep the plain constraint, or create a unique index on `lower(...)` in `init()` with
  `tools.create_unique_index` (`odoo/tools/sql.py:231-237`, which core calls on columns, as
  `odoo/addons/base/models/ir_model.py:1933` does):

```python
from odoo import models, tools


class LibraryBook(models.Model):
    _inherit = 'library.book'

    def init(self):
        tools.create_unique_index(self.env.cr, 'library_book_isbn_lower_uniq', self._table, ['lower(isbn)'])
```
<!-- end -->

<!-- since=19.0 id=unique-any-case -->
- A value unique whatever its case (an ISBN, an email): `UNIQUE (isbn)` compares exact values, so either
  normalize the value in `create` and `write` (as the loan strips its `note`) and keep the plain constraint, or
  declare a `models.UniqueIndex` on `lower(...)`, which takes an expression and a message
  (`odoo/orm/table_objects.py:185-205`):

```python
from odoo import models


class LibraryBook(models.Model):
    _inherit = 'library.book'

    _isbn_lower_unique = models.UniqueIndex('(lower(isbn))', 'An ISBN is unique, whatever its case.')
```
<!-- end -->

<!-- since=15.0 id=search-operators -->
- A search method gets the operator as written (`=`, `!=`, ...) and must handle each one itself, returning a
  domain list (`addons/lunch/models/lunch_supplier.py:286-303`); for a condition it cannot handle it raises,
  as `addons/fleet/models/fleet_vehicle.py:206` asserts and `addons/account/models/account_account.py:283-285`
  raises `UserError`. A `!=` on a column also matches its empty values (`odoo/osv/expression.py:1076-1077`).
<!-- end -->

<!-- since=19.0 id=search-operators -->
- A search method gets normalized operators (`=` becomes `in`; a boolean condition arrives as `in` or
  `not in` with `[True]`), returns `NotImplemented` for an operator it does not handle, and builds a `Domain`
  (`odoo/orm/fields.py:145-170`, as `addons/lunch/models/lunch_supplier.py:324-335`).
<!-- end -->

<!-- since=15.0 id=domain-combine -->
- Domains are lists, combined with `expression.AND([...])` and `expression.OR([...])` (`from odoo.osv import
  expression`, as `addons/lunch/models/lunch_product.py:96-98`).
<!-- end -->

<!-- since=19.0 id=domain-combine -->
- Domains are combined with `Domain` objects (`from odoo.fields import Domain`, `&`, `|`, `~`;
  `odoo/fields/__init__.py:20`); `odoo.osv.expression.AND`/`OR` warn "Since 19.0, use odoo.fields.Domain"
  (`odoo/osv/expression.py:242`).
<!-- end -->

<!-- since=15.0 id=create-api-model -->
- `@api.model` on `create` wraps a method that takes one dict (`model_create_single`, `odoo/api.py:382-383`):
  it works but creates the records one by one; write `@api.model_create_multi`.
<!-- end -->

<!-- since=19.0 id=create-api-model -->
- `@api.model` on `create` turns it into `model_create_multi` (`odoo/orm/decorators.py:322-323`): the method
  receives a list even when written for one dict.
<!-- end -->

<!-- since=15.0 id=grouped-values -->
- Grouped values in code: `read_group(domain, fields, groupby)` returns dicts such as `category_id_count`
  (`odoo/models.py:2412`, as `addons/lunch/models/lunch_product_category.py:30-31`).
<!-- end -->

<!-- since=19.0 id=grouped-values -->
- Grouped values in code: `_read_group(domain, groupby, aggregates)` returns tuples, for example
  `_read_group([...], ['category_id'], ['__count'])` (`odoo/orm/models.py:1867`, as
  `addons/lunch/models/lunch_product_category.py:30-31`); `read_group` is deprecated "Since 19.0"
  (`odoo/orm/models.py:2754`).
<!-- end -->

<!-- since=15.0 id=cache-before-sql -->
- Before raw SQL, write the pending values with `flush(fnames, records)` and, after it, drop stale values
  with `invalidate_cache(fnames, ids)` (`odoo/models.py:5668`, `:5982`, as
  `addons/lunch/models/lunch_supplier.py:201`); the query is a string with `%s` and a parameter list:
  `cr.execute(query, params)`.
<!-- end -->

<!-- since=19.0 id=cache-before-sql -->
- Before raw SQL, write the pending values with `flush_model(fnames)` or `flush_recordset(fnames)` and, after
  it, drop stale values with `invalidate_model(fnames)` or `invalidate_recordset(fnames)`
  (`odoo/orm/models.py:6372`, `:6386`, `:6728`, `:6743`, as `addons/lunch/models/lunch_supplier.py:211`);
  the query is composed with `odoo.tools.SQL("... %s", value)` (`odoo/tools/sql.py:46`) and run with
  `self.env.cr.execute(sql)`.
<!-- end -->

<!-- since=15.0 id=env-attributes -->
- `self.env.cr`, `self.env.uid` and `self.env.context` are the cursor, user and context; `self._cr`,
  `self._uid` and `self._context` are the same values (`addons/lunch/models/lunch_order.py:80`).
<!-- end -->

<!-- since=19.0 id=env-attributes -->
- `self.env.cr`, `self.env.uid` and `self.env.context` are the cursor, user and context; `self._cr`,
  `self._uid` and `self._context` warn "Deprecated since 19.0" (`odoo/orm/models.py:5931`).
<!-- end -->

<!-- since=15.0 id=translation -->
- Messages are translated with `_` imported from `odoo`.
<!-- end -->

<!-- since=19.0 id=translation -->
- Messages are translated with `self.env._("...")` (`odoo/orm/environments.py:315`); `from odoo import _`
  still works.
<!-- end -->

<!-- since=15.0 id=archive-hook -->
- Side effects of archiving go in an override of `toggle_active`, which `action_archive` and
  `action_unarchive` call (`odoo/models.py:5099-5112`, as `addons/lunch/models/lunch_product_category.py:35`).
<!-- end -->

<!-- since=19.0 id=archive-hook -->
- Side effects of archiving go in overrides of `action_archive` and `action_unarchive`; `toggle_active` is
  "Deprecated since 19.0" (`odoo/orm/models.py:5808`, as `addons/lunch/models/lunch_product_category.py:41-47`).
<!-- end -->

## Mistakes

### Create in batch

<!-- since=15.0 id=create-rule -->
Why: a `create(self, vals)` under `@api.model` is called once per record, and a loop that calls
`super().create(vals)` per dict does the same: every record pays its own queries and recomputations.

Exceptions: none.

```python
from odoo import api, models


class LibraryLoan(models.Model):
    _inherit = 'library.loan'

    @api.model
    def create(self, vals):
        if vals.get('note'):
            vals['note'] = vals['note'].strip()
        return super().create(vals)
```

```python
from odoo import api, models


class LibraryLoan(models.Model):
    _inherit = 'library.loan'

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('note'):
                vals['note'] = vals['note'].strip()
        return super().create(vals_list)
```
<!-- end -->

<!-- since=19.0 id=create-rule -->
Why: `create` always receives a list here, so code written for one dict breaks (`vals.get` on a list), and a
loop that calls `super().create(vals)` per dict pays the queries of every record.

Exceptions: none.

```python
from odoo import api, models


class LibraryLoan(models.Model):
    _inherit = 'library.loan'

    @api.model
    def create(self, vals):
        if vals.get('note'):
            vals['note'] = vals['note'].strip()
        return super().create(vals)
```

```python
from odoo import api, models


class LibraryLoan(models.Model):
    _inherit = 'library.loan'

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('note'):
                vals['note'] = vals['note'].strip()
        return super().create(vals_list)
```
<!-- end -->

### Return what `super().write` returns, from a copy of the values

Why: a `write` that returns nothing breaks callers that test its result, and changing the caller's dict in
place changes what the caller writes next.

Exceptions: none.

```python
from odoo import models


class LibraryLoan(models.Model):
    _inherit = 'library.loan'

    def write(self, vals):
        vals['note'] = (vals.get('note') or '').strip()
        super().write(vals)
```

```python
from odoo import models


class LibraryLoan(models.Model):
    _inherit = 'library.loan'

    def write(self, vals):
        if vals.get('note'):
            vals = dict(vals, note=vals['note'].strip())
        return super().write(vals)
```

### Depend on every field the compute reads

Why: a stored value whose input is missing from `@api.depends` goes stale without any error.

Exceptions: a dependency left out on purpose to freeze a value, said in a comment (`duration` above).

```python
from datetime import timedelta

from odoo import api, models


class LibraryLoan(models.Model):
    _inherit = 'library.loan'

    @api.depends('date')
    def _compute_date_due(self):
        for loan in self:
            loan.date_due = loan.date + timedelta(days=loan.duration) if loan.date else False
```

```python
from datetime import timedelta

from odoo import api, models


class LibraryLoan(models.Model):
    _inherit = 'library.loan'

    @api.depends('date', 'duration')
    def _compute_date_due(self):
        for loan in self:
            loan.date_due = loan.date + timedelta(days=loan.duration) if loan.date else False
```

### Assign the computed field on every record

Why: a record left unassigned raises "Compute method failed to assign" on a non-stored read-only field and
silently gets an empty value otherwise (15.0 `odoo/fields.py:1140-1141`; 19.0 `odoo/orm/fields.py:1756-1757`);
a compute that returns the value or calls `write` assigns nothing.

Exceptions: none.

```python
from odoo import api, models


class LibraryLoan(models.Model):
    _inherit = 'library.loan'

    @api.depends('borrower_id.email')
    def _compute_borrower_email(self):
        for loan in self:
            if loan.borrower_id:
                loan.borrower_email = loan.borrower_id.email
```

```python
from odoo import api, models


class LibraryLoan(models.Model):
    _inherit = 'library.loan'

    @api.depends('borrower_id.email')
    def _compute_borrower_email(self):
        for loan in self:
            loan.borrower_email = loan.borrower_id.email
```

### Constrain local fields, not dotted paths

Why: dotted names in `@api.constrains` are ignored, so the check never runs; a field that create does not
receive (no default, not in the form) does not trigger it on create either.

Exceptions: none; read the related value inside the method.

```python
from odoo import api, models


class LibraryLoan(models.Model):
    _inherit = 'library.loan'

    @api.constrains('book_id.copies')
    def _check_copies(self):
        pass
```

```python
from odoo import api, models


class LibraryLoan(models.Model):
    _inherit = 'library.loan'

    @api.constrains('book_id', 'date_returned')
    def _check_copies(self):
        pass
```

### Declare SQL constraints and indexes in the form of the checkout's series

<!-- since=15.0 id=sql-objects-rule -->
Why: `models.Constraint` and `models.Index` do not exist on this series: the module fails to import with an
`AttributeError` on `models`.

Exceptions: none.

```python
from odoo import models


class LibraryLoan(models.Model):
    _inherit = 'library.loan'

    _duration_positive = models.Constraint('CHECK (duration > 0)', 'The loan duration must be positive.')
    _book_date_idx = models.Index('(book_id, date)')
```

```python
from odoo import models, tools


class LibraryLoan(models.Model):
    _inherit = 'library.loan'

    _sql_constraints = [
        ('duration_positive', 'CHECK (duration > 0)', 'The loan duration must be positive.'),
    ]

    def init(self):
        tools.create_index(self.env.cr, 'library_loan_book_date_idx', self._table, ['book_id', 'date'])
```
<!-- end -->

<!-- since=19.0 id=sql-objects-rule -->
Why: `_sql_constraints` is ignored here with a warning, so the rule is silently missing from the database,
and an `init()` index duplicates what `models.Index` declares; an attribute without the leading `_` fails
with "Names of SQL objects in a model must start with '_'" (`odoo/orm/table_objects.py:44`).

Exceptions: none.

```python
from odoo import models


class LibraryLoan(models.Model):
    _inherit = 'library.loan'

    _sql_constraints = [
        ('duration_positive', 'CHECK (duration > 0)', 'The loan duration must be positive.'),
    ]
```

```python
from odoo import models


class LibraryLoan(models.Model):
    _inherit = 'library.loan'

    _duration_positive = models.Constraint('CHECK (duration > 0)', 'The loan duration must be positive.')
    _book_date_idx = models.Index('(book_id, date)')
```
<!-- end -->

### Refuse the search conditions the method does not handle

<!-- since=15.0 id=search-rule -->
Why: returning `[]` for a condition the method does not understand matches every record, so a wrong filter
shows everything instead of failing.

Exceptions: none.

```python
from odoo import fields, models


class LibraryLoan(models.Model):
    _inherit = 'library.loan'

    def _search_is_due_today(self, operator, value):
        return [('date_due', '=', fields.Date.context_today(self))]
```

```python
from odoo import _, fields, models
from odoo.exceptions import UserError


class LibraryLoan(models.Model):
    _inherit = 'library.loan'

    def _search_is_due_today(self, operator, value):
        if operator not in ('=', '!=') or not isinstance(value, bool):
            raise UserError(_("Due Today can only be searched as true or false."))
        today = fields.Date.context_today(self)
        if (operator == '=') == value:
            return [('date_due', '=', today)]
        return [('date_due', '!=', today)]
```
<!-- end -->

<!-- since=19.0 id=search-rule -->
Why: returning `[]` matches every record; `NotImplemented` lets the ORM try the equivalent operator it can
handle, or fail.

Exceptions: none.

```python
from odoo import fields, models


class LibraryLoan(models.Model):
    _inherit = 'library.loan'

    def _search_is_due_today(self, operator, value):
        return [('date_due', '=', fields.Date.context_today(self))]
```

```python
from odoo import fields, models
from odoo.fields import Domain


class LibraryLoan(models.Model):
    _inherit = 'library.loan'

    def _search_is_due_today(self, operator, value):
        if operator != 'in':
            return NotImplemented
        return Domain('date_due', '=', fields.Date.context_today(self))
```
<!-- end -->

### Flush before raw SQL and pass values as parameters

<!-- since=15.0 id=raw-sql-rule -->
Why: the query reads the database, not the pending values of the cache, and a value formatted into the query
string is an SQL injection.

Exceptions: none; prefer the ORM when it can express the query.

```python
from odoo import models


class LibraryBook(models.Model):
    _inherit = 'library.book'

    def _open_loan_counts(self):
        self.env.cr.execute(
            "SELECT book_id, count(*) FROM library_loan WHERE date_returned IS NULL "
            "AND book_id IN (%s) GROUP BY book_id" % ','.join(map(str, self.ids))
        )
        return dict(self.env.cr.fetchall())
```

```python
from odoo import models


class LibraryBook(models.Model):
    _inherit = 'library.book'

    def _open_loan_counts(self):
        self.env['library.loan'].flush(['book_id', 'date_returned'])
        self.env.cr.execute(
            "SELECT book_id, count(*) FROM library_loan WHERE date_returned IS NULL "
            "AND book_id IN %s GROUP BY book_id",
            [tuple(self.ids)],
        )
        return dict(self.env.cr.fetchall())
```
<!-- end -->

<!-- since=19.0 id=raw-sql-rule -->
Why: the query reads the database, not the pending values of the cache, and a value formatted into the query
string is an SQL injection.

Exceptions: none; prefer the ORM when it can express the query.

```python
from odoo import models


class LibraryBook(models.Model):
    _inherit = 'library.book'

    def _open_loan_counts(self):
        self.env.cr.execute(
            "SELECT book_id, count(*) FROM library_loan WHERE date_returned IS NULL "
            "AND book_id IN (%s) GROUP BY book_id" % ','.join(map(str, self.ids))
        )
        return dict(self.env.cr.fetchall())
```

```python
from odoo import models
from odoo.tools import SQL


class LibraryBook(models.Model):
    _inherit = 'library.book'

    def _open_loan_counts(self):
        self.env['library.loan'].flush_model(['book_id', 'date_returned'])
        self.env.cr.execute(SQL(
            "SELECT book_id, count(*) FROM library_loan WHERE date_returned IS NULL "
            "AND book_id IN %s GROUP BY book_id",
            tuple(self.ids),
        ))
        return dict(self.env.cr.fetchall())
```
<!-- end -->

## Verify

- `oasis --project <root> model-info library.loan --methods` (Gentle Shell: `oasis_model_info`) lists the
  computes, inverses, constraints and overrides with their decorators and `super()` calls;
  `--field date_due` shows the compute and the dependencies of one field.
- `oasis --project <root> test-module --compact library` with tests that create in batch, change each
  dependency and check the recomputed value, write an invalid value and assert `ValidationError` (SQL
  constraints raise at flush: `psycopg2` `IntegrityError` under `mute_logger('odoo.sql_db')`), and search on
  `is_due_today` with `=` and `!=`.
- `oasis --project <root> update-module --compact library <database>` on an existing database after adding or
  changing a stored field, a SQL constraint or an index: it reports a constraint that existing rows
  violate.
- `oasis --project <root> verify-module --compact library` before handing over.
