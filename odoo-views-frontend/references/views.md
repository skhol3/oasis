# Recipe: form, list and search views

Checked against: 15.0, 19.0.

Official docs: [19.0](https://www.odoo.com/documentation/19.0/developer/reference/user_interface/view_architectures.html), [15.0](https://www.odoo.com/documentation/15.0/developer/reference/backend/views.html)

What the [views and frontend skill](../SKILL.md) needs to give a model its form, list and search views. Paths in *Source* are relative to the Odoo source root of the series.

## When to use

A model that has no views yet, or a new form, list or search view of an existing model. For a change to a view another module owns, use [view inheritance](view-inheritance.md); to open the views from a menu, add a [window action and menu](actions-menus.md).

## Files

1. `library/models/library_book.py`: the model, from the
   [model recipe](../../odoo-backend/references/model.md). Every field a view names must exist on it.
2. `library/views/library_book_views.xml`: the form, list and search views, one `ir.ui.view` record each.
3. `library/__manifest__.py` `data`: the security files first, then `views/library_book_views.xml`, then the
   file of the actions and menus ([module recipe](../../odoo-backend/references/module.md)). A view only needs
   its model, but the action and menu that open it come after it.

## Example

The views name these fields of `library.book`
([model recipe](../../odoo-backend/references/model.md)): `name`, `isbn`, `author_id`, `date_published`,
`pages`, `copies`, `state`, `borrower_id`, `user_id`, `company_id` and `active`. The form shows `copies` with
the `library_copies` widget of the [Owl recipe](owl-component.md).

`library/views/library_book_views.xml`, modelled on `addons/website/views/website_rewrite.xml` and `addons/point_of_sale/views/pos_payment_views.xml`:

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

`<separator/>` splits the filters into blocks; a `group_by` filter has `domain="[]"` and the field in its `context`. A window action turns a filter on by default with `{'search_default_<filter name>': 1}` in its `context`, for example `{'search_default_group_by_author': 1}` (`addons/point_of_sale/views/pos_payment_views.xml:67`).

The domains of the search fields are AND-ed with each other and with the filters (19.0 view architectures page: "field domains are joined with each other and with filters using the **AND** operator"). That page also says the `search` root "takes no attributes", but the schema of both series accepts `string` (`odoo/addons/base/rng/search_view.rng:24`), as the example writes it: the source wins.

## Changed in

| Point | Since | Before | Source |
|---|---|---|---|
| List view root element and view type: `<list>`, type `list` | 19.0 | `<tree>`, type `tree`; `list` is not a view type (`odoo/addons/base/models/ir_ui_view.py:243`, `odoo/addons/base/rng/tree_view.rng:24`) | `odoo/addons/base/models/ir_ui_view.py:149`, `odoo/addons/base/rng/list_view.rng:24` |
| Conditions on record values: `invisible`, `readonly`, `required` and `column_invisible` take a Python expression, such as `invisible="state != 'borrowed'"`; a view with `attrs` or `states` is refused with "Since 17.0, the "attrs" and "states" attributes are no longer used." | 17.0 | A domain in `attrs`, such as `attrs="{'invisible': [('state', '!=', 'borrowed')]}"`, and `states="borrowed,lost"` to show an element only in those states (`odoo/addons/base/models/ir_ui_view.py:82-110`, example `addons/website/views/website_rewrite.xml:19`); a plain `invisible="1"` or `invisible="context.get('hide')"` is evaluated once against the context, never against field values | `odoo/addons/base/models/ir_ui_view.py:34`, `odoo/addons/base/models/ir_ui_view.py:495-497` |
| Hiding a list column: `column_invisible="..."` | 19.0 | `invisible` on a field of a `<tree>` hides the column (turned into `column_invisible`, context only); `attrs` with `column_invisible` for a condition (`odoo/addons/base/models/ir_ui_view.py:99-106`) | `odoo/addons/base/models/ir_ui_view.py:34`, `addons/point_of_sale/views/pos_payment_views.xml:35` |
| Fields an expression needs: added to the view automatically | 19.0 | Each field named in `attrs`, a `domain` or a `context` must be in the view, else "Field ... used in ... must be present in view but is missing." (`odoo/addons/base/models/ir_ui_view.py:2283`) | `odoo/addons/base/models/ir_ui_view.py:1547-1548` |
| Chatter of a `mail.thread` model: `<chatter/>` after `</sheet>` | 19.0 | `<div class="oe_chatter">` holding `message_follower_ids`, `activity_ids` and `message_ids` fields (`addons/fleet/views/fleet_vehicle_views.xml:140-143`) | `addons/mail/static/src/chatter/web/form_compiler.js:47`, `addons/fleet/views/fleet_vehicle_views.xml:183` |

A *Since* the source does not state is 19.0: the point changed after 15.0, by 19.0 at the latest.

## Mistakes

- Writing `<tree>` or `attrs` on 19.0, or `<list>` and Python-expression modifiers on 15.0: use the column of the checkout's series (`oasis doctor` `series=`).
- On 15.0, writing `invisible="state != 'borrowed'"`: it is evaluated once against the context, so the condition on the record is silently ignored.
- Naming a field the model does not have, or a typo in it: the view fails to load on install. Check with `model-info <model> --field <name>`.
- Giving two filters the same `name`, or a `search_default_*` key that matches no filter `name`.
- Hiding a list column with `invisible` on 19.0: `column_invisible` drops the column (`addons/web/static/src/views/list/list_renderer.js:331`), `invisible` only empties the cell of each record it is true for (`list_renderer.xml:288`).
- Creating the views but no access rule: a menu is shown only to users who can read its action's model (`odoo/addons/base/models/ir_ui_menu.py:127`); add the access rule first (the [access recipe](../../odoo-security/references/access.md)).

## Verify

- `oasis --project <root> model-info library.book --field <name>` for each field the views name.
- `oasis --project <root> update-module --compact library <database>` loads the views; a view error stops the update with the view name and line.
- `oasis --project <root> view-info library.book` lists the new form, list and search views with their XML ids.
- `oasis --project <root> test-module --compact library` runs the module's tests, including a form or tour test that opens the views.
