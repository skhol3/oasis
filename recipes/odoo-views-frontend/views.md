# Recipe: form, list and search views

Checked against: every series.

Official docs: 15.0=https://www.odoo.com/documentation/15.0/developer/reference/backend/views.html, 19.0=https://www.odoo.com/documentation/19.0/developer/reference/user_interface/view_architectures.html

Part of the [views and frontend skill](../../SKILL.md). A path in `path:line` is relative to the Odoo source
root of the series written before it (15.0 at commit 3a28e5b0, 19.0 at commit 8a2481dfc), or of this series
when none is written. The example follows `addons/website/views/website_rewrite.xml` and
`addons/point_of_sale/views/pos_payment_views.xml`, which have the same shape in both.

## When to use

A model that has no views yet, or a new form, list or search view of an existing model. For a change to a view
another module owns, use [view inheritance](view-inheritance.md); to open the views from a menu, add a
[window action and menu](actions-menus.md).

## Files

1. `library/models/library_book.py`: the model, from the `model` recipe of `odoo-backend`. Every field a view
   names must exist on it.
2. `library/models/library_author.py`: the author model with `mail.thread`, the same copy as the `inheritance`
   recipe of `odoo-backend`, shown here; only the author form needs it.
3. `library/views/library_book_views.xml`: the form, list and search views of the book, one `ir.ui.view`
   record each.
4. `library/views/library_author_views.xml`: the author form with the chatter (the same copy as the
   `inheritance` recipe of `odoo-backend`).
5. `library/__manifest__.py` `data`: the security files first, then both view files, then the file of the
   actions and menus (the `module` recipe of `odoo-backend` gives the manifest). A view needs only its model;
   the action and menu that open it come after it.

## Example

The book views name these fields of `library.book` (the `model` recipe of `odoo-backend`): `name`, `isbn`,
`author_id`, `date_published`, `pages`, `copies`, `state`, `borrower_id`, `user_id`, `company_id` and
`active`. The form and the list show `copies` with the `library_copies` widget of the [Owl recipe](owl-component.md);
building the views without that widget, drop `widget="library_copies"`: an unknown widget only logs "Missing
widget" in the browser console and falls back to the default widget of the type (15.0
`addons/web/static/src/legacy/js/views/basic/basic_view.js:87-90`, `:97-99`; 19.0
`addons/web/static/src/views/fields/field.js:140`).

`library/views/library_book_views.xml`:

```xml id=book-views since=15.0
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <record id="library_book_view_form" model="ir.ui.view">
        <field name="name">library.book.form</field>
        <field name="model">library.book</field>
        <field name="arch" type="xml">
            <form string="Book">
                <header>
                    <field name="state" widget="statusbar" options="{'clickable': '1'}"/>
                </header>
                <sheet>
                    <widget name="web_ribbon" title="Archived" bg_color="bg-danger" attrs="{'invisible': [('active', '=', True)]}"/>
                    <div class="oe_title">
                        <h1><field name="name" placeholder="e.g. The Odyssey"/></h1>
                    </div>
                    <group>
                        <group>
                            <field name="author_id"/>
                            <field name="isbn"/>
                            <field name="date_published"/>
                            <field name="pages"/>
                        </group>
                        <group>
                            <field name="copies" widget="library_copies"/>
                            <field name="borrower_id"
                                   attrs="{'invisible': [('state', '!=', 'borrowed')], 'required': [('state', '=', 'borrowed')]}"/>
                            <field name="user_id"/>
                            <field name="company_id" groups="base.group_multi_company"/>
                            <field name="active" invisible="1"/>
                        </group>
                    </group>
                </sheet>
            </form>
        </field>
    </record>

    <record id="library_book_view_list" model="ir.ui.view">
        <field name="name">library.book.list</field>
        <field name="model">library.book</field>
        <field name="arch" type="xml">
            <tree string="Books" decoration-muted="state == 'lost'">
                <field name="name"/>
                <field name="author_id"/>
                <field name="isbn" optional="show"/>
                <field name="date_published" optional="hide"/>
                <field name="copies" widget="library_copies"/>
                <field name="borrower_id" invisible="context.get('hide_borrower')"/>
                <field name="state" widget="badge"/>
            </tree>
        </field>
    </record>

    <record id="library_book_view_search" model="ir.ui.view">
        <field name="name">library.book.search</field>
        <field name="model">library.book</field>
        <field name="arch" type="xml">
            <search string="Books">
                <field name="name"/>
                <field name="isbn"/>
                <field name="author_id"/>
                <separator/>
                <filter string="Available" name="available" domain="[('state', '=', 'available')]"/>
                <filter string="Borrowed" name="borrowed" domain="[('state', '=', 'borrowed')]"/>
                <separator/>
                <filter string="Archived" name="inactive" domain="[('active', '=', False)]"/>
                <group>
                    <filter string="Author" name="group_by_author" domain="[]" context="{'group_by': 'author_id'}"/>
                    <filter string="Status" name="group_by_state" domain="[]" context="{'group_by': 'state'}"/>
                </group>
            </search>
        </field>
    </record>
</odoo>
```

```xml id=book-views since=19.0
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <record id="library_book_view_form" model="ir.ui.view">
        <field name="name">library.book.form</field>
        <field name="model">library.book</field>
        <field name="arch" type="xml">
            <form string="Book">
                <header>
                    <field name="state" widget="statusbar" options="{'clickable': '1'}"/>
                </header>
                <sheet>
                    <widget name="web_ribbon" title="Archived" bg_color="text-bg-danger" invisible="active"/>
                    <div class="oe_title">
                        <h1><field name="name" placeholder="e.g. The Odyssey"/></h1>
                    </div>
                    <group>
                        <group>
                            <field name="author_id"/>
                            <field name="isbn"/>
                            <field name="date_published"/>
                            <field name="pages"/>
                        </group>
                        <group>
                            <field name="copies" widget="library_copies"/>
                            <field name="borrower_id" invisible="state != 'borrowed'" required="state == 'borrowed'"/>
                            <field name="user_id"/>
                            <field name="company_id" groups="base.group_multi_company"/>
                            <field name="active" invisible="1"/>
                        </group>
                    </group>
                </sheet>
            </form>
        </field>
    </record>

    <record id="library_book_view_list" model="ir.ui.view">
        <field name="name">library.book.list</field>
        <field name="model">library.book</field>
        <field name="arch" type="xml">
            <list string="Books" decoration-muted="state == 'lost'">
                <field name="name"/>
                <field name="author_id"/>
                <field name="isbn" optional="show"/>
                <field name="date_published" optional="hide"/>
                <field name="copies" widget="library_copies"/>
                <field name="borrower_id" column_invisible="context.get('hide_borrower')"/>
                <field name="state" widget="badge"/>
            </list>
        </field>
    </record>

    <record id="library_book_view_search" model="ir.ui.view">
        <field name="name">library.book.search</field>
        <field name="model">library.book</field>
        <field name="arch" type="xml">
            <search string="Books">
                <field name="name"/>
                <field name="isbn"/>
                <field name="author_id"/>
                <separator/>
                <filter string="Available" name="available" domain="[('state', '=', 'available')]"/>
                <filter string="Borrowed" name="borrowed" domain="[('state', '=', 'borrowed')]"/>
                <separator/>
                <filter string="Archived" name="inactive" domain="[('active', '=', False)]"/>
                <group>
                    <filter string="Author" name="group_by_author" domain="[]" context="{'group_by': 'author_id'}"/>
                    <filter string="Status" name="group_by_state" domain="[]" context="{'group_by': 'state'}"/>
                </group>
            </search>
        </field>
    </record>
</odoo>
```

`library/models/library_author.py`, the same copy as the `inheritance` recipe of `odoo-backend` (it needs `mail`
in `depends`, as the manifest has):

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

`library/views/library_author_views.xml`: `name`, `email` and `phone` are the partner's the author delegates
to, `genre` the author's own:

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

<!-- since=15.0 id=list-tag -->
- The list view is `<tree>` and its type is `tree` (`odoo/addons/base/models/ir_ui_view.py:243`,
  `odoo/addons/base/rng/tree_view.rng:24`); `list` is not a view type. The `string` of `<tree>` is accepted but
  has no effect (`odoo/addons/base/rng/tree_view.rng:34`).
<!-- end -->

<!-- since=19.0 id=list-tag -->
- The list view is `<list>` and its type is `list` (`odoo/addons/base/models/ir_ui_view.py:149`,
  `odoo/addons/base/rng/list_view.rng:24`); `tree` is not a view type any more.
<!-- end -->

<!-- since=15.0 id=modifiers -->
- A condition on the record's values goes in `attrs`, a dictionary from `invisible`, `readonly` or `required`
  to a domain (`odoo/addons/base/models/ir_ui_view.py:86-88`); `states="borrowed,lost"` is a shorthand for
  `invisible` outside those states (`:90-95`). A plain `invisible`, `readonly` or `required` is evaluated once
  on the server with only `context` (`:97-100`), so it holds a constant (`invisible="1"`) or a context
  expression, never a field name.
<!-- end -->

<!-- since=19.0 id=modifiers -->
- `invisible`, `readonly`, `required` and `column_invisible` hold a Python expression on the record's values,
  such as `invisible="state != 'borrowed'"` (`odoo/addons/base/models/ir_ui_view.py:34`). A view that still
  holds `attrs` or `states` is refused with "Since 17.0, the "attrs" and "states" attributes are no longer
  used." (`:495-497`).
<!-- end -->

<!-- since=15.0 id=column-hide -->
- In a `<tree>`, `invisible` on a field hides the whole column and takes the context only
  (`odoo/addons/base/models/ir_ui_view.py:101-106`, as `addons/account/views/account_analytic_view.xml:34`
  writes it); `column_invisible` is not an attribute of a field here, so the schema refuses it
  (`odoo/addons/base/rng/common.rng:206`).
<!-- end -->

<!-- since=19.0 id=column-hide -->
- In a `<list>`, `column_invisible` drops the column (`addons/web/static/src/views/list/list_renderer.js:331`,
  as `addons/point_of_sale/views/pos_payment_views.xml:35` writes it); `invisible` only empties the cell of
  each record it is true for (`addons/web/static/src/views/list/list_renderer.xml:288`).
<!-- end -->

<!-- since=15.0 id=fields-in-view -->
- Every field an `attrs` domain names must be in the view, else "Field ... used in ... must be present in
  view but is missing." (`odoo/addons/base/models/ir_ui_view.py:2283`): `state` is in the header, `active` is
  in the form as an invisible field.
<!-- end -->

<!-- since=19.0 id=fields-in-view -->
- A field an expression names is added to the view by itself when it is missing
  (`odoo/addons/base/models/ir_ui_view.py:1547-1548`).
<!-- end -->

- A model with an `active` field hides its archived records from every search, so from the list, the kanban and
  the many2one inputs, unless the domain names `active` or the context sets `active_test=False` (15.0
  `odoo/models.py:4484-4489`; 19.0 `odoo/orm/models.py:5375-5383`): a list that hides inactive records needs no
  domain, and the `Archived` filter shows them because its domain names `active`.

<!-- since=15.0 id=ribbon -->
- The ribbon of an archived record is the `web_ribbon` widget, first inside `<sheet>`, hidden through `attrs`
  while `active` is true (`addons/lunch/views/lunch_supplier_views.xml:21`,
  `addons/web/static/src/legacy/js/widgets/ribbon.js:45`); `active` must be in the form, here as an invisible
  field.
<!-- end -->

<!-- since=19.0 id=ribbon -->
- The ribbon of an archived record is the `web_ribbon` widget, first inside `<sheet>`, with
  `invisible="active"` and the Bootstrap class `text-bg-danger` (`addons/lunch/views/lunch_supplier_views.xml:21`,
  `addons/web/static/src/views/widgets/ribbon/ribbon.js:71`).
<!-- end -->

- `<separator/>` splits the filters into blocks: the active filters of one block are OR-ed, the blocks AND-ed
  (15.0 `addons/web/static/src/legacy/js/control_panel/control_panel_model_extension.js:1075`, `:1140`; 19.0
  `addons/web/static/src/search/search_model.js:1620-1630`). A `group_by` filter has `domain="[]"` and the
  field in its `context`. A window action turns a filter on with
  `{'search_default_<filter name>': 1}` in its `context`, as `addons/point_of_sale/views/pos_payment_views.xml`
  does (15.0 line 62, 19.0 line 67).
- The search root takes `string` in both series (`odoo/addons/base/rng/search_view.rng:24`), although the
  19.0 view architectures page says it "takes no attributes": the source wins.

<!-- since=15.0 id=chatter-form -->
- The chatter of a `mail.thread` form is a `<div class="oe_chatter">` after `</sheet>` holding the fields
  `message_follower_ids`, `activity_ids` and `message_ids`; the form renderer builds it only from that `div`
  (`addons/mail/static/src/widgets/form_renderer/form_renderer.js:133`).
<!-- end -->

<!-- since=19.0 id=chatter-form -->
- The chatter of a `mail.thread` form is `<chatter/>` after `</sheet>`; the form compiler builds it only from
  that tag (`addons/mail/static/src/chatter/web/form_compiler.js:46-49`).
<!-- end -->

## Mistakes

### Write the list tag of the checkout's series

<!-- since=15.0 id=list-rule -->
Why: `list` is not a view type on this series, so a `<list>` view is refused when the module loads.

Exceptions: none.

```xml
<list string="Books">
    <field name="name"/>
</list>
```

```xml
<tree string="Books">
    <field name="name"/>
</tree>
```
<!-- end -->

<!-- since=19.0 id=list-rule -->
Why: `tree` is not a view type on this series, so a `<tree>` view is refused when the module loads.

Exceptions: none.

```xml
<tree string="Books">
    <field name="name"/>
</tree>
```

```xml
<list string="Books">
    <field name="name"/>
</list>
```
<!-- end -->

### Write a condition on record values the series' way

<!-- since=15.0 id=modifier-rule -->
Why: a plain `invisible` is evaluated with only `context` when the view is validated
(`odoo/addons/base/models/ir_ui_view.py:1415-1418`), so `state` is undefined and the module update stops.

Exceptions: a constant (`invisible="1"`) or a context expression (`invisible="context.get('hide')"`).

```xml
<field name="borrower_id" invisible="state != 'borrowed'"/>
```

```xml
<field name="borrower_id" attrs="{'invisible': [('state', '!=', 'borrowed')]}"/>
```
<!-- end -->

<!-- since=19.0 id=modifier-rule -->
Why: a view that holds `attrs` or `states` is refused since 17.0, so the module update stops.

Exceptions: none.

```xml
<field name="borrower_id" attrs="{'invisible': [('state', '!=', 'borrowed')]}"/>
```

```xml
<field name="borrower_id" invisible="state != 'borrowed'"/>
```
<!-- end -->

### Hide a list column the series' way

<!-- since=15.0 id=column-rule -->
Why: the schema of a field has no `column_invisible` attribute here, so the `<tree>` is refused as an invalid
view definition (`odoo/addons/base/models/ir_ui_view.py:451-456`).

Exceptions: a one2many list inside a form, which may set `column_invisible` inside `attrs` with a domain on
the parent record.

```xml
<field name="borrower_id" column_invisible="context.get('hide_borrower')"/>
```

```xml
<field name="borrower_id" invisible="context.get('hide_borrower')"/>
```
<!-- end -->

<!-- since=19.0 id=column-rule -->
Why: `invisible` in a list hides the value per record and keeps an empty column; only `column_invisible`
removes the column.

Exceptions: hiding the value of some records while keeping the column is the point.

```xml
<field name="borrower_id" invisible="context.get('hide_borrower')"/>
```

```xml
<field name="borrower_id" column_invisible="context.get('hide_borrower')"/>
```
<!-- end -->

### Name only fields the model has

Why: a field name that is not on the model, or a typo in one, stops the module update with "Field ... does
not exist in model".

Exceptions: none; check the name with `model-info <model> --field <name>` first.

```xml
<field name="author"/>
```

```xml
<field name="author_id"/>
```

### Give each filter its own name and match `search_default_` to it

Why: a `search_default_<name>` key that names no filter turns nothing on, and two filters with one `name`
make the key ambiguous.

Exceptions: none.

```xml
<search>
    <filter string="Available" name="state" domain="[('state', '=', 'available')]"/>
    <filter string="Borrowed" name="state" domain="[('state', '=', 'borrowed')]"/>
</search>
```

```xml
<search>
    <filter string="Available" name="available" domain="[('state', '=', 'available')]"/>
    <filter string="Borrowed" name="borrowed" domain="[('state', '=', 'borrowed')]"/>
</search>
```

## Verify

- `oasis --project <root> model-info library.book --field <name>` for each field the views name.
- `oasis --project <root> update-module --compact library <database>` loads the views; a view error stops the
  update with the view name and line.
- `oasis --project <root> view-info library.book` lists the new form, list and search views with their XML
  ids; `oasis --project <root> view-info library.author` the author form.
- `oasis --project <root> test-module --compact library` runs the module's tests, including a tour that opens
  the views (the `tours` recipe of `odoo-testing`).
