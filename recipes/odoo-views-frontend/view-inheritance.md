# Recipe: inherited views with XPath

Checked against: every series.

Official docs: 15.0=https://www.odoo.com/documentation/15.0/developer/reference/backend/views.html#inheritance, 19.0=https://www.odoo.com/documentation/19.0/developer/reference/user_interface/view_records.html#inheritance

Part of the [views and frontend skill](../../SKILL.md). A path in `path:line` is relative to the Odoo source
root of the series written before it (15.0 at commit 3a28e5b0, 19.0 at commit 8a2481dfc), or of this series
when none is written.

## When to use

Adding, moving, hiding or changing elements of an existing view (here `base.view_partner_form` and
`base.view_res_partner_filter`) from your module. For a new view of your own model, use the
[views recipe](views.md).

## Files

1. `library/__manifest__.py`: the module that owns the parent view in `depends` (`base` here, through `mail`),
   so it loads first; the manifest is the one of the `module` recipe of `odoo-backend`.
2. `library/models/res_partner.py`: the fields `library_card`, `library_member_since` and `library_note`,
   added with `_inherit = 'res.partner'` (the `inheritance` recipe of `odoo-backend` gives the file). A view
   that names a field the model lacks stops the update.
3. `library/views/res_partner_views.xml`: one `ir.ui.view` record per parent view, with `inherit_id` and no
   root element of its own in `arch`.
4. `library/__manifest__.py` `data`: security first, then `views/res_partner_views.xml`.

## Example

`library/views/res_partner_views.xml`. Before writing it, read the parent arch of the checkout's series
(`oasis --project <root> xmlid-info base.view_partner_form` gives its file and line). Every target below is in
`odoo/addons/base/views/res_partner_views.xml` of both series: the form's `vat` (15.0 line 207, 19.0 line 188),
`group name="misc"` (15.0 line 339, 19.0 line 294) and `page name='internal_notes'` (15.0 line 346, 19.0 line
304), and the search view's `email` (15.0 line 411, 19.0 line 322).

```xml id=partner-views since=15.0
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
            <!-- attrs is replaced whole: restate the parent's readonly key -->
            <xpath expr="//field[@name='vat']" position="attributes">
                <attribute name="attrs">{'readonly': [('parent_id', '!=', False)], 'required': [('is_company', '=', True), ('library_card', '!=', False)]}</attribute>
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

```xml id=partner-views since=19.0
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

How it behaves:

<!-- since=15.0 id=positions -->
- Positions (`odoo/tools/template_inheritance.py:86-260`): `inside` (the default) appends to the target,
  `after` and `before` add siblings, `replace` swaps the target for the content (an element whose text is
  `$0` receives a copy of the replaced node; `mode="inner"` replaces only its children), and `attributes`
  sets each `<attribute name="...">` to its text, an empty text removing the attribute. A child with
  `position="move"` moves an existing node of the parent instead of copying it. Patterns from core:
  `addons/delivery/views/partner_view.xml:9` (`group name="sale" position="inside"`),
  `addons/sms/views/res_partner_views.xml:14` (`replace`), `addons/barcodes_gs1_nomenclature/views/barcodes_view.xml:9-11`
  (`<attribute name="attrs">`).
<!-- end -->

<!-- since=19.0 id=positions -->
- Positions (`odoo/tools/template_inheritance.py:109-343`): `inside` (the default) appends to the target,
  `after` and `before` add siblings, `replace` swaps the target for the content (an element whose text is
  `$0` receives a copy of the replaced node; `mode="inner"` replaces only its children), and `attributes`
  sets each `<attribute name="...">` to its text, an empty text removing the attribute. A child with
  `position="move"` moves an existing node of the parent instead of copying it. Patterns from core:
  `addons/delivery/views/res_partner_views.xml:9` (`group name="sale" position="inside"`),
  `addons/phone_validation/views/res_partner_views.xml:8` (`replace`),
  `addons/account_payment/views/account_move_views.xml:13` (`add` with `separator="or"`).
<!-- end -->

- The `<field name="...">` shorthand takes the first field of that name anywhere in the parent, sub-views
  included (15.0 `odoo/tools/template_inheritance.py:65-72`; 19.0 `odoo/tools/template_inheritance.py:71-108`);
  any other element matches on all its attributes.

<!-- since=15.0 id=modifier-attribute -->
- A modifier of the parent lives in its `attrs` dictionary (the `vat` holds
  `attrs="{'readonly': [('parent_id','!=',False)]}"`, `odoo/addons/base/views/res_partner_views.xml:207`).
  `<attribute name="attrs">` replaces the whole dictionary, so restate every key the parent had, and every
  field the domains name must be in the combined view (`parent_id` and `is_company` are in the partner form).
  `add` and `remove` only split an attribute as a list on `separator` (default `,`), with no expression handling
  (`odoo/tools/template_inheritance.py:199-213`); other attributes of `<attribute>` are ignored.
<!-- end -->

<!-- since=19.0 id=modifier-attribute -->
- `add` and `remove` on `invisible`, `readonly`, `required`, `column_invisible`, `t-if`, `t-elif` and
  `decoration-*` combine Python expressions, and `separator` must be `and` or `or`
  (`odoo/tools/template_inheritance.py:20`, `:265-292`). `<attribute>` accepts only `name`, `add`, `remove`,
  `separator` and `data-oe-*`; any other attribute is an error (`:236-251`). A combined view that still holds
  `attrs` or `states` is refused (`odoo/addons/base/models/ir_ui_view.py:495-497`).
<!-- end -->

<!-- since=15.0 id=order -->
- The specs of one view apply in order, each on the result of the previous ones. When several views inherit
  the same parent, they apply by `priority` (default 16), then by id
  (`odoo/addons/base/models/ir_ui_view.py:242`, `:656`): give yours a higher `priority` to apply after another
  module's extension.
<!-- end -->

<!-- since=19.0 id=order -->
- The specs of one view apply in order, each on the result of the previous ones. When several views inherit
  the same parent, they apply by `priority` (default 16), then by id
  (`odoo/addons/base/models/ir_ui_view.py:148`, `:764`): give yours a higher `priority` to apply after another
  module's extension.
<!-- end -->

## Mistakes

### Target a repeated field with a full XPath

<!-- since=15.0 id=shorthand-rule -->
Why: the shorthand takes the first match anywhere, sub-views included; in `base.view_partner_form` the first
`comment` is in the contact form of `child_ids` (`odoo/addons/base/views/res_partner_views.xml:261`), not on
the Internal Notes page.

Exceptions: a field that appears once in the parent arch.

```xml
<field name="comment" position="attributes">
    <attribute name="placeholder">Reading notes...</attribute>
</field>
```

```xml
<xpath expr="//page[@name='internal_notes']/field[@name='comment']" position="attributes">
    <attribute name="placeholder">Reading notes...</attribute>
</xpath>
```
<!-- end -->

<!-- since=19.0 id=shorthand-rule -->
Why: the shorthand takes the first match anywhere, sub-views included; in `base.view_partner_form` the first
`comment` is in the contact form of `child_ids` (`odoo/addons/base/views/res_partner_views.xml:280`), not on
the Notes page.

Exceptions: a field that appears once in the parent arch.

```xml
<field name="comment" position="attributes">
    <attribute name="placeholder">Reading notes...</attribute>
</field>
```

```xml
<xpath expr="//page[@name='internal_notes']/field[@name='comment']" position="attributes">
    <attribute name="placeholder">Reading notes...</attribute>
</xpath>
```
<!-- end -->

### Read the parent arch of the series before targeting it

Why: a target that is not found stops the update with "Element ... cannot be located in parent view" (15.0
`odoo/tools/template_inheritance.py:258`; 19.0 `odoo/tools/template_inheritance.py:343`), and parent archs
differ between series.

Exceptions: none.

```xml
<xpath expr="//page[@name='notes']" position="before">
    <page string="Library" name="library"/>
</xpath>
```

```xml
<xpath expr="//page[@name='internal_notes']" position="before">
    <page string="Library" name="library"/>
</xpath>
```

### Change attributes instead of replacing a node

Why: `replace` removes the node other inheriting views may target and drops every attribute it had, so another
module's extension fails or the field loses its widget.

Exceptions: the node must change in a way attributes cannot express; write it again in full with the same
`name`, as the search view of the example does.

```xml
<field name="email" position="replace">
    <field name="email" string="Contact email"/>
</field>
```

```xml
<field name="email" position="attributes">
    <attribute name="string">Contact email</attribute>
</field>
```

### Keep the parent's condition when adding one

<!-- since=15.0 id=keep-condition-rule -->
Why: `<attribute name="attrs">` replaces the whole dictionary, so writing only the new key drops the parent's
`readonly` on `vat`.

Exceptions: dropping the parent's condition is the point.

```xml
<xpath expr="//field[@name='vat']" position="attributes">
    <attribute name="attrs">{'required': [('library_card', '!=', False)]}</attribute>
</xpath>
```

```xml
<xpath expr="//field[@name='vat']" position="attributes">
    <attribute name="attrs">{'readonly': [('parent_id', '!=', False)], 'required': [('library_card', '!=', False)]}</attribute>
</xpath>
```
<!-- end -->

<!-- since=19.0 id=keep-condition-rule -->
Why: a text value replaces the parent's expression, so another module's condition on the same attribute is
lost.

Exceptions: dropping the parent's condition is the point.

```xml
<xpath expr="//field[@name='email']" position="attributes">
    <attribute name="required">library_card</attribute>
</xpath>
```

```xml
<xpath expr="//field[@name='email']" position="attributes">
    <attribute name="required" add="library_card" separator="or"/>
</xpath>
```
<!-- end -->

### Depend on the module that owns the parent view

Why: without it in `depends`, the `inherit_id` ref may not exist yet when your file loads, and the install
stops with "External ID not found".

Exceptions: views of `base`, which every module gets.

```python
{'name': 'Library', 'depends': ['base'], 'data': ['views/sale_order_views.xml']}
```

```python
{'name': 'Library', 'depends': ['sale'], 'data': ['views/sale_order_views.xml']}
```

## Verify

- `oasis --project <root> view-info res.partner --type form` lists `base.view_partner_form` and the views that
  extend it; `oasis --project <root> xmlid-info base.view_partner_form` gives its file and line to read the
  parent arch.
- `oasis --project <root> model-info res.partner --field library_card` confirms the field the view adds.
- `oasis --project <root> update-module --compact library <database>` applies the inheritance; a missing target
  or an invalid attribute stops the update.
- `oasis --project <root> test-module --compact library` runs the module's tests.
