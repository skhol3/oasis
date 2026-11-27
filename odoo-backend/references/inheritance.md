# Recipe: model inheritance (`_inherit`, `_inherits`, mixins)

Checked against: 15.0, 19.0.

Official docs: [19.0](https://www.odoo.com/documentation/19.0/developer/reference/backend/orm.html#inheritance-and-extension), [15.0](https://www.odoo.com/documentation/15.0/developer/reference/backend/orm.html#inheritance-and-extension)

Part of the [backend skill](../SKILL.md). Paths in `path:line` are relative to the Odoo source root: a bare
path is the 19.0 source (commit 8a2481dfc), a path marked 15.0 is the 15.0 source (commit 3a28e5b0). The
example follows `addons/lunch/models/res_users.py` (extension), `addons/lunch/models/lunch_supplier.py`
(mixins), `addons/product/models/product_product.py` and `odoo/addons/base/models/res_users.py`
(delegation).

## When to use

Pick the form by what must happen to the table and the records:

| Goal | Write | Table and records |
|---|---|---|
| Add fields or change methods of an existing model | `_inherit = 'res.partner'` (a string, no `_name`) | the same table and records; every user of the model sees the change |
| Add mixins to an existing model | `_name = 'res.partner'` and `_inherit = ['res.partner', 'mail.activity.mixin']` (`addons/mail/models/res_partner.py:15-16`) | the same table, with the mixin's fields and methods |
| A new model built from another one or from mixins (prototype) | a new `_name` and `_inherit = ['mail.thread', 'mail.activity.mixin']` | a new table with copies of the parent's fields; no record is shared |
| A new model whose records each own a record of another model (delegation) | `_inherits = {'res.partner': 'partner_id'}` and that required `Many2one` | a new table with only its own fields; the parent's fields are read and written on the linked record |

The 19.0 ORM page says "`_inherits` is more or less implemented, avoid it if you can": use delegation only
when each record must own a record of the parent, as `product.product` and `res.users` do. No official page
of either series covers mixins (`mail.thread`, `mail.activity.mixin`); the mixin rows rely on the source
(`addons/mail/models/res_partner.py:15-16`, `addons/mail/models/mail_thread.py:502-504`).

Views of an inherited model are extended with XPath in the [views skill](../../odoo-views-frontend/SKILL.md).

## Files

1. `library/__manifest__.py`: `depends` lists the module of every model inherited (`mail` for `mail.thread`
   and `mail.activity.mixin`; `base` holds `res.partner`).
2. `library/models/res_partner.py`: the extension, named after the extended model.
3. `library/models/library_author.py`: the new model with mixins and delegation.
4. `library/models/__init__.py`: `res_partner` after the files that define the module's own models
   ([module.md](module.md)).
5. `library/security/ir.model.access.csv`: the rows for `model_library_author` (an extension needs none;
   [access recipe](../../odoo-security/references/access.md)).
6. `library/views/library_author_views.xml`: the form with the chatter, after the CSV in `data`. The
   partner form gets the new fields through view inheritance
   ([view-inheritance.md](../../odoo-views-frontend/references/view-inheritance.md)).

## Example

`library/__manifest__.py` (the final manifest of [module.md](module.md)):

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

`library/models/res_partner.py`: an extension adds fields and overrides a method, calling `super()`; the
first three fields are the ones the partner form shows
([view-inheritance.md](../../odoo-views-frontend/references/view-inheritance.md)):

```python
from odoo import api, fields, models
from odoo.exceptions import UserError


class ResPartner(models.Model):
    _inherit = 'res.partner'

    library_card = fields.Char()
    library_member_since = fields.Date()
    library_note = fields.Text()
    library_loan_ids = fields.One2many('library.loan', 'borrower_id', string='Library Loans')
    library_loan_count = fields.Integer(compute='_compute_library_loan_count')

    @api.depends('library_loan_ids')
    def _compute_library_loan_count(self):
        for partner in self:
            partner.library_loan_count = len(partner.library_loan_ids)

    def action_archive(self):
        if self.library_loan_ids.filtered(lambda loan: not loan.date_returned):
            raise UserError(self.env._("Return the open loans of these contacts before archiving them."))
        return super().action_archive()
```

`library/models/library_author.py`: mixins (prototype) plus delegation to `res.partner`, as `product.product`
combines `_inherits` with `mail.thread` (`addons/product/models/product_product.py:19-20`); the book's
`author_id` points to it ([model.md](model.md)):

```python
from odoo import fields, models


class LibraryAuthor(models.Model):
    _name = 'library.author'
    _description = 'Library Author'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _inherits = {'res.partner': 'partner_id'}

    partner_id = fields.Many2one('res.partner', required=True, ondelete='cascade', index=True)
    book_ids = fields.One2many('library.book', 'author_id', string='Books')
    genre = fields.Selection(
        [('fiction', 'Fiction'), ('non_fiction', 'Non-fiction'), ('poetry', 'Poetry')],
        default='fiction', tracking=True,
    )
```

`library/views/library_author_views.xml`: `name`, `email` and `phone` are the partner's, shown as the
author's own:

```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <record id="library_author_view_form" model="ir.ui.view">
        <field name="name">library.author.form</field>
        <field name="model">library.author</field>
        <field name="arch" type="xml">
            <form>
                <sheet>
                    <group>
                        <field name="name"/>
                        <field name="email"/>
                        <field name="phone"/>
                        <field name="genre"/>
                    </group>
                </sheet>
                <chatter/>
            </form>
        </field>
    </record>
</odoo>
```

How it behaves, in both series unless *Changed in* says otherwise:

- Redefining a field in an extension changes only the attributes you pass; the others stay. Extend a
  selection with `selection_add=[('value', 'Label')]` and, when the field is required, an `ondelete` policy
  per new value (`ondelete={'value': 'cascade'}`, or `'set default'` when the field has a default); a
  required field without one is refused
  (`odoo/orm/fields_selection.py:136`; 15.0 `odoo/fields.py:2451`).
- A method override calls `super()` and returns its result, unless replacing the behavior is the point.
- With `_inherits`, creating an author creates its partner from the partner's values; fields defined
  locally win over the parent's (`odoo/orm/model_classes.py:492-494`); deleting the partner deletes the
  author (`ondelete='cascade'`), deleting the author leaves the partner.
- `tracking=True` is accepted only on models that inherit `mail.thread` (`addons/mail/models/mail_thread.py:502-504`;
  15.0 `addons/mail/models/mail_thread.py:448-450`).

## Changed in

| Point | Since | Before | Source |
|---|---|---|---|
| `_inherit` as a list without `_name`: `_name` comes from the class name, with "Class ... has no _name, please make it explicit"; only a string `_inherit` sets `_name` to the extended model | 19.0 | a one-item list also extended that model: `_name` was `inherit[0]` (15.0 `odoo/models.py:174`) | `odoo/orm/models.py:241-249` |
| `_inherits` without its `Many2one` field, or with one not required with `ondelete='cascade'` or `'restrict'`: `TypeError` | 19.0 | the field was created, or forced to required and cascade, with a log line (15.0 `odoo/models.py:2953-2962`) | `odoo/orm/model_classes.py:468-477` |
| `delegate=True` on a `Many2one` without the model in `_inherits`: `TypeError` | 19.0 | the model was added to `_inherits` (15.0 `odoo/models.py:2964-2971`) | `odoo/orm/fields_relational.py:260-264` |
| `bypass_search_access=True` on a `Many2one` (set automatically on a delegation field) | 19.0 | `auto_join=True` (15.0 `odoo/fields.py:2704`; 15.0 `odoo/addons/base/models/res_users.py:350`) | `odoo/orm/fields_relational.py:39`, `odoo/addons/base/models/res_users.py:214` |
| The chatter of a `mail.thread` form: `<chatter/>` after `</sheet>` | 19.0 | `<div class="oe_chatter">` with the fields `message_follower_ids`, `activity_ids`, `message_ids` (15.0 `addons/lunch/views/lunch_supplier_views.xml:112-116`) | `addons/lunch/views/lunch_supplier_views.xml:109` |

A *Since* the source does not state is 19.0: the point changed after 15.0, by 19.0 at the latest.

On 15.0 the example's view replaces `<chatter/>` with that `oe_chatter` block; the rest of the example is the
same.

## Mistakes

- `_inherit = ['res.partner']` (a list) without `_name` on 19.0: unless the class name happens to spell the
  model, it defines a new model. Write the string form for an extension.
- A new `_name` with `_inherit = 'res.partner'` when an extension was meant: it creates a second table that
  copies the partner fields, and nothing that uses `res.partner` sees the new field.
- `depends` without the module of an inherited model: "Model ... inherits from non-existing model ..."
  (`odoo/orm/model_classes.py:196`; 15.0 `odoo/models.py:643`), or it works only where that module happens
  to be installed first.
- Extending an `AbstractModel` such as `mail.thread` with a `models.Model` class under the same `_name`:
  "transforms the abstract model ... into a non-abstract model" (`odoo/orm/model_classes.py:236`; 15.0
  `odoo/models.py:683`).
- `selection=` instead of `selection_add=` in an extension: it replaces the list, with the warning
  "overrides existing selection; use selection_add instead" (`odoo/orm/fields_selection.py:110`).
- A method override that does not call `super()`, drops its return value, or changes its signature:
  other modules' overrides of the same method stop running.
- With `_inherits`, a local field with the name of a parent field: it hides the parent's, so the value is
  no longer the partner's.
- `tracking=True` on a model without `mail.thread`: "unknown parameter" warning and no tracking.
- A 15.0 `oe_chatter` block on 19.0: the form compiler builds the chatter only from `<chatter/>`
  (`addons/mail/static/src/chatter/web/form_compiler.js:46-49`), so no chatter appears. On 15.0 write the
  `oe_chatter` block.

## Verify

- `oasis --project <root> model-info res.partner --module library` (Gentle Shell: `oasis_model_info`) shows
  only what `library` adds to the model; without `--module` it lists every extending module and field
  overrides.
- `oasis --project <root> model-info library.author` shows the inherited mixins and the delegation.
- `oasis --project <root> view-info library.author` lists the views of the model and what extends them.
- `oasis --project <root> verify-module --compact library` installs on a fresh database (so a missing
  `depends` shows), updates and tests; `oasis --project <root> test-module --compact library` with a test that
  creates an author and reads `partner_id.name`.
