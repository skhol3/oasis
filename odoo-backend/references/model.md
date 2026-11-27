# Recipe: a new model and its fields

Checked against: 15.0, 19.0.

Official docs: [19.0](https://www.odoo.com/documentation/19.0/developer/reference/backend/orm.html), [15.0](https://www.odoo.com/documentation/15.0/developer/reference/backend/orm.html)

Part of the [backend skill](../SKILL.md). Paths in `path:line` are relative to the Odoo source root: a bare
path is the 19.0 source (commit 8a2481dfc), a path marked 15.0 is the 15.0 source (commit 3a28e5b0). The
example, the `library.book` of the `library` module the recipes build ([module.md](module.md)), follows
`addons/lunch/models/lunch_product.py` and `lunch_supplier.py` (fields, company and currency) and `addons/analytic/models/analytic_account.py` (display name and name search).

## When to use

A module needs a new business object (its own table): a `models.Model` with `_name`. For a field added to
an existing model use `_inherit` ([inheritance.md](inheritance.md)); computed fields, constraints and
`create`/`write` overrides are in [compute-constraint.md](compute-constraint.md); the module skeleton is in
[module.md](module.md).

## Files

1. `library/models/library_book.py`: one model per file, file named after the model. The second model,
   `library.loan`, is in [compute-constraint.md](compute-constraint.md); `library.author` in
   [inheritance.md](inheritance.md).
2. `library/models/__init__.py`: `from . import library_book` among the imports of [module.md](module.md).
3. `library/security/ir.model.access.csv`: one row per new model (`model_library_book`), in the
   [access recipe](../../odoo-security/references/access.md).
4. Views, the action and the menu: the [views recipe](../../odoo-views-frontend/references/views.md), listed
   in the manifest `data` after the CSV.

## Example

`library/models/library_book.py`, final: it holds every field the later recipes use (`user_id` and
`company_id` for the record rules, `pages` and `copies` for the views, the widget and the tests):

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
    author_id = fields.Many2one('library.author', index=True)
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
    loan_ids = fields.One2many('library.loan', 'book_id', string='Loans')

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

What each part does, in both series unless *Changed in* says otherwise:

- `_description` is the label users see; a model without it logs "The model ... has no _description"
  (`odoo/orm/model_classes.py:275`; 15.0 `odoo/models.py:717`).
- `_order` is the default `ORDER BY` of `search` and of the list view; end it with `id` so the order is
  stable. The default is `'id'` (`odoo/orm/models.py:434`).
- `_rec_name` names the field that labels a record; it defaults to `name` when the model has one (the book
  needs none), and a name that is not a field fails with "Invalid _rec_name" (`odoo/orm/model_classes.py:435-439`;
  15.0 `odoo/models.py:3038-3040`). The loan of [compute-constraint.md](compute-constraint.md) has no `name`
  and sets `_rec_name = 'book_id'`.
- `display_name` is computed by `_compute_display_name` from `_rec_name` (`odoo/orm/models.py:1437-1452`);
  override it, with `@api.depends` on the fields it reads, to build another label. `_rec_names_search` lists
  the fields a name search looks in (`odoo/orm/models.py:433`, used by `_search_display_name` at `:1455`).
- `Monetary` takes its currency from `currency_field`, which defaults to `currency_id`
  (`odoo/orm/fields_numeric.py:223-228`); the named field must exist on the model, or setup fails with
  "Field ... with unknown currency_field" (`:234`). A related `currency_id`, as here and in
  `addons/lunch/models/lunch_product.py:26`, is the usual source.
- `Many2one` with `required=True` defaults to `ondelete='restrict'` (`company_id`), otherwise to
  `'set null'` (`author_id`); `required` with `'set null'` is refused (`odoo/orm/fields_relational.py:282-286`).
  `One2many` needs the comodel's `Many2one` back to this model (`library.loan.book_id` for `loan_ids`). Write
  `One2many`/`Many2many` values with `Command` (`from odoo.fields import Command`, both series:
  `odoo/fields/__init__.py:19`; 15.0 `odoo/fields.py:3002`).
- `Selection` takes a list of `(value, label)` pairs; extend it from another module with `selection_add`
  ([inheritance.md](inheritance.md)).
- `company_id` with `default=lambda self: self.env.company` and the `with_company`, `check_company=True` and
  `_check_company_auto` attributes work the same in both series (`addons/lunch/models/lunch_product.py:16-25`);
  the multi-company record rule of [record-rules.md](../../odoo-security/references/record-rules.md) filters
  on it.
- `_name_unique` (a SQL constraint) and `_check_pages` (a Python constraint) are explained in
  [compute-constraint.md](compute-constraint.md); [model-tests.md](../../odoo-testing/references/model-tests.md)
  tests both.

## Changed in

| Point | Since | Before | Source |
|---|---|---|---|
| The ORM lives in `odoo/orm/` (`models.py`, `fields*.py`, `decorators.py`, `environments.py`, `commands.py`), re-exported by `odoo/fields`, `odoo/models` and `odoo/api`; read field and model behavior there | 19.0 | `odoo/models.py`, `odoo/fields.py` and `odoo/api.py` (15.0) | `odoo/fields/__init__.py:5`, `odoo/models/__init__.py:7`, `odoo/api/__init__.py:5` |
| Display name: override `_compute_display_name` and set `record.display_name`; `name_get` no longer exists | 19.0 | override `name_get` and return `(id, name)` pairs (15.0 `odoo/models.py:1845`; 15.0 `addons/analytic/models/analytic_account.py:145`) | `odoo/orm/models.py:1438`, `addons/analytic/models/analytic_account.py:105` |
| Name search: list the fields in `_rec_names_search`, or override `_search_display_name(operator, value)` and return a domain; `_name_search` no longer exists | 19.0 | override `_name_search(name, args, operator, limit, name_get_uid)` (15.0 `odoo/models.py:1917`; 15.0 `addons/analytic/models/analytic_account.py:157`) | `odoo/orm/models.py:433`, `odoo/orm/models.py:1455`, `addons/analytic/models/analytic_account.py:18` |
| Field aggregation: `aggregator='sum'` (`avg`, `max`, ...); `group_operator` is a deprecated alias | 18.0 | `group_operator=` (15.0 `odoo/fields.py:285`) | `odoo/orm/fields.py:486` |
| Field index kinds: `index=True` or `'btree'`, `'btree_not_null'`, `'trigram'` | 19.0 | a boolean only (15.0 `odoo/fields.py:140`) | `odoo/orm/fields.py:109-117`, `addons/analytic/models/analytic_account.py:22` |

A *Since* the source does not state is 19.0: the point changed after 15.0, by 19.0 at the latest.

## Mistakes

- No `_description`, or no ACL row: the model works for the superuser only, with a warning in the log.
- `_rec_name` left to its default on a model without `name`: the label becomes `library.loan,7` and name
  search warns "Cannot search on display_name" (`odoo/orm/models.py:1466`). Set `_rec_name` or override the
  display name.
- A `_compute_display_name` override without `@api.depends` on the fields it reads: the label stays stale
  in the cache after those fields change.
- `name_get` or `_name_search` written on 19.0 (copied from 15.0 code): they are never called, so the label
  and search silently stay the default. Reverse on 15.0: `_compute_display_name` alone does not change what
  `name_get` returns.
- `Monetary` without a currency field on the model (`currency_id` missing or named differently): setup
  fails at install.
- `One2many` whose inverse name is not a `Many2one` of the comodel pointing back: setup fails.
- `ondelete='set null'` on a required `Many2one`: refused at setup; use `'restrict'` or `'cascade'`.
- 19.0 attributes written on 15.0: `aggregator=` only logs "Field ...: unknown parameter" (15.0
  `odoo/fields.py:479`) and the aggregation is missing; `index='trigram'` is merely truthy there and creates
  a plain btree index (15.0 `odoo/modules/registry.py:473-477`).
- A `_name` of another module's model, or a new `_name` that also lists itself in `_inherit`: that is an
  extension, not a new model ([inheritance.md](inheritance.md)).

## Verify

- `oasis --project <root> model-info library.book` (Gentle Shell: `oasis_model_info`) lists the fields,
  their attributes and the methods as defined in source; `--field price` shows one field and its overrides.
- `oasis --project <root> module-info library --section models` lists the models the module defines and
  extends; `--section security` the ACL rows per model.
- `oasis --project <root> verify-module --compact library` installs on a fresh database, updates and runs
  the tests; a new stored field also needs `oasis --project <root> update-module --compact library <database>`
  on an existing database.
