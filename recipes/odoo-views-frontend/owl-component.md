# Recipe: Owl field widget

Checked against: every series.

Official docs: 15.0=https://www.odoo.com/documentation/15.0/developer/reference/frontend/owl_components.html, 19.0=https://www.odoo.com/documentation/19.0/developer/reference/frontend/owl_components.html

Part of the [views and frontend skill](../../SKILL.md). A path in `path:line` is relative to the Odoo source
root of the series written before it (15.0 at commit 3a28e5b0, 19.0 at commit 8a2481dfc), or of this series
when none is written.

<!-- since=15.0 id=intro -->
The example follows `addons/account/static/src/js/account_resequence_field.js` and its template
`addons/account/static/src/xml/account_resequence.xml`: on this series the form, list and kanban views are the
legacy ones, and they find a widget only in the legacy registries `web.field_registry` and
`web.field_registry_owl` (`addons/web/static/src/legacy/js/views/basic/basic_view.js:82-99`). The newer
`registry.category("fields")` exists (`addons/web/static/src/fields/fields.js:10`), but these views never read
it, so the widget is an Owl 1 class extending `web.AbstractFieldOwl`, registered in `web.field_registry_owl`.
<!-- end -->

<!-- since=19.0 id=intro -->
The example follows `addons/web/static/src/views/fields/badge/badge_field.js` and
`addons/web/static/src/views/fields/boolean_toggle/boolean_toggle_field.js`: an Owl 2 component and its entry
in `registry.category("fields")`, where the form, list and kanban views look a widget up
(`addons/web/static/src/views/fields/field.js:122-142`).
<!-- end -->

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

```javascript id=component since=15.0
odoo.define('library.CopiesField', function (require) {
"use strict";

const AbstractFieldOwl = require('web.AbstractFieldOwl');
const fieldRegistryOwl = require('web.field_registry_owl');

class CopiesField extends AbstractFieldOwl {
    get copies() {
        return this.value || 0;
    }

    increment(delta) {
        // the legacy parser reads text, as an input gives it
        return this._setValue(String(Math.max(0, this.copies + delta)));
    }
}
CopiesField.template = 'library.CopiesField';
CopiesField.supportedFieldTypes = ['integer'];
CopiesField.description = 'Copies counter';

fieldRegistryOwl.add('library_copies', CopiesField);

return CopiesField;
});
```

```javascript id=component since=19.0
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

```xml id=template since=15.0
<?xml version="1.0" encoding="UTF-8"?>
<templates xml:space="preserve">
    <t t-name="library.CopiesField" owl="1">
        <div class="d-flex align-items-center">
            <button t-if="mode === 'edit'" type="button" class="btn btn-sm btn-secondary"
                    t-on-click="increment(-1)">-</button>
            <span class="mx-2" t-esc="copies"/>
            <button t-if="mode === 'edit'" type="button" class="btn btn-sm btn-secondary"
                    t-on-click="increment(1)">+</button>
        </div>
    </t>
</templates>
```

```xml id=template since=19.0
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

```python id=manifest since=15.0
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

```python id=manifest since=19.0
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

How it behaves:

<!-- since=15.0 id=owl-version -->
- Owl is version 1.4.11 (`addons/web/static/lib/owl/owl.js:5604`), the global `owl`: no `@odoo/owl` import;
  `const { Component } = owl;` and hooks from `owl.hooks` when a component needs them. The class gets its
  template and types as properties after it, `CopiesField.template = '...'`, as core does
  (`addons/account/static/src/js/account_resequence_field.js:27`).
<!-- end -->

<!-- since=19.0 id=owl-version -->
- Owl is version 2.8.4 (`addons/web/static/lib/owl/owl.js:5869`), imported from `@odoo/owl`, with
  `static template` and `static props` on the class (`addons/web/static/src/views/fields/integer/integer_field.js:9-13`).
<!-- end -->

<!-- since=15.0 id=registration -->
- Registration: the file is an `odoo.define` module that `require`s `web.AbstractFieldOwl` and
  `web.field_registry_owl`, so it runs after them, and adds the class itself under its key; the registry
  accepts only an Owl component class (`addons/web/static/src/legacy/js/fields/field_registry_owl.js:6-9`).
  The form looks the key up in `web.field_registry` first, then in `web.field_registry_owl`
  (`addons/web/static/src/legacy/js/views/basic/basic_view.js:87-88`).
<!-- end -->

<!-- since=19.0 id=registration -->
- Registration: `registry.category("fields")` holds entries `{ component, displayName, supportedTypes,
  extractProps, ... }`, checked when they are added (`addons/web/static/src/views/fields/field.js:65-76`,
  `addons/web/static/src/core/registry.js:100-101`). An `extractProps(fieldInfo, dynamicInfo)` function in the
  entry turns view `options` into more props (`field.js:450`, as `badge_field.js:58-63` does).
<!-- end -->

<!-- since=15.0 id=value-api -->
- The value: `this.value` reads `record.data[name]` (`addons/web/static/src/legacy/js/fields/abstract_field_owl.js:331-333`),
  `this._setValue(value)` parses it with the parser of the field type and notifies the view (`:527-529`,
  `:550`), and `this.mode` is `'edit'` or `'readonly'` (`:228-230`). The integer parser reads text and fails on
  a number (`addons/web/static/src/legacy/js/fields/field_utils.js:565-574`), hence `String(...)`. A form opens
  in read mode on this series, so the buttons show only after Edit.
<!-- end -->

<!-- since=19.0 id=value-api -->
- The value: the field component passes `name`, `record`, `id` and `readonly`
  (`addons/web/static/src/views/fields/standard_field_props.js:9-14`); read with
  `this.props.record.data[this.props.name]`, write with `await this.props.record.update({...})`
  (`boolean_toggle_field.js:15`). `readonly` is true when the view's modifier says so or the record is not in
  edition (`field.js:464`).
<!-- end -->

<!-- since=15.0 id=modules -->
- A file is an ES module (`import`/`export`) only when its first comment is `/** @odoo-module **/`
  (`odoo/tools/js_transpiler.py:585-594`); without it, the file is plain JavaScript, here an `odoo.define`
  module.
<!-- end -->

<!-- since=19.0 id=modules -->
- Every file under `<module>/static/src` or `static/tests` is an ES module, with no header needed;
  `/** @odoo-module ignore **/` opts out (`odoo/tools/js_transpiler.py:713-728`).
<!-- end -->

<!-- since=15.0 id=template-bundle -->
- Templates: the XML goes in `web.assets_qweb`, the JavaScript in `web.assets_backend`
  (`addons/web/__manifest__.py:41`). That bundle feeds both the legacy QWeb and Owl; only a template that
  carries `owl="1"` and sits directly under `<templates>` reaches Owl
  (`addons/web/static/src/legacy/js/core/session.js:239-246`, `addons/account/static/src/xml/account_resequence.xml:17`).
  Owl 1 prints with `t-esc` (escaped) or `t-raw`, and has no `t-out` (`addons/web/static/lib/owl/owl.js:2316`,
  `:2325`); `t-on-click="increment(-1)"` calls the method with its arguments, as
  `addons/web/static/src/legacy/xml/base.xml:324` does.
<!-- end -->

<!-- since=19.0 id=template-bundle -->
- Templates: the XML goes in `web.assets_backend` with the JavaScript (`addons/fleet/__manifest__.py:52-55`);
  any `t-name` of the bundle is an Owl template. `t-out` escapes unless the value is `markup`.
<!-- end -->

<!-- since=15.0 id=list-cell -->
- In a list the same class renders every cell in read mode (`addons/web/static/src/legacy/js/views/list/list_renderer.js:973`,
  wrapped as in a form by `addons/web/static/src/legacy/js/views/basic/basic_renderer.js:748`), so the buttons stay
  hidden. The list builds the column header from the class: it reads `label` and `noLabel` on its prototype
  (`list_renderer.js:929-932`), so the class names no getter so (a rule below).
<!-- end -->

<!-- since=19.0 id=list-cell -->
- In a list the same component renders every cell, with `readonly` true unless the row is in edition
  (`addons/web/static/src/views/fields/field.js:464`), so the buttons stay hidden.
<!-- end -->

- A display-only widget is this component without the buttons and the method they call; a view can also set
  `readonly="1"` on the field.

<!-- since=15.0 id=extension-module -->
- A widget of a module that extends `library` (say `library_member`) takes names of its own: its registry key
  (`library_member_badge`; the legacy registry replaces a key silently), its template
  (`library_member.MemberBadge`; Owl throws "Template ... already defined", `addons/web/static/lib/owl/owl.js:1657-1658`)
  and its `odoo.define` module (`library_member.MemberBadge`; "Service ... already defined",
  `addons/web/static/src/boot.js:146`). Its own manifest lists its files with its own paths,
  `'web.assets_backend': ['library_member/static/src/**/*.js']` and
  `'web.assets_qweb': ['library_member/static/src/**/*.xml']`, and its view inherits the `library` one
  (`inherit_id` `library.library_book_view_form`, the [view inheritance recipe](view-inheritance.md)).
<!-- end -->

<!-- since=19.0 id=extension-module -->
- A widget of a module that extends `library` (say `library_member`) takes names of its own: its registry key
  (`library_member_badge`; `add` throws on an existing key) and its template (`library_member.MemberBadge`; a
  second template of one name throws "Template ... already exists", `addons/web/static/src/core/templates.js:166-167`).
  Its own manifest lists its files with its own paths, `'web.assets_backend': ['library_member/static/src/**/*']`;
  it imports from `library` as `@library/copies_field/copies_field` (`odoo/tools/js_transpiler.py:68-81`), and its
  view inherits the `library` one (`inherit_id` `library.library_book_view_form`, the
  [view inheritance recipe](view-inheritance.md)).
<!-- end -->

- Besides paths and globs, a bundle list takes the directives `prepend`, `before`, `after`, `replace`, `remove`
  and `include` (15.0 `odoo/addons/base/models/ir_asset.py:24-30`; 19.0 `odoo/addons/base/models/ir_asset.py:17-23`).
- The official Owl pages of both series say every Odoo version since 14 ships the same Owl; the sources do
  not (1.4.11 on 15.0, 2.8.4 on 19.0), and this recipe follows the sources.

## Mistakes

<!-- since=15.0 id=registry-rule -->
### Register a form widget in the legacy Owl registry

Why: the legacy form, list and kanban views never read `registry.category("fields")`, so a widget added there
logs "Missing widget" and the field falls back to the integer widget.

Exceptions: none.

```javascript
/** @odoo-module **/
import { registry } from "@web/core/registry";

const { Component } = owl;

class CopiesField extends Component {}
CopiesField.template = 'library.CopiesField';

registry.category("fields").add("library_copies", CopiesField);
```

```javascript
odoo.define('library.CopiesField', function (require) {
"use strict";

const AbstractFieldOwl = require('web.AbstractFieldOwl');
const fieldRegistryOwl = require('web.field_registry_owl');

class CopiesField extends AbstractFieldOwl {}
CopiesField.template = 'library.CopiesField';

fieldRegistryOwl.add('library_copies', CopiesField);
});
```
<!-- end -->

<!-- since=19.0 id=registry-rule -->
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
<!-- end -->

### Prefix the widget key with the module name

<!-- since=15.0 id=key-rule -->
Why: the legacy registry replaces an existing key without a word (`addons/web/static/src/legacy/js/core/registry.js:58`),
so a key such as `integer` swaps the core widget for every view.

Exceptions: replacing the core widget is the point.

```javascript
fieldRegistryOwl.add('integer', CopiesField);
```

```javascript
fieldRegistryOwl.add('library_copies', CopiesField);
```
<!-- end -->

<!-- since=19.0 id=key-rule -->
Why: `add` throws "Cannot add key ... it already exists" for a key such as a core widget's
(`addons/web/static/src/core/registry.js:103-107`), unless `{ force: true }`, which replaces it for every view.

Exceptions: replacing the core widget is the point, with `{ force: true }`.

```javascript
registry.category("fields").add("integer", copiesField);
```

```javascript
registry.category("fields").add("library_copies", copiesField);
```
<!-- end -->

### Load the template where the series' Owl reads it

<!-- since=15.0 id=template-rule -->
Why: a template in `web.assets_qweb` without `owl="1"`, or nested below another element, goes to the legacy
QWeb only, and the field fails to render with "Template library.CopiesField does not exist"
(`addons/web/static/lib/owl/owl.js:1714`).

Exceptions: a template for a legacy widget, not an Owl component.

```xml
<templates>
    <t t-name="library.CopiesField">
        <span t-esc="copies"/>
    </t>
</templates>
```

```xml
<templates>
    <t t-name="library.CopiesField" owl="1">
        <span t-esc="copies"/>
    </t>
</templates>
```
<!-- end -->

<!-- since=19.0 id=template-rule -->
Why: no bundle named `web.assets_qweb` is loaded on this series, so a template listed there never reaches the
web client and the field fails to render.

Exceptions: none.

```python
{'assets': {'web.assets_qweb': ['library/static/src/**/*.xml']}}
```

```python
{'assets': {'web.assets_backend': ['library/static/src/**/*']}}
```
<!-- end -->

### Write the output directive of the series' Owl

<!-- since=15.0 id=output-rule -->
Why: Owl 1 has no `t-out`, so the value is not printed.

Exceptions: none.

```xml
<span t-out="copies"/>
```

```xml
<span t-esc="copies"/>
```
<!-- end -->

<!-- since=19.0 id=output-rule -->
Why: `t-raw` is deprecated and warns; `t-out` prints the value escaped unless it is `markup`.

Exceptions: none.

```xml
<span t-raw="value"/>
```

```xml
<span t-out="value"/>
```
<!-- end -->

<!-- since=15.0 id=label-rule -->
### Name no getter `label` or `noLabel` on a widget class

Why: the list reads `label` and `noLabel` on the widget's prototype to build the column header
(`addons/web/static/src/legacy/js/views/list/list_renderer.js:929-932`), so a getter of that name runs without a
record, throws, and the whole list fails to render; the form never reads them, so the widget seems to work.

Exceptions: none; give the getter another name.

```javascript
class CopiesField extends AbstractFieldOwl {
    get label() {
        return `${this.value || 0} copies`;
    }
}
```

```javascript
class CopiesField extends AbstractFieldOwl {
    get copiesLabel() {
        return `${this.value || 0} copies`;
    }
}
```
<!-- end -->

<!-- since=19.0 id=label-rule -->
<!-- end -->

### Translate the text, then put the value in

<!-- since=15.0 id=translate-rule -->
Why: the 15.0 `_t` takes one argument (`addons/web/static/src/legacy/js/core/translation.js:41-46`), so
`_t("%s copies", n)` shows `%s copies`, and a term built with the value is never found among the translations.

Exceptions: none.

```javascript
const { _t } = require('web.core');
const text = _t(`${count} copies`);
```

```javascript
const { _t } = require('web.core');
const text = _.str.sprintf(_t("%s copies"), count);
```
<!-- end -->

<!-- since=19.0 id=translate-rule -->
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
<!-- end -->

### Read and write the value through the series' field API

<!-- since=15.0 id=value-rule -->
Why: a legacy field component has no `props.record.update`; it changes its value with `_setValue`, which
parses text.

Exceptions: none.

```javascript
this.props.record.update({ [this.props.name]: this.copies + 1 });
```

```javascript
this._setValue(String(this.copies + 1));
```
<!-- end -->

<!-- since=19.0 id=value-rule -->
Why: `_setValue`, `value` and `mode` belong to the legacy `AbstractFieldOwl`, which no longer exists; a field
component writes through its record.

Exceptions: none.

```javascript
this._setValue(this.value + 1);
```

```javascript
this.props.record.update({ [this.props.name]: this.value + 1 });
```
<!-- end -->

## Verify

<!-- since=15.0 id=syntax-check -->
- `node --check library/static/src/copies_field/copies_field.js` catches syntax errors before Odoo runs (an
  `odoo.define` file is plain JavaScript).
<!-- end -->

<!-- since=19.0 id=syntax-check -->
- `node --check` on a copy of each JavaScript file saved as `.mjs` catches syntax errors before Odoo runs (the
  file uses `import`).
<!-- end -->

- `oasis --project <root> test-module --compact library` installs the module on a disposable database with
  its manifest and the views that name the widget, then runs its tests (a new module has no database to
  update); a tour that opens the list and the form proves the widget renders (the `tours` recipe of
  `odoo-testing`), since a missing widget or template, or a list that fails on the widget, shows only when a
  view loads it.
- `oasis --project <root> view-info library.book` confirms which views name `widget="library_copies"`.
