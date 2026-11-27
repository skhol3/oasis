# Recipe: form, list and search views

Checked against: 15.0.

Official docs: [15.0](https://www.odoo.com/documentation/15.0/developer/reference/backend/views.html)

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
2. `library/models/library_author.py`: the author model with `mail.thread`, from the `inheritance` recipe of
   `odoo-backend`; only the author form needs it.
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
`active`. The form shows `copies` with the `library_copies` widget of the [Owl recipe](owl-component.md);
building the views without that widget, drop `widget="library_copies"`: an unknown widget only logs "Missing
widget" in the browser console and falls back to the default widget of the type (15.0
`addons/web/static/src/legacy/js/views/basic/basic_view.js:87-90`, `:97-99`; 19.0
`addons/web/static/src/views/fields/field.js:140`).

`library/views/library_book_views.xml`:

```xml
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

`library/views/library_author_views.xml`: `name`, `email` and `phone` are the partner's the author delegates
to, `genre` the author's own:

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

How it behaves:

- The list view is `<tree>` and its type is `tree` (`odoo/addons/base/models/ir_ui_view.py:243`,
  `odoo/addons/base/rng/tree_view.rng:24`); `list` is not a view type. The `string` of `<tree>` is accepted but
  has no effect (`odoo/addons/base/rng/tree_view.rng:34`).

- A condition on the record's values goes in `attrs`, a dictionary from `invisible`, `readonly` or `required`
  to a domain (`odoo/addons/base/models/ir_ui_view.py:86-88`); `states="borrowed,lost"` is a shorthand for
  `invisible` outside those states (`:90-95`). A plain `invisible`, `readonly` or `required` is evaluated once
  on the server with only `context` (`:97-100`), so it holds a constant (`invisible="1"`) or a context
  expression, never a field name.

- In a `<tree>`, `invisible` on a field hides the whole column and takes the context only
  (`odoo/addons/base/models/ir_ui_view.py:101-106`, as `addons/account/views/account_analytic_view.xml:34`
  writes it); `column_invisible` is not an attribute of a field here, so the schema refuses it
  (`odoo/addons/base/rng/common.rng:206`).

- Every field an `attrs` domain names must be in the view, else "Field ... used in ... must be present in
  view but is missing." (`odoo/addons/base/models/ir_ui_view.py:2283`): `state` is in the header, `active` is
  in the form as an invisible field.

- `<separator/>` splits the filters into blocks: the active filters of one block are OR-ed, the blocks AND-ed
  (15.0 `addons/web/static/src/legacy/js/control_panel/control_panel_model_extension.js:1075`, `:1140`; 19.0
  `addons/web/static/src/search/search_model.js:1620-1630`). A `group_by` filter has `domain="[]"` and the
  field in its `context`. A window action turns a filter on with
  `{'search_default_<filter name>': 1}` in its `context`, as `addons/point_of_sale/views/pos_payment_views.xml`
  does (15.0 line 62, 19.0 line 67).
- The search root takes `string` in both series (`odoo/addons/base/rng/search_view.rng:24`), although the
  19.0 view architectures page says it "takes no attributes": the source wins.

- The chatter of a `mail.thread` form is a `<div class="oe_chatter">` after `</sheet>` holding the fields
  `message_follower_ids`, `activity_ids` and `message_ids`; the form renderer builds it only from that `div`
  (`addons/mail/static/src/widgets/form_renderer/form_renderer.js:133`).

## Mistakes

### Write the list tag of the checkout's series

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

### Write a condition on record values the series' way

Why: a plain `invisible` is evaluated with only `context` when the view is validated
(`odoo/addons/base/models/ir_ui_view.py:1415-1418`), so `state` is undefined and the module update stops.

Exceptions: a constant (`invisible="1"`) or a context expression (`invisible="context.get('hide')"`).

```xml
<field name="borrower_id" invisible="state != 'borrowed'"/>
```

```xml
<field name="borrower_id" attrs="{'invisible': [('state', '!=', 'borrowed')]}"/>
```

### Hide a list column the series' way

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

## Changed from earlier series

Oldest supported series.
