# Recipe: inherited views with XPath

Checked against: 15.0, 19.0.

Official docs: [19.0](https://www.odoo.com/documentation/19.0/developer/reference/user_interface/view_records.html#inheritance), [15.0](https://www.odoo.com/documentation/15.0/developer/reference/backend/views.html#inheritance)

What the [views and frontend skill](../SKILL.md) needs to change a view another module owns without copying it. Paths in *Source* are relative to the Odoo source root of the series.

## When to use

Adding, moving, hiding or changing elements of an existing view (here `base.view_partner_form` and `base.view_res_partner_filter`) from your module. For a new view of your own model, use the [views recipe](views.md).

## Files

1. `library/__manifest__.py`: the module that owns the parent view in `depends` (`base` here, through `mail`), so it loads first.
2. `library/models/res_partner.py`: the new fields `library_card`, `library_member_since` and `library_note`, added with `_inherit = 'res.partner'` (the [backend inheritance recipe](../../odoo-backend/references/inheritance.md), which gives the file).
3. `library/views/res_partner_views.xml`: one `ir.ui.view` record per parent view, with `inherit_id` and no root element of its own in `arch`.
4. `library/__manifest__.py` `data`: security first, then `views/res_partner_views.xml` ([module recipe](../../odoo-backend/references/module.md)).

## Example

`library/views/res_partner_views.xml`. Before writing it, read the parent arch of the checkout's series: every target below exists in `odoo/addons/base/views/res_partner_views.xml` (`vat` `:188`, `group name="misc"` `:294`, `page name='internal_notes'` `:304`, the search field `email` `:322`); 15.0 has the same names (`:207`, `:339`, `:346`, `:411`).

```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <record id="view_partner_form_library" model="ir.ui.view">
        <field name="name">res.partner.form.library</field>
        <field name="model">res.partner</field>
        <field name="inherit_id" ref="base.view_partner_form"/>
        <field name="arch" type="xml">
            <!-- shorthand: the first <field name="vat"> anywhere in the parent -->
            <field name="vat" position="after">
                <field name="library_card"/>
            </field>
            <!-- shorthand on any element: the first <group> whose attributes all match -->
            <group name="misc" position="inside">
                <field name="library_member_since"/>
            </group>
            <xpath expr="//page[@name='internal_notes']" position="before">
                <page string="Library" name="library">
                    <field name="library_note" placeholder="Reading preferences..."/>
                </page>
            </xpath>
            <!-- add to the parent's expression instead of overwriting it -->
            <xpath expr="//field[@name='vat']" position="attributes">
                <attribute name="required" add="is_company and library_card" separator="or"/>
            </xpath>
        </field>
    </record>

    <record id="view_res_partner_filter_library" model="ir.ui.view">
        <field name="name">res.partner.search.library</field>
        <field name="model">res.partner</field>
        <field name="inherit_id" ref="base.view_res_partner_filter"/>
        <field name="arch" type="xml">
            <!-- replace: the parent's node goes away, so write it again in full -->
            <xpath expr="//field[@name='email']" position="replace">
                <field name="email" string="Email or card"
                       filter_domain="['|', ('email', 'ilike', self), ('library_card', 'ilike', self)]"/>
            </xpath>
        </field>
    </record>
</odoo>
```

Positions (`odoo/tools/template_inheritance.py:159-333`): `inside` (the default) appends to the target, `after` and `before` add siblings, `replace` swaps the target for the content (an element whose text is `$0` receives a copy of the replaced node; `mode="inner"` replaces only its children), `attributes` sets each `<attribute name="...">` to its text, or with `add`/`remove` edits the current value, and an empty text removes the attribute. A child with `position="move"` moves an existing node of the parent instead of copying it. Patterns from core: `addons/delivery/views/res_partner_views.xml:8` (`group name="sale" position="inside"`), `addons/phone_validation/views/res_partner_views.xml:8` (`replace` in a search view), `addons/account_payment/views/account_move_views.xml:13` (`add` with `separator="or"`).

The specs of one view apply in order, each on the result of the previous ones (19.0 view records page: "Inheritance specs are applied sequentially"). When several views inherit the same parent, "the order is determined by the `priority`" (default 16), then the id (`odoo/addons/base/models/ir_ui_view.py:148`, `:764`; 15.0 `:242`, `:656`): give yours a higher `priority` to apply after another module's extension.

## Changed in

| Point | Since | Before | Source |
|---|---|---|---|
| Changing a modifier of the parent: `<attribute name="invisible">expr</attribute>` (also `readonly`, `required`, `column_invisible`); a combined view that still holds `attrs` or `states` is refused with "Since 17.0, the "attrs" and "states" attributes are no longer used." | 17.0 | `<attribute name="attrs">{'invisible': [...]}</attribute>`, which replaces the whole `attrs` dict of the target, so restate every key it had (`addons/barcodes_gs1_nomenclature/views/barcodes_view.xml:10`; the 15.0 `vat` carries `attrs="{'readonly': [('parent_id','!=',False)]}"`, `odoo/addons/base/views/res_partner_views.xml:207`) | `odoo/addons/base/models/ir_ui_view.py:495-497`, `addons/barcodes_gs1_nomenclature/views/barcodes_view.xml:9-11` |
| `add`/`remove` on `invisible`, `readonly`, `required`, `column_invisible`, `t-if`, `t-elif` and `decoration-*`: combine Python expressions; `separator` must be `and` or `or` | 19.0 | `add`/`remove` split every attribute as a list with `separator` (default `,`), with no expression handling (`odoo/tools/template_inheritance.py:195-213`) | `odoo/tools/template_inheritance.py:20`, `odoo/tools/template_inheritance.py:267-292` |
| `<attribute>` accepts only `name`, `add`, `remove`, `separator` and `data-oe-*`; any other attribute is an error | 19.0 | Other attributes of `<attribute>` are ignored (`odoo/tools/template_inheritance.py:195-216`) | `odoo/tools/template_inheritance.py:236-251` |

A *Since* the source does not state is 19.0: the point changed after 15.0, by 19.0 at the latest.

## Mistakes

- Using the `<field name="...">` shorthand for a field that appears more than once: it takes the first match anywhere in the arch, sub-views included (`odoo/tools/template_inheritance.py:94-101`). In `base.view_partner_form`, the first `comment` is inside the `child_ids` contact form (19.0 `:280`, 15.0 `:261`), not the Notes page; write `//page[@name='internal_notes']/field[@name='comment']`.
- Guessing a target from memory or from another series: read the parent arch first (`view-info`, `xmlid-info`); a target that is not found stops the update with "Element ... cannot be located in parent view" (`odoo/tools/template_inheritance.py:146`).
- `replace` to hide or tweak an element: it removes the node every later inheriting view may target, and drops all its attributes. Use `attributes` (`invisible`, `string`, `placeholder`) instead; when you must replace, keep the same `name`.
- Overwriting `invisible` or `required` with plain text when the parent already has an expression: it loses the parent's condition; use `add` with `separator="or"` or `"and"` on 19.0.
- On 15.0, setting `<attribute name="attrs">` with only the key you need: the target loses its other `attrs` keys.
- Forgetting the parent module in `depends`: the `inherit_id` ref may not exist yet when your file loads.
- Adding a field in the view but not on the model: the view fails to validate.

## Verify

- `oasis --project <root> view-info res.partner --type form` lists `base.view_partner_form` and the views that extend it; `oasis --project <root> xmlid-info base.view_partner_form` gives its file and line to read the parent arch.
- `oasis --project <root> model-info res.partner --field library_card` confirms the field the view adds.
- `oasis --project <root> update-module --compact library <database>` applies the inheritance; a missing target or an invalid attribute stops the update.
- `oasis --project <root> test-module --compact library` runs the module's tests.
