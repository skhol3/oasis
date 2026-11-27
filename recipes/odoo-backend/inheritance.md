# Recipe: model inheritance (`_inherit`, `_inherits`, mixins)

Checked against: every series.

Official docs: 15.0=https://www.odoo.com/documentation/15.0/developer/reference/backend/orm.html#inheritance-and-extension, 19.0=https://www.odoo.com/documentation/19.0/developer/reference/backend/orm.html#inheritance-and-extension

Part of the [backend skill](../../SKILL.md). A path in `path:line` is relative to the Odoo source root of the
series written before it (15.0 at commit 3a28e5b0, 19.0 at commit 8a2481dfc), or of this series when none is
written. The example follows `addons/lunch/models/res_users.py` (extension),
`addons/lunch/models/lunch_supplier.py` (mixins), `addons/product/models/product_product.py` and
`odoo/addons/base/models/res_users.py` (delegation).

## When to use

Pick the form by what must happen to the table and the records:

| Goal | Write | Table and records |
|---|---|---|
| Add fields or change methods of an existing model | `_inherit = 'res.partner'` (a string, no `_name`) | the same table and records; every user of the model sees the change |
| Add mixins to an existing model | `_name = 'res.partner'` and `_inherit = ['res.partner', 'mail.activity.mixin']` | the same table, with the mixin's fields and methods |
| A new model built from another one or from mixins (prototype) | a new `_name` and `_inherit = ['mail.thread', 'mail.activity.mixin']` | a new table with copies of the parent's fields; no record is shared |
| A new model whose records each own a record of another model (delegation) | `_inherits = {'res.partner': 'partner_id'}` and that required `Many2one` | a new table with only its own fields; the parent's fields are read and written on the linked record |

`addons/mail/models/res_partner.py` adds mixins to the partner that way (15.0 lines 13-14, 19.0 lines 15-16).
The 19.0 ORM page says "`_inherits` is more or less implemented, avoid it if you can": use delegation only
when each record must own a record of the parent, as `product.product` and `res.users` do. No official page
of either series covers mixins (`mail.thread`, `mail.activity.mixin`); the mixin rows rely on the source.

Views of an inherited model are extended with XPath: the `view-inheritance` recipe of `odoo-views-frontend`.

## Files

1. `library/__manifest__.py`: `depends` lists the module of every model inherited (`mail` for `mail.thread`
   and `mail.activity.mixin`; `base` holds `res.partner`). The manifest is the one of [module.md](module.md).
2. `library/models/res_partner.py`: the extension, named after the extended model.
3. `library/models/library_author.py`: the new model with mixins and delegation.
4. `library/models/__init__.py`: `library_author` before `res_partner`, the extension of another module's
   model last ([module.md](module.md)).
5. `library/security/ir.model.access.csv`: the rows of `model_library_author` (an extension needs none;
   [module.md](module.md)).
6. `library/views/library_author_views.xml`: the form with the chatter, after the CSV in `data`. The
   partner form gets the new fields through view inheritance (the `view-inheritance` recipe).

## Example

`library/__manifest__.py`, the manifest of [module.md](module.md) (building only this piece, keep the
`security/ir.model.access.csv` and `views/library_author_views.xml` entries of `data` and drop `assets`):

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

`library/models/res_partner.py`: an extension adds fields and overrides a method, calling `super()`; the
fields are the ones the partner form of the `view-inheritance` recipe shows:

```python
from odoo import api, fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    library_card = fields.Char(copy=False)
    library_member_since = fields.Date()
    library_note = fields.Text()

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('library_card') and not vals.get('library_member_since'):
                vals['library_member_since'] = fields.Date.context_today(self)
        return super().create(vals_list)
```

`library/models/library_author.py`: mixins (prototype) plus delegation to `res.partner`, as `product.product`
combines `_inherits` with `mail.thread` (15.0 `addons/product/models/product.py:81-82`; 19.0
`addons/product/models/product_product.py:19-20`). Each author owns a contact, `partner_id`, which is what the
book's `author_id` of [model.md](model.md) points to:

```python
from odoo import fields, models


class LibraryAuthor(models.Model):
    _name = 'library.author'
    _description = 'Library Author'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _inherits = {'res.partner': 'partner_id'}

    partner_id = fields.Many2one('res.partner', required=True, ondelete='cascade', index=True)
    genre = fields.Selection(
        [('fiction', 'Fiction'), ('non_fiction', 'Non-fiction'), ('poetry', 'Poetry')],
        default='fiction', tracking=True,
    )
```

`library/views/library_author_views.xml`: `name`, `email` and `phone` are the partner's, shown as the
author's own:

```xml id=chatter since=15.0
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
                <div class="oe_chatter">
                    <field name="message_follower_ids"/>
                    <field name="activity_ids"/>
                    <field name="message_ids"/>
                </div>
            </form>
        </field>
    </record>
</odoo>
```

```xml id=chatter since=19.0
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

How it behaves:

- Redefining a field in an extension changes only the attributes you pass; the others stay. Extend a
  selection with `selection_add=[('value', 'Label')]` and, when the field is required, an `ondelete` policy
  per new value (`ondelete={'value': 'cascade'}`, or `'set default'` when the field has a default); a
  required field without one is refused (15.0 `odoo/fields.py:2449-2451`; 19.0
  `odoo/orm/fields_selection.py:134-136`).
- A method override calls `super()` and returns its result, unless replacing the behavior is the point. The
  partner's `create` keeps the batch form of the method it overrides.
- With `_inherits`, creating an author creates its partner from the partner's values; fields defined
  locally win over the parent's (15.0 `odoo/models.py:2934`; 19.0 `odoo/orm/model_classes.py:492-494`);
  deleting the partner deletes the author (`ondelete='cascade'`), deleting the author leaves the partner.
- `tracking=True` is accepted only on models that inherit `mail.thread` (15.0
  `addons/mail/models/mail_thread.py:448-450`; 19.0 `addons/mail/models/mail_thread.py:502-504`).

<!-- since=15.0 id=chatter-form -->
- The chatter of a `mail.thread` form is a `<div class="oe_chatter">` after `</sheet>` holding the fields
  `message_follower_ids`, `activity_ids` and `message_ids` (`addons/lunch/views/lunch_supplier_views.xml:112-116`).
<!-- end -->

<!-- since=19.0 id=chatter-form -->
- The chatter of a `mail.thread` form is `<chatter/>` after `</sheet>`
  (`addons/lunch/views/lunch_supplier_views.xml:109`); the form compiler builds it only from that tag.
<!-- end -->

<!-- since=15.0 id=inherit-list -->
- `_inherit` as a one-item list without `_name` also extends that model: `_name` becomes `_inherit[0]`
  (`odoo/models.py:170-174`); a longer list without `_name` takes the class name. Write the string form anyway.
<!-- end -->

<!-- since=19.0 id=inherit-list -->
- Only a string `_inherit` sets `_name` to the extended model; a list without `_name` takes `_name` from the
  class name and logs "Class ... has no _name, please make it explicit" (`odoo/orm/models.py:241-249`).
<!-- end -->

<!-- since=15.0 id=inherits-field -->
- `_inherits` without its `Many2one` field gets one created, and a field that is not required with
  `ondelete='cascade'` or `'restrict'` is forced to required and cascade, with a log line; a `Many2one` with
  `delegate=True` adds its model to `_inherits` (`odoo/models.py:2950-2972`). Declare the field as the example
  does.
<!-- end -->

<!-- since=19.0 id=inherits-field -->
- `_inherits` without its `Many2one` field, or with one that is not required with `ondelete='cascade'` or
  `'restrict'`, is a `TypeError` (`odoo/orm/model_classes.py:466-477`); the field becomes the delegation
  field by itself, and `delegate=True` on a `Many2one` whose model is not in `_inherits` is a `TypeError`
  (`odoo/orm/fields_relational.py:255-264`).
<!-- end -->

<!-- since=15.0 id=search-access-join -->
- A delegation field searches its parent with `auto_join=True` (`odoo/fields.py:2704`; as
  `odoo/addons/base/models/res_users.py:350` declares on `partner_id`).
<!-- end -->

<!-- since=19.0 id=search-access-join -->
- A delegation field gets `bypass_search_access=True` by itself (`odoo/orm/fields_relational.py:256-259`); on
  another `Many2one` that attribute replaces `auto_join` (`odoo/orm/fields_relational.py:39`; as
  `odoo/addons/base/models/res_users.py:214` declares on `partner_id`).
<!-- end -->

## Mistakes

### Write an extension with a string `_inherit`

<!-- since=15.0 id=inherit-rule -->
Why: a list of the model plus a mixin without `_name` takes the class name as `_name`, so it defines a new
model instead of extending the partner.

Exceptions: adding mixins to an existing model takes a list, with `_name` set to that model.

```python
from odoo import fields, models


class LibraryPartner(models.Model):
    _inherit = ['res.partner', 'mail.activity.mixin']

    library_card = fields.Char()
```

```python
from odoo import fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    library_card = fields.Char()
```
<!-- end -->

<!-- since=19.0 id=inherit-rule -->
Why: a list without `_name` takes `_name` from the class name, so unless the class name spells the model it
defines a new model instead of extending it.

Exceptions: adding mixins to an existing model takes a list, with `_name` set to that model.

```python
from odoo import fields, models


class LibraryPartner(models.Model):
    _inherit = ['res.partner', 'mail.activity.mixin']

    library_card = fields.Char()
```

```python
from odoo import fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    library_card = fields.Char()
```
<!-- end -->

### Extend a model instead of copying it when its users must see the change

Why: a new `_name` with `_inherit = 'res.partner'` creates a second table that copies the partner fields, and
nothing that uses `res.partner` sees the new field.

Exceptions: a prototype is meant: a model of its own that reuses another's fields.

```python
from odoo import fields, models


class LibraryMember(models.Model):
    _name = 'library.member'
    _description = 'Library Member'
    _inherit = 'res.partner'

    library_card = fields.Char()
```

```python
from odoo import fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    library_card = fields.Char()
```

### Depend on the module of every inherited model

Why: "Model ... inherits from non-existing model ..." on a fresh database (15.0 `odoo/models.py:642-643`;
19.0 `odoo/orm/model_classes.py:195-196`), or a module that works only where the other one happens to be
installed first.

Exceptions: `base`, which every module gets.

```python
{'name': 'Library', 'depends': ['base']}
```

```python
{'name': 'Library', 'depends': ['mail', 'web']}
```

### Extend an abstract model with an abstract class

Why: a `models.Model` class under the `_name` of an `AbstractModel` such as `mail.thread` fails with
"transforms the abstract model ... into a non-abstract model" (15.0 `odoo/models.py:682-685`; 19.0
`odoo/orm/model_classes.py:236`).

Exceptions: none.

```python
from odoo import models


class MailThread(models.Model):
    _inherit = 'mail.thread'
```

```python
from odoo import models


class MailThread(models.AbstractModel):
    _inherit = 'mail.thread'
```

### Add selection values with `selection_add`

Why: `selection=` in an extension replaces the list, with the warning "overrides existing selection; use
selection_add instead" (15.0 `odoo/fields.py:2426`; 19.0 `odoo/orm/fields_selection.py:110`), and drops the
values other modules added.

Exceptions: none.

```python
from odoo import fields, models


class LibraryAuthor(models.Model):
    _inherit = 'library.author'

    genre = fields.Selection([('essay', 'Essay')])
```

```python
from odoo import fields, models


class LibraryAuthor(models.Model):
    _inherit = 'library.author'

    genre = fields.Selection(selection_add=[('essay', 'Essay')], ondelete={'essay': 'set default'})
```

### Call `super()` and keep the signature in an override

Why: an override that skips `super()`, drops its return value or changes its signature stops the overrides
of other modules of the same method.

Exceptions: replacing the behavior is the point, and no other module overrides the method.

```python
from odoo import models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    def create(self, vals):
        return self.browse()
```

```python
from odoo import api, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    @api.model_create_multi
    def create(self, vals_list):
        return super().create(vals_list)
```

### Keep the parent's field names off a delegating model

Why: with `_inherits`, a local field with the name of a parent field hides it, so the value is no longer the
partner's.

Exceptions: hiding the parent's field is the point.

```python
from odoo import fields, models


class LibraryAuthor(models.Model):
    _inherit = 'library.author'

    email = fields.Char()
```

```python
from odoo import fields, models


class LibraryAuthor(models.Model):
    _inherit = 'library.author'

    agent_email = fields.Char()
```

### Track fields only on `mail.thread` models

Why: `tracking=True` on a model without `mail.thread` only logs "unknown parameter", and nothing is tracked.

Exceptions: none.

```python
from odoo import fields, models


class LibraryShelf(models.Model):
    _name = 'library.shelf'
    _description = 'Library Shelf'

    name = fields.Char(tracking=True)
```

```python
from odoo import fields, models


class LibraryShelf(models.Model):
    _name = 'library.shelf'
    _description = 'Library Shelf'
    _inherit = ['mail.thread']

    name = fields.Char(tracking=True)
```

### Write the chatter of the checkout's series

<!-- since=15.0 id=chatter-rule -->
Why: the 15.0 form renderer builds the chatter only from a `div` of class `oe_chatter`
(`addons/mail/static/src/widgets/form_renderer/form_renderer.js:133`), so `<chatter/>` shows no chatter.

Exceptions: none.

```xml
<form>
    <sheet/>
    <chatter/>
</form>
```

```xml
<form>
    <sheet/>
    <div class="oe_chatter">
        <field name="message_follower_ids"/>
        <field name="activity_ids"/>
        <field name="message_ids"/>
    </div>
</form>
```
<!-- end -->

<!-- since=19.0 id=chatter-rule -->
Why: the form compiler builds the chatter only from `<chatter/>`
(`addons/mail/static/src/chatter/web/form_compiler.js:46-49`), so an `oe_chatter` block shows no chatter.

Exceptions: none.

```xml
<form>
    <sheet/>
    <div class="oe_chatter">
        <field name="message_follower_ids"/>
        <field name="activity_ids"/>
        <field name="message_ids"/>
    </div>
</form>
```

```xml
<form>
    <sheet/>
    <chatter/>
</form>
```
<!-- end -->

## Verify

- `oasis --project <root> model-info res.partner --module library` (Gentle Shell: `oasis_model_info`) shows
  only what `library` adds to the model; without `--module` it lists every extending module and field
  overrides.
- `oasis --project <root> model-info library.author` shows the inherited mixins and the delegation.
- `oasis --project <root> view-info library.author` lists the views of the model and what extends them.
- `oasis --project <root> verify-module --compact library` installs on a fresh database (so a missing
  `depends` shows), updates and tests; `oasis --project <root> test-module --compact library` with a test that
  creates an author and reads `partner_id.name`.
