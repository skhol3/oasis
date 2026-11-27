# Recipe: computed fields, constraints, indexes and create/write overrides

Checked against: 15.0, 19.0.

Official docs: [19.0](https://www.odoo.com/documentation/19.0/developer/reference/backend/orm.html#constraints-and-indexes), [15.0](https://www.odoo.com/documentation/15.0/developer/reference/backend/orm.html)

Part of the [backend skill](../SKILL.md). Paths in `path:line` are relative to the Odoo source root: a bare
path is the 19.0 source (commit 8a2481dfc), a path marked 15.0 is the 15.0 source (commit 3a28e5b0). The
example, the `library.loan` of the `library` module the recipes build ([module.md](module.md)), follows
`addons/lunch/models/lunch_order.py`, `lunch_product.py` and `lunch_supplier.py`.

## When to use

A value derived from other fields (`compute=`), editable or searchable derived values (`inverse=`,
`search=`), a rule records must satisfy (`@api.constrains`, a SQL constraint), a database index, or logic
that must run on every `create` or `write`. The model itself is in [model.md](model.md).

## Files

1. `library/models/library_loan.py`: the fields, their compute/inverse/search methods, the constraints and
   the overrides, in that order inside the class (fields, SQL objects, computes, constraints, CRUD).
2. `library/models/__init__.py`: `from . import library_loan` ([module.md](module.md)).
3. `library/security/ir.model.access.csv`: the rows for `model_library_loan`
   ([access recipe](../../odoo-security/references/access.md)).
4. A stored field added or changed on an installed module needs a module update, which adds the column
   and computes the stored values of existing records.

The book of [model.md](model.md) carries the other two constraints of the module: `_name_unique`
(`models.Constraint('UNIQUE (name)', ...)`) and `_check_pages` (`@api.constrains('pages')`).

## Example

`library/models/library_loan.py`, on the book of [model.md](model.md):

```python
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

How the parts behave, in both series unless *Changed in* says otherwise:

- A computed field is not stored unless `store=True`; `readonly=False` makes it editable. Its method assigns
  the field on every record of `self`, never returns it.
- `@api.depends` lists every field the method reads, dotted paths included; on a change of one of them the
  ORM recomputes (stored) or invalidates (not stored). Leaving a path out is how a value is frozen on
  purpose: `duration` depends on `book_id`, not `book_id.loan_duration`, so a later change of the book's
  loan days does not rewrite past loans, as `addons/lunch/models/lunch_order.py:225-228` depends on
  `product_id`, not `product_id.price`. A dependency on `id` is refused
  (`odoo/orm/decorators.py:269`); use `@api.depends_context` for context keys (`uid`, `company`).
- `inverse` receives the records whose computed value was written and writes the sources (here the
  borrower's `email`; `addons/lunch/models/lunch_product.py:32`, `:104`).
- `search` receives an operator and a value and returns a domain that replaces the condition
  (`odoo/orm/fields.py:145-170`, `addons/lunch/models/lunch_product.py:82-85`).
- `@api.constrains` runs after `create`/`write` (and after a stored compute) on the records where one of
  the named fields changed, and raises `ValidationError` (`odoo/orm/decorators.py:92-120`,
  `odoo/orm/models.py:4960-4966`). Only plain field names: dotted names are ignored, and a field neither
  stored nor inversible logs "is not writeable" (`odoo/orm/models.py:539-541`).
- A SQL constraint checks one row in the database, faster and race-free (`_duration_positive`, the book's
  `_name_unique`); anything that reads other records or relations is a Python constraint (`_check_copies`
  counts the open loans of the book).
- `create` takes a list of value dicts under `@api.model_create_multi` and returns the recordset of super;
  a caller may still pass one dict, which the decorator wraps in a list (official ORM page: "The method may
  be called with either a single dict or a list of dicts"; `odoo/orm/decorators.py:357-369`, 15.0
  `odoo/api.py:421`). `write` takes one dict for every record of `self` and returns `True` (`odoo/orm/models.py:4340`).

## Changed in

| Point | Since | Before | Source |
|---|---|---|---|
| SQL constraint: a `models.Constraint(definition, message)` class attribute whose name starts with `_`; `_sql_constraints` is ignored with "Model attribute '_sql_constraints' is no longer supported" | 19.0 | `_sql_constraints = [(name, definition, message)]` (15.0 `odoo/models.py:497`; 15.0 `addons/lunch/models/lunch_supplier.py:110-114`) | `odoo/orm/table_objects.py:79`, `odoo/orm/model_classes.py:162-164`, `addons/lunch/models/lunch_supplier.py:116` |
| Index on several columns: `models.Index('(col_a, col_b)')` or `models.UniqueIndex(definition, message)` | 19.0 | raw SQL in `init()`: `CREATE INDEX IF NOT EXISTS` or `tools.create_index` (15.0 `addons/lunch/models/lunch_order.py:79-81`; 15.0 `odoo/tools/sql.py:223`) | `odoo/orm/table_objects.py:125`, `odoo/orm/table_objects.py:185`, `addons/lunch/models/lunch_order.py:64` |
| Search method: gets normalized operators (`=` becomes `in`; a boolean condition arrives as `in` or `not in` with `[True]`), returns `NotImplemented` for an operator it does not handle, and builds a `Domain` | 19.0 | gets the operator as written (`=`, `!=`, ...), handles each itself and returns a domain list (15.0 `addons/lunch/models/lunch_supplier.py:286-303`) | `odoo/orm/fields.py:145-170`, `addons/lunch/models/lunch_supplier.py:324-335` |
| Domains are combined with `Domain` objects (`from odoo.fields import Domain`, `&`, `~`); `odoo.osv.expression.AND`/`OR` warn "Since 19.0, use odoo.fields.Domain" | 19.0 | `expression.AND([...])`, `expression.OR([...])` (15.0 `addons/lunch/models/lunch_product.py:96-98`) | `odoo/osv/expression.py:242`, `odoo/fields/__init__.py:20` |
| `@api.model` on `create` turns it into `model_create_multi`: the method receives a list | 19.0 | `@api.model` on `create` wraps a single-dict method (`model_create_single`, 15.0 `odoo/api.py:382-383`); `@api.model_create_multi` exists in both (15.0 `odoo/api.py:421`) | `odoo/orm/decorators.py:322-323`, `odoo/orm/decorators.py:357` |
| Grouped values in code: `_read_group(domain, groupby, aggregates)` returns tuples, for example `_read_group([...], ['category_id'], ['__count'])`; `read_group` is deprecated "Since 19.0" | 19.0 | `read_group(domain, fields, groupby, ...)` returns dicts such as `category_id_count` (15.0 `odoo/models.py:2412`; 15.0 `addons/lunch/models/lunch_product_category.py:30-31`) | `odoo/orm/models.py:1867`, `odoo/orm/models.py:2754`, `addons/lunch/models/lunch_product_category.py:30-31` |
| Cache before raw SQL: `flush_model(fnames)`, `flush_recordset(fnames)`, `invalidate_model(fnames)`, `invalidate_recordset(fnames)` | 19.0 | `flush(fnames, records)` and `invalidate_cache(fnames, ids)` (15.0 `odoo/models.py:5668`, `5982`; 15.0 `addons/lunch/models/lunch_supplier.py:201`) | `odoo/orm/models.py:6372`, `odoo/orm/models.py:6386`, `odoo/orm/models.py:6728`, `odoo/orm/models.py:6743`, `addons/lunch/models/lunch_supplier.py:211` |
| Raw SQL is composed with `odoo.tools.SQL("... %s", value)` and run with `self.env.cr.execute(sql)` | 19.0 | a query string and a parameter list: `cr.execute(query, params)`; no `SQL` | `odoo/tools/sql.py:46` |
| `self._cr`, `self._uid`, `self._context` warn "Deprecated since 19.0"; use `self.env.cr`, `self.env.uid`, `self.env.context` | 19.0 | `self._cr` everywhere (15.0 `addons/lunch/models/lunch_order.py:80`) | `odoo/orm/models.py:5931` |
| Translated messages: `self.env._("...")` (`from odoo import _` still works) | 19.0 | `from odoo import _` only | `odoo/orm/environments.py:315` |
| Archive side effects: override `action_archive`/`action_unarchive`; `toggle_active` is "Deprecated since 19.0" | 19.0 | override `toggle_active` (15.0 `addons/lunch/models/lunch_product_category.py:35`) | `odoo/orm/models.py:5808`, `addons/lunch/models/lunch_product_category.py:41-47` |

A *Since* the source does not state is 19.0: the point changed after 15.0, by 19.0 at the latest.

On 15.0 the example's SQL objects are written
`_sql_constraints = [('duration_positive', 'CHECK (duration > 0)', 'The loan duration must be positive.')]` (and
the book's `[('name_unique', 'UNIQUE (name)', 'A book with this title already exists.')]`) and an
`init()` that runs `tools.create_index(self._cr, 'library_loan_book_date_idx', self._table, ['book_id', 'date'])`;
its search method handles `=` and `!=` with `True` or `False` itself and returns a domain list, as 15.0
`addons/lunch/models/lunch_supplier.py:286-303` does; and its message uses `_` from `odoo`. The database name
is `<table>_<name>` in both (`odoo/orm/table_objects.py:55-58`; 15.0 `odoo/models.py:753`), so a constraint
keeps its name when the code moves from `_sql_constraints` to `models.Constraint`.

## Mistakes

- `create(self, vals)` with a single dict, or a loop that calls `super().create(vals)` per dict: on 19.0 the
  method receives a list; everywhere it defeats batch creation. Decorate with `@api.model_create_multi`,
  change the dicts, call `super().create(vals_list)` once.
- `write` that does not return the result of `super().write(vals)`, or that mutates the caller's dict
  in place when it is shared (copy it, as the example does).
- `@api.depends` missing a field the method reads, or a dotted path left out by accident: the stored value
  silently goes stale. Add every input, or freeze on purpose and say so.
- A compute method that assigns only some records of `self` (an `if` without `else`): a non-stored
  read-only field raises "Compute method failed to assign", other fields silently get an empty value (`odoo/orm/fields.py:1757`; 15.0 `odoo/fields.py:1141`). Assign every record.
- A compute that returns a value, or that calls `write` on `self` instead of assigning the field.
- `@api.constrains('book_id.copies')`: dotted names are ignored; constrain the local field and
  read the related value inside.
- A constraint on a field that create does not receive (not in the form, no default): it does not run on
  create; give the field a default or check in `create`.
- `_sql_constraints` on 19.0: ignored with a warning, so the rule is silently missing. `models.Constraint` on
  15.0: an `AttributeError` on `models`.
- A `models.Constraint` or `models.Index` attribute without the leading `_`: assertion "Names of SQL objects
  in a model must start with '_'" (`odoo/orm/table_objects.py:44`).
- A search method that ignores `operator`/`value`, or that returns `[]` for an unsupported operator (it
  matches everything); on 19.0 return `NotImplemented`.
- Raw SQL without flushing the fields it reads first (`flush_model`), or without invalidating what it
  writes; string formatting of values into the query instead of parameters (`SQL` on 19.0, `params` on
  15.0).

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
