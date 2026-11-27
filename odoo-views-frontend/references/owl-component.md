# Recipe: Owl field widget

Checked against: 15.0, 19.0.

Official docs: [19.0](https://www.odoo.com/documentation/19.0/developer/reference/frontend/owl_components.html), [15.0](https://www.odoo.com/documentation/15.0/developer/reference/frontend/owl_components.html)

What the [views and frontend skill](../SKILL.md) needs to add a field widget: an Owl component registered in the `fields` registry, its template, and the asset bundle that loads them. Paths in *Source* are relative to the Odoo source root of the series.

## When to use

A field needs a display or an input no core widget gives (core widgets: `addons/web/static/src/views/fields/`). The view then names it with `widget="<key>"`. Check first that a core widget does not already do it.

## Files

1. `library/static/src/copies_field/copies_field.js`: the component and its registration.
2. `library/static/src/copies_field/copies_field.xml`: its Owl template.
3. `library/__manifest__.py` `assets`: both files in `web.assets_backend`. `assets` is a manifest key of its own, not a `data` file.
4. The view that uses it (the [views recipe](views.md)): `<field name="copies" widget="library_copies"/>` on the integer `copies` of `library.book` ([model recipe](../../odoo-backend/references/model.md)).

## Example

`library/static/src/copies_field/copies_field.js`, modelled on `addons/web/static/src/views/fields/badge/badge_field.js` and `addons/web/static/src/views/fields/boolean_toggle/boolean_toggle_field.js`:

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

`library/static/src/copies_field/copies_field.xml`, an Owl template file (root `<templates>`, as in `addons/web/static/src/views/fields/badge/badge_field.xml`):

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

`library/__manifest__.py` (the final manifest of the [module recipe](../../odoo-backend/references/module.md)), with the bundle entry as `addons/fleet/__manifest__.py:52-55` writes it:

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

Besides paths and globs, a bundle list takes the directives `before`, `after`, `replace` and `remove` (official assets page; `odoo/addons/base/models/ir_asset.py:17-25`, 15.0 `:24-30`).

The view's field component passes `name`, `record`, `id` and `readonly` (`addons/web/static/src/views/fields/standard_field_props.js:9-14`); `readonly` is true when the view's modifier says so or the record is not in edition (`addons/web/static/src/views/fields/field.js:463-464`). An `extractProps(fieldInfo, dynamicInfo)` function (`field.js:450`) in the registry entry turns view `options` into more props (`badge_field.js:58-63`).

## Changed in

| Point | Since | Before | Source |
|---|---|---|---|
| Owl: version 2, imported as `import { Component, useState } from "@odoo/owl"`; `static template` and `static props` on the class | 19.0 | Owl 1.4.11 as the global `owl`: `const { Component } = owl;`, hooks from `owl.hooks`; core sets `MyField.template = '...'` after the class (`addons/web/static/lib/owl/owl.js:5604`, `addons/account/static/src/js/account_resequence_field.js:4-5`, `:27`) | `addons/web/static/lib/owl/owl.js:5869`, `addons/web/static/src/views/fields/integer/integer_field.js:9-13` |
| Where form, list and kanban views find a widget: `registry.category("fields")`, whose entries are objects `{ component, displayName, supportedTypes, extractProps, ... }` checked on `add` | 19.0 | These views are legacy and read only `web.field_registry` (legacy widgets) and `web.field_registry_owl` (Owl classes); `registry.category("fields")` exists but they do not read it (`addons/web/static/src/legacy/js/views/basic/basic_view.js:85-99`, `addons/web/static/src/fields/fields.js:10`). Register the class itself inside an `odoo.define`: `require('web.field_registry_owl').add('library_copies', CopiesField)` with `class CopiesField extends AbstractFieldOwl` (`addons/account/static/src/js/account_resequence_field.js:1-30`) | `addons/web/static/src/views/fields/field.js:65-76`, `addons/web/static/src/views/fields/field.js:122-142` |
| Reading and writing the value: `this.props.record.data[this.props.name]`, `await this.props.record.update({...})`, `this.props.readonly`; supported types in `supportedTypes` of the entry | 19.0 | `this.value`, `this._setValue(value)` and `this.mode` (`'edit'` or `'readonly'`) of `AbstractFieldOwl`; types in the static `supportedFieldTypes` (`addons/web/static/src/legacy/js/fields/abstract_field_owl.js:228`, `:331`, `:550`, `:684`) | `addons/web/static/src/views/fields/boolean_toggle/boolean_toggle_field.js:12-16`, `addons/web/static/src/views/fields/field.js:463-464` |
| ES modules: every file under `<module>/static/src` or `static/tests` is one, no header needed (`/** @odoo-module ignore **/` opts out) | 19.0 | Only a file whose first comment is `/** @odoo-module **/` may use `import`/`export`; others are `odoo.define` modules (`odoo/tools/js_transpiler.py:585-594`) | `odoo/tools/js_transpiler.py:713-728` |
| Owl template output: `t-out` (escapes unless the value is `markup`); `t-raw` warns as deprecated | 19.0 | Owl 1 has `t-esc` and `t-raw` and no `t-out`: write `t-esc` (`addons/web/static/lib/owl/owl.js:2313`, `:2322`) | `addons/web/static/lib/owl/owl.js:5281-5290` |
| Templates in the bundle: the XML templates go in `web.assets_backend` with the JavaScript | 19.0 | XML templates in `web.assets_qweb`, JavaScript and styles in `web.assets_backend` (`addons/web/__manifest__.py:41`, `addons/account/__manifest__.py:93-125`) | `addons/fleet/__manifest__.py:52-55` |
| An Owl template is any `t-name` of the bundle | 19.0 | `web.assets_qweb` feeds the legacy QWeb and Owl: only a template with `owl="1"` (`<t t-name="library.CopiesField" owl="1">`) reaches Owl, any other fails at render with "Template library.CopiesField does not exist" (`addons/web/static/src/legacy/js/core/session.js:240-243`, `addons/account/static/src/xml/account_resequence.xml:17`) | `addons/web/static/src/views/fields/badge/badge_field.xml:4` |

A *Since* the source does not state is 19.0: the point changed after 15.0, by 19.0 at the latest.

The official Owl components page of both series says "all Odoo versions (starting in version 14) share the same Owl version"; the sources disagree (15.0 ships Owl 1.4.11, `addons/web/static/lib/owl/owl.js:5604`; 19.0 Owl 2.8.4, `addons/web/static/lib/owl/owl.js:5869`), and this recipe follows the sources.

## Mistakes

- Adding the component class itself on 19.0 (`registry.category("fields").add("library_copies", CopiesField)`): the registry validates each entry and needs an object with `component` (`addons/web/static/src/views/fields/field.js:65-66`, `addons/web/static/src/core/registry.js:100-101`).
- A key that already exists, such as a core widget name: `add` throws `Cannot add key ... it already exists` unless `{ force: true }` (`addons/web/static/src/core/registry.js:103-107`). Prefix keys with the module name.
- The JavaScript is not in the bundle (wrong path or glob, the module not updated, or `web.assets_frontend` instead of `web.assets_backend`): the view logs `Missing widget: library_copies for field of type integer` and falls back to the default widget of the type (`addons/web/static/src/views/fields/field.js:140-142`).
- The widget on a field of a type missing from `supportedTypes`: a console warning (`field.js:135-136`).
- `static template` naming a template that no bundled XML defines (the `t-name` and the module prefix must match), or on 15.0 an Owl template without `owl="1"`.
- Writing a 15.0 widget with 19.0 code, or the reverse: on 15.0 a form or list widget registered in `registry.category("fields")` is never used by the legacy views; on 19.0 `odoo.define`, `web.AbstractFieldOwl` and `web.field_registry_owl` do not exist.
- On 15.0, `t-out` in an Owl template: Owl 1 has no such directive.
- Checking only that the JavaScript parses: a missing widget or template shows only when a view loads it; open the view in a tour.

## Verify

- `node --check` on a copy of each JavaScript file saved as `.mjs` catches syntax errors before Odoo runs (the file uses `import`).
- `oasis --project <root> update-module --compact library <database>` loads the module with its manifest and the view that names the widget.
- `oasis --project <root> test-module --compact library` runs the module's tests; a tour or JavaScript test that opens the form proves the widget renders (the [tour recipe](../../odoo-testing/references/tours.md)).
- `oasis --project <root> view-info library.book --type form` confirms which form names `widget="library_copies"`.
