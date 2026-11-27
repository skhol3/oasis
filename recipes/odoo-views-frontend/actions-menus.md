# Recipe: window action and menus

Checked against: every series.

Official docs: 15.0=https://www.odoo.com/documentation/15.0/developer/reference/backend/actions.html, 19.0=https://www.odoo.com/documentation/19.0/developer/reference/backend/actions.html

Part of the [views and frontend skill](../../SKILL.md). A path in `path:line` is relative to the Odoo source
root of the series written before it (15.0 at commit 3a28e5b0, 19.0 at commit 8a2481dfc), or of this series
when none is written. The example follows `addons/fleet/views/fleet_vehicle_model_views.xml` (menus) and
`addons/point_of_sale/views/pos_payment_views.xml` (action), which have the same shape in both.

## When to use

A model that needs an entry in the web client: an `ir.actions.act_window` that opens its views, and the menus
that reach it (a root menu for a new app, a section menu, and the action menu).

## Files

1. `library/models/library_book.py`: the model the action opens, from the `model` recipe of `odoo-backend`.
2. `library/security/library_groups.xml` (the `access` recipe of `odoo-security`): the group
   `group_library_user` the root menu names. Building without it, drop `groups` from the root menu.
3. `library/security/ir.model.access.csv`: the access rows; a menu shows only to users who can read its
   action's model.
4. `library/views/library_menus.xml`: the window action first, then the menus.
5. `library/__manifest__.py` `data` in that order, security first, `views/library_menus.xml` last. Odoo loads
   the files one after another in the listed order (15.0 `odoo/modules/loading.py:64-68`; 19.0
   `odoo/modules/loading.py:55-61`), so a file can only refer to XML ids that an earlier file, or an earlier
   record of the same file, created; core modules list security first the same way
   (`addons/fleet/__manifest__.py:31-34`).

The action names no view: it opens, for each mode, the model's primary view of lowest priority (15.0
`odoo/addons/base/models/ir_ui_view.py:598`; 19.0 `odoo/addons/base/models/ir_ui_view.py:695`), which are the
ones of the [views recipe](views.md) when the module has them, and a generated default view otherwise (15.0
`odoo/models.py:1512-1543`; 19.0 `odoo/addons/base/models/ir_ui_view.py:3056`).

## Example

`library/__manifest__.py`, the manifest of the `module` recipe of `odoo-backend` (building only this piece, keep
the security entries and `views/library_menus.xml` of `data`, and drop `assets`):

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

`library/security/ir.model.access.csv`, the one of the `module` recipe of `odoo-backend` (building only the
book, keep its rows):

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

`library/views/library_menus.xml`:

```xml id=menus since=15.0
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <record id="library_book_action" model="ir.actions.act_window">
        <field name="name">Books</field>
        <field name="res_model">library.book</field>
        <field name="view_mode">tree,form</field>
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

```xml id=menus since=19.0
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <record id="library_book_action" model="ir.actions.act_window">
        <field name="name">Books</field>
        <field name="res_model">library.book</field>
        <field name="path">library-books</field>
        <field name="view_mode">list,form</field>
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

How it behaves:

<!-- since=15.0 id=view-mode -->
- `view_mode` lists the modes the action opens, comma-separated without spaces; the list mode is `tree`, also
  the default `tree,form` (`odoo/addons/base/models/ir_actions.py:238`), and a mode written twice or with a
  space is refused (`:212-219`).
<!-- end -->

<!-- since=19.0 id=view-mode -->
- `view_mode` lists the modes the action opens, comma-separated without spaces; the list mode is `list`, also
  the default `list,form` (`odoo/addons/base/models/ir_actions.py:318`), and a mode written twice or with a
  space is refused (`:300-306`).
<!-- end -->

<!-- since=15.0 id=path -->
- Actions have no `path` field on this series: the URL names the action by its id.
<!-- end -->

<!-- since=19.0 id=path -->
- `path` is the readable URL of the action, `/odoo/library-books`: lowercase letters, digits, `_` and `-`,
  starting with a letter, unique across actions, neither `new` nor starting with `m-` or `action-`
  (`odoo/addons/base/models/ir_actions.py:70`, `:82-92`), as `addons/fleet/views/fleet_vehicle_views.xml:372`
  sets it.
<!-- end -->

- `{'search_default_available': 1}` turns on the filter named `available` of the search view (the
  [views recipe](views.md)); a key that names no filter turns nothing on.
- The `groups` attribute of `<menuitem>` takes comma-separated XML ids, and `-<id>` removes a group (15.0
  `odoo/tools/convert.py:469-478`; 19.0 `odoo/tools/convert.py:318-327`). A `<menuitem>` may also hold its
  sub-menus as children instead of naming a `parent` (15.0 `odoo/tools/convert.py:487-488`; 19.0
  `odoo/tools/convert.py:336-337`).
- A menu shows only when the user can read the model of its action, and a section or root menu only when one
  of its action menus shows (15.0 `odoo/addons/base/models/ir_ui_menu.py:108-118`; 19.0
  `odoo/addons/base/models/ir_ui_menu.py:120-135`).

<!-- since=15.0 id=groups-field -->
- Written as a field of the record, the groups of an action or a menu are `groups_id`
  (`odoo/addons/base/models/ir_actions.py:248`, `odoo/addons/base/models/ir_ui_menu.py:35`).
<!-- end -->

<!-- since=19.0 id=groups-field -->
- Written as a field of the record, the groups of an action or a menu are `group_ids`
  (`odoo/addons/base/models/ir_actions.py:329`, `odoo/addons/base/models/ir_ui_menu.py:29`).
<!-- end -->

<!-- since=15.0 id=target -->
- `target` is `current` (the default), `new` (a dialog), `inline`, `fullscreen` or `main`
  (`odoo/addons/base/models/ir_actions.py:237`).
<!-- end -->

<!-- since=19.0 id=target -->
- `target` is `current` (the default), `new` (a dialog), `fullscreen` or `main`; `inline` is gone
  (`odoo/addons/base/models/ir_actions.py:317`).
<!-- end -->

## Mistakes

### Declare the action before the menu that opens it

Why: `<menuitem action="...">` reads the action with `env.ref` when it loads (15.0 `odoo/tools/convert.py:459`;
19.0 `odoo/tools/convert.py:308`), so a menu before its action, or in a file listed before the action's file,
stops the install with "External ID not found".

Exceptions: none.

```xml
<odoo>
    <menuitem id="library_book_menu" action="library_book_action" parent="library_menu_catalog"/>
    <record id="library_book_action" model="ir.actions.act_window">
        <field name="name">Books</field>
        <field name="res_model">library.book</field>
    </record>
</odoo>
```

```xml
<odoo>
    <record id="library_book_action" model="ir.actions.act_window">
        <field name="name">Books</field>
        <field name="res_model">library.book</field>
    </record>
    <menuitem id="library_book_menu" action="library_book_action" parent="library_menu_catalog"/>
</odoo>
```

### Write the list mode of the checkout's series

<!-- since=15.0 id=view-mode-rule -->
Why: `list` is not a view type here, so the action fails when the web client opens it.

Exceptions: none.

```xml
<field name="view_mode">list,form</field>
```

```xml
<field name="view_mode">tree,form</field>
```
<!-- end -->

<!-- since=19.0 id=view-mode-rule -->
Why: `tree` is not a view type here, so the action fails when the web client opens it.

Exceptions: none.

```xml
<field name="view_mode">tree,form</field>
```

```xml
<field name="view_mode">list,form</field>
```
<!-- end -->

<!-- since=15.0 id=path-rule -->
### Leave `path` out of an action

Why: `ir.actions.act_window` has no `path` field here, so the record stops the install with "Invalid field
'path' on model 'ir.actions.act_window'" (`odoo/models.py:4050-4052`).

Exceptions: none.

```xml
<record id="library_book_action" model="ir.actions.act_window">
    <field name="name">Books</field>
    <field name="res_model">library.book</field>
    <field name="path">library-books</field>
</record>
```

```xml
<record id="library_book_action" model="ir.actions.act_window">
    <field name="name">Books</field>
    <field name="res_model">library.book</field>
</record>
```
<!-- end -->

<!-- since=19.0 id=path-rule -->
### Write a `path` the action accepts

Why: a `path` with upper case, a space, a reserved prefix (`m-`, `action-`) or the word `new` is refused, and
the install stops.

Exceptions: none.

```xml
<field name="path">Library Books</field>
```

```xml
<field name="path">library-books</field>
```
<!-- end -->

### Write the groups field of the checkout's series

<!-- since=15.0 id=groups-rule -->
Why: the field is `groups_id` here, so `group_ids` on an action or a menu record stops the install with
"Invalid field 'group_ids' on model ..." (`odoo/models.py:4050-4052`).

Exceptions: the `groups` attribute of `<menuitem>`, written the same in every series.

```xml
<field name="group_ids" eval="[(4, ref('group_library_user'))]"/>
```

```xml
<field name="groups_id" eval="[(4, ref('group_library_user'))]"/>
```
<!-- end -->

<!-- since=19.0 id=groups-rule -->
Why: the field is `group_ids` here, so `groups_id` on an action or a menu record stops the install with
"Invalid field 'groups_id' in ..." (`odoo/orm/models.py:4658-4660`).

Exceptions: the `groups` attribute of `<menuitem>`, written the same in every series.

```xml
<field name="groups_id" eval="[(4, ref('group_library_user'))]"/>
```

```xml
<field name="group_ids" eval="[(4, ref('group_library_user'))]"/>
```
<!-- end -->

### Give the menu's group read access to the action's model

Why: a menu shows only to users who can read its action's model, so a menu whose group has no access row on
`library.book` is hidden, and so are its section and root menus.

Exceptions: none.

```csv
id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink
access_library_book_manager,library.book.manager,model_library_book,group_library_manager,1,1,1,1
```

```csv
id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink
access_library_book_user,library.book.user,model_library_book,group_library_user,1,1,1,0
access_library_book_manager,library.book.manager,model_library_book,group_library_manager,1,1,1,1
```

### Put `web_icon` on the root menu only

Why: `web_icon` is read only for a menu without a parent (15.0 `odoo/tools/convert.py:443-448`; 19.0
`odoo/tools/convert.py:292-297`), so on a sub-menu it is dropped without a word.

Exceptions: none.

```xml
<menuitem id="library_menu_catalog" name="Catalog" parent="library_menu_root" web_icon="library,static/description/icon.png"/>
```

```xml
<menuitem id="library_menu_root" name="Library" web_icon="library,static/description/icon.png"/>
```

## Verify

- `oasis --project <root> module-info library --section menus` and `--section actions` list the menus and
  actions the module defines, and `--section data` the manifest order.
- `oasis --project <root> xmlid-info library.library_book_action` shows the action, its fields and the menus
  that reference it.
- `oasis --project <root> update-module --compact library <database>` loads the files in manifest order; a
  missing XML id stops it with the file and record.
- `oasis --project <root> test-module --compact library` runs the module's tests, including a tour that opens
  the menu (the `tours` recipe of `odoo-testing`).
