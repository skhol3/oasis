# Recipe: window action and menus

Checked against: 15.0, 19.0.

Official docs: [19.0](https://www.odoo.com/documentation/19.0/developer/reference/backend/actions.html), [15.0](https://www.odoo.com/documentation/15.0/developer/reference/backend/actions.html)

What the [views and frontend skill](../SKILL.md) needs to open a model's [views](views.md) from the main menu. Paths in *Source* are relative to the Odoo source root of the series.

## When to use

A model that needs an entry in the web client: an `ir.actions.act_window` that opens its views, and the menus that reach it (a root menu for a new app, a section menu, and the action menu).

## Files

1. `library/security/library_groups.xml` and `library/security/ir.model.access.csv`: the groups the menus
   name and the access rules (the [access recipe](../../odoo-security/references/access.md)).
2. `library/views/library_book_views.xml`: the form, list and search views ([views recipe](views.md)).
3. `library/views/library_menus.xml`: the window action first, then the menus.
4. `library/__manifest__.py` `data` in that order, security first. Odoo loads the files one after another in the listed order (`odoo/modules/loading.py:55-61`), so a file can only refer to XML ids that an earlier file or an earlier record of the same file created; core modules list security first the same way (`addons/fleet/__manifest__.py:31-37`).

## Example

`library/__manifest__.py` (the final manifest of the
[module recipe](../../odoo-backend/references/module.md); `views/library_menus.xml` is the last `data` file):

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

`library/security/ir.model.access.csv` (the same file as the
[access recipe](../../odoo-security/references/access.md)):

```csv
id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink
access_library_book_employee,library.book.employee,model_library_book,base.group_user,1,0,0,0
access_library_book_user,library.book.user,model_library_book,group_library_user,1,1,1,0
access_library_book_manager,library.book.manager,model_library_book,group_library_manager,1,1,1,1
access_library_loan_employee,library.loan.employee,model_library_loan,base.group_user,1,0,0,0
access_library_loan_user,library.loan.user,model_library_loan,group_library_user,1,1,1,0
access_library_loan_manager,library.loan.manager,model_library_loan,group_library_manager,1,1,1,1
access_library_author_employee,library.author.employee,model_library_author,base.group_user,1,0,0,0
access_library_author_user,library.author.user,model_library_author,group_library_user,1,1,1,0
access_library_author_manager,library.author.manager,model_library_author,group_library_manager,1,1,1,1
```

`library/views/library_menus.xml`, modelled on `addons/point_of_sale/views/pos_payment_views.xml:61-77` and `addons/fleet/views/fleet_vehicle_model_views.xml:167-168`:

```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <record id="library_book_action" model="ir.actions.act_window">
        <field name="name">Books</field>
        <field name="res_model">library.book</field>
        <field name="path">library-books</field>
        <field name="view_mode">list,form</field>
        <field name="search_view_id" ref="library_book_view_search"/>
        <field name="context">{'search_default_available': 1}</field>
        <field name="help" type="html">
            <p class="o_view_nocontent_smiling_face">Add your first book</p>
        </field>
    </record>

    <!-- root menu: no parent, the app in the main menu -->
    <menuitem id="library_menu_root" name="Library" sequence="200" groups="group_library_user"/>
    <!-- section menu: a parent and no action -->
    <menuitem id="library_menu_catalog" name="Catalog" parent="library_menu_root" sequence="10"/>
    <!-- action menu: its name defaults to the action name -->
    <menuitem id="library_book_menu" action="library_book_action" parent="library_menu_catalog" sequence="10"/>
</odoo>
```

A `<menuitem>` may also hold its sub-menus as children instead of naming a `parent` (`odoo/tools/convert.py:336-337`). `groups` takes comma-separated XML ids and `-<id>` removes a group (`odoo/tools/convert.py:318-327`).

## Changed in

| Point | Since | Before | Source |
|---|---|---|---|
| List mode of an action: `view_mode` `list,form` (also the default) | 19.0 | `tree,form` (also the default); `list` is not a view mode (`odoo/addons/base/models/ir_actions.py:238`) | `odoo/addons/base/models/ir_actions.py:318` |
| `path`: the readable URL of an action (lowercase letters, digits, `_` and `-`, starting with a letter, unique) | 19.0 | No `path` field on actions; leave it out (`odoo/addons/base/models/ir_actions.py:23-29`) | `odoo/addons/base/models/ir_actions.py:70`, `odoo/addons/base/models/ir_actions.py:82-92` |
| Groups of an action or a menu written as a field: `group_ids` | 19.0 | `groups_id` (`odoo/addons/base/models/ir_actions.py:248`, `odoo/addons/base/models/ir_ui_menu.py:35`); the `groups` attribute of `<menuitem>` is the same in both | `odoo/addons/base/models/ir_actions.py:329`, `odoo/addons/base/models/ir_ui_menu.py:29`, `odoo/tools/convert.py:326` |
| `target` of a window action: `current`, `new`, `fullscreen` or `main` | 19.0 | Also `inline` (`odoo/addons/base/models/ir_actions.py:237`) | `odoo/addons/base/models/ir_actions.py:317` |

A *Since* the source does not state is 19.0: the point changed after 15.0, by 19.0 at the latest.

## Mistakes

- A `<menuitem action="...">` before its action, or in a file listed before the action's file: the menu is loaded with `env.ref` of the action and fails when the action does not exist yet (`odoo/tools/convert.py:303-309`).
- A `groups` id from a security file listed after the menus: every XML id must exist when its record loads.
- A menu that nobody sees: a menu shows only when the user can read the model of its action, and a section or root menu only when one of its action menus shows (`odoo/addons/base/models/ir_ui_menu.py:127-134`); the model's access rule is missing or names another group.
- `web_icon` on a sub-menu: it is read only for a menu with no parent (`odoo/tools/convert.py:292-297`).
- `view_mode` with spaces or a repeated mode: write `list,form`; a repeated mode is refused (`odoo/addons/base/models/ir_actions.py:302-304`).
- A `path` with upper case, starting with `m-` or `action-`, or equal to `new`: refused (`odoo/addons/base/models/ir_actions.py:85-92`). On 15.0 leave `path` out: the field does not exist.
- A `search_default_<name>` key in `context` that is not the `name` of a filter of the search view.
- A data file missing from the manifest `data`: Odoo never loads it.

## Verify

- `oasis --project <root> module-info library --section menus` and `--section actions` list the menus and actions the module defines, and `--section data` the manifest order.
- `oasis --project <root> xmlid-info library.library_book_action` shows the action, its fields and the menus that reference it.
- `oasis --project <root> update-module --compact library <database>` loads the files in manifest order; a missing XML id stops it with the file and record.
- `oasis --project <root> test-module --compact library` runs the module's tests, including a tour that opens the menu.
