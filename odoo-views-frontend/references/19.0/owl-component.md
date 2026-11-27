# Recipe: Owl field widget

Checked against: 19.0.

Official docs: [19.0](https://www.odoo.com/documentation/19.0/developer/reference/frontend/owl_components.html)

Part of the [views and frontend skill](../../SKILL.md). A path in `path:line` is relative to the Odoo source
root of the series written before it (15.0 at commit 3a28e5b0, 19.0 at commit 8a2481dfc), or of this series
when none is written.

The example follows `addons/web/static/src/views/fields/badge/badge_field.js` and
`addons/web/static/src/views/fields/boolean_toggle/boolean_toggle_field.js`: an Owl 2 component and its entry
in `registry.category("fields")`, where the form, list and kanban views look a widget up
(`addons/web/static/src/views/fields/field.js:122-142`).

## When to use

A field needs a display or an input no core widget gives. The view then names it with `widget="<key>"`. Check
first that a core widget does not already do it (15.0 `addons/web/static/src/legacy/js/fields/`; 19.0
`addons/web/static/src/views/fields/`).

## Files

1. `library/models/library_book.py`: the integer `copies` the widget shows, from the `model` recipe of
   `odoo-backend`.
2. `library/static/src/copies_field/copies_field.js`: the component and its registration.
3. `library/static/src/copies_field/copies_field.xml`: its Owl template.
4. `library/__manifest__.py` `assets`: both files in the bundles of the series. `assets` is a manifest key of
   its own, not a `data` file.
5. `library/views/library_book_views.xml`, the same copy as the [views recipe](views.md): the form and the list
   name the widget, `<field name="copies" widget="library_copies"/>`. Building the widget alone, put that line
   in any form or list of `library.book`.

## Example

`library/static/src/copies_field/copies_field.js`:

```javascript
import { Component } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

export class CopiesField extends Component {
    static template = "library.CopiesField";
    static props = { ...standardFieldProps };

    get value() {
        return this.props.record.data[this.props.name] || 0;
    }

    async increment(delta) {
        await this.props.record.update({ [this.props.name]: Math.max(0, this.value + delta) });
    }
}

export const copiesField = {
    component: CopiesField,
    displayName: _t("Copies counter"),
    supportedTypes: ["integer"],
};

registry.category("fields").add("library_copies", copiesField);
```

`library/static/src/copies_field/copies_field.xml`, an Owl template file (root `<templates>`):

```xml
<?xml version="1.0" encoding="UTF-8"?>
<templates xml:space="preserve">
    <t t-name="library.CopiesField">
        <div class="d-flex align-items-center gap-2">
            <button t-if="!props.readonly" type="button" class="btn btn-sm btn-secondary"
                    t-on-click="() => this.increment(-1)">-</button>
            <span t-out="value"/>
            <button t-if="!props.readonly" type="button" class="btn btn-sm btn-secondary"
                    t-on-click="() => this.increment(1)">+</button>
        </div>
    </t>
</templates>
```

`library/__manifest__.py`, the manifest of the `module` recipe of `odoo-backend` (building only this piece,
keep `assets` and drop the `data` files you do not build):

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

`library/views/library_book_views.xml`, the same copy as the [views recipe](views.md):

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

How it behaves:

- Owl is version 2.8.4 (`addons/web/static/lib/owl/owl.js:5869`), imported from `@odoo/owl`, with
  `static template` and `static props` on the class (`addons/web/static/src/views/fields/integer/integer_field.js:9-13`).

- Registration: `registry.category("fields")` holds entries `{ component, displayName, supportedTypes,
  extractProps, ... }`, checked when they are added (`addons/web/static/src/views/fields/field.js:65-76`,
  `addons/web/static/src/core/registry.js:100-101`). An `extractProps(fieldInfo, dynamicInfo)` function in the
  entry turns view `options` into more props (`field.js:450`, as `badge_field.js:58-63` does).

- The value: the field component passes `name`, `record`, `id` and `readonly`
  (`addons/web/static/src/views/fields/standard_field_props.js:9-14`); read with
  `this.props.record.data[this.props.name]`, write with `await this.props.record.update({...})`
  (`boolean_toggle_field.js:15`). `readonly` is true when the view's modifier says so or the record is not in
  edition (`field.js:464`).

- Every file under `<module>/static/src` or `static/tests` is an ES module, with no header needed;
  `/** @odoo-module ignore **/` opts out (`odoo/tools/js_transpiler.py:713-728`).

- Templates: the XML goes in `web.assets_backend` with the JavaScript (`addons/fleet/__manifest__.py:52-55`);
  any `t-name` of the bundle is an Owl template. `t-out` escapes unless the value is `markup`.

- In a list the same component renders every cell, with `readonly` true unless the row is in edition
  (`addons/web/static/src/views/fields/field.js:464`), so the buttons stay hidden.

- A display-only widget is this component without the buttons and the method they call; a view can also set
  `readonly="1"` on the field.

- A widget of a module that extends `library` (say `library_member`) takes names of its own: its registry key
  (`library_member_badge`; `add` throws on an existing key) and its template (`library_member.MemberBadge`; a
  second template of one name throws "Template ... already exists", `addons/web/static/src/core/templates.js:166-167`).
  Its own manifest lists its files with its own paths, `'web.assets_backend': ['library_member/static/src/**/*']`;
  it imports from `library` as `@library/copies_field/copies_field` (`odoo/tools/js_transpiler.py:68-81`), and its
  view inherits the `library` one (`inherit_id` `library.library_book_view_form`, the
  [view inheritance recipe](view-inheritance.md)).

- Besides paths and globs, a bundle list takes the directives `prepend`, `before`, `after`, `replace`, `remove`
  and `include` (15.0 `odoo/addons/base/models/ir_asset.py:24-30`; 19.0 `odoo/addons/base/models/ir_asset.py:17-23`).
- The official Owl pages of both series say every Odoo version since 14 ships the same Owl; the sources do
  not (1.4.11 on 15.0, 2.8.4 on 19.0), and this recipe follows the sources.

## Mistakes

### Register an entry object, not the component class

Why: the registry validates each entry and needs an object with `component`, so adding the class throws when
the bundle loads and the widget is missing.

Exceptions: none.

```javascript
registry.category("fields").add("library_copies", CopiesField);
```

```javascript
registry.category("fields").add("library_copies", {
    component: CopiesField,
    supportedTypes: ["integer"],
});
```

### Prefix the widget key with the module name

Why: `add` throws "Cannot add key ... it already exists" for a key such as a core widget's
(`addons/web/static/src/core/registry.js:103-107`), unless `{ force: true }`, which replaces it for every view.

Exceptions: replacing the core widget is the point, with `{ force: true }`.

```javascript
registry.category("fields").add("integer", copiesField);
```

```javascript
registry.category("fields").add("library_copies", copiesField);
```

### Load the template where the series' Owl reads it

Why: no bundle named `web.assets_qweb` is loaded on this series, so a template listed there never reaches the
web client and the field fails to render.

Exceptions: none.

```python
{'assets': {'web.assets_qweb': ['library/static/src/**/*.xml']}}
```

```python
{'assets': {'web.assets_backend': ['library/static/src/**/*']}}
```

### Write the output directive of the series' Owl

Why: `t-raw` is deprecated and warns; `t-out` prints the value escaped unless it is `markup`.

Exceptions: none.

```xml
<span t-raw="value"/>
```

```xml
<span t-out="value"/>
```

### Translate the text, then put the value in

Why: a term built with the value (`` _t(`${count} copies`) ``) is never found among the translations; `_t`
takes the values after the term (`addons/web/static/src/core/l10n/translation.js:95`).

Exceptions: none.

```javascript
import { _t } from "@web/core/l10n/translation";
const text = _t(`${count} copies`);
```

```javascript
import { _t } from "@web/core/l10n/translation";
const text = _t("%s copies", count);
```

### Read and write the value through the series' field API

Why: `_setValue`, `value` and `mode` belong to the legacy `AbstractFieldOwl`, which no longer exists; a field
component writes through its record.

Exceptions: none.

```javascript
this._setValue(this.value + 1);
```

```javascript
this.props.record.update({ [this.props.name]: this.value + 1 });
```

## Verify

- `node --check` on a copy of each JavaScript file saved as `.mjs` catches syntax errors before Odoo runs (the
  file uses `import`).

- `oasis --project <root> test-module --compact library` installs the module on a disposable database with
  its manifest and the views that name the widget, then runs its tests (a new module has no database to
  update); a tour that opens the list and the form proves the widget renders (the `tours` recipe of
  `odoo-testing`), since a missing widget or template, or a list that fails on the widget, shows only when a
  view loads it.
- `oasis --project <root> view-info library.book` confirms which views name `widget="library_copies"`.

## Changed from 15.0

- `intro`: The example follows `addons/web/static/src/views/fields/badge/badge_field.js` and
- `component`: `export class CopiesField extends Component {`
- `template`: `<t t-name="library.CopiesField">`
- `manifest`: `'version': '19.0.1.0.0',`
- `book-views`: `<widget name="web_ribbon" title="Archived" bg_color="text-bg-danger" invisible="active"/>`
- `owl-version`: Owl is version 2.8.4 (`addons/web/static/lib/owl/owl.js:5869`), imported from `@odoo/owl`, with
- `registration`: Registration: `registry.category("fields")` holds entries `{ component, displayName, supportedTypes,
- `value-api`: The value: the field component passes `name`, `record`, `id` and `readonly`
- `modules`: Every file under `<module>/static/src` or `static/tests` is an ES module, with no header needed;
- `template-bundle`: Templates: the XML goes in `web.assets_backend` with the JavaScript (`addons/fleet/__manifest__.py:52-55`);
- `list-cell`: In a list the same component renders every cell, with `readonly` true unless the row is in edition
- `extension-module`: A widget of a module that extends `library` (say `library_member`) takes names of its own: its registry key
- `registry-rule`: Register an entry object, not the component class
- `key-rule`: Why: `add` throws "Cannot add key ... it already exists" for a key such as a core widget's
- `template-rule`: Why: no bundle named `web.assets_qweb` is loaded on this series, so a template listed there never reaches the
- `output-rule`: Why: `t-raw` is deprecated and warns; `t-out` prints the value escaped unless it is `markup`.
- `label-rule`: removed
- `translate-rule`: Why: a term built with the value (`` _t(`${count} copies`) ``) is never found among the translations; `_t`
- `value-rule`: Why: `_setValue`, `value` and `mode` belong to the legacy `AbstractFieldOwl`, which no longer exists; a field
- `syntax-check`: `node --check` on a copy of each JavaScript file saved as `.mjs` catches syntax errors before Odoo runs (the
