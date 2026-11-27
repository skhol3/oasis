# Recipe: a web tour run by an HttpCase

Checked against: every series.

Official docs: 15.0=https://www.odoo.com/documentation/15.0/developer/reference/backend/testing.html#integration-testing, 19.0=https://www.odoo.com/documentation/19.0/developer/reference/backend/testing.html#integration-testing

Part of the [testing skill](../../SKILL.md). A path in `path:line` is relative to the Odoo source root of the
series written before it (15.0 at commit 3a28e5b0, 19.0 at commit 8a2481dfc), or of this series when none is
written.

## When to use

A test of a flow through the web client: open an action, fill a form, save, and check the result. Use a
[model test](model-tests.md) for logic that needs no browser; it is faster and more precise.

The example creates a `library.book` of the `library` module the recipes build through the web client. It
needs, from `odoo-backend` (`references/<series>/` of that skill), `module.md` (the manifest and the access CSV)
and `model.md` (`library.book` with `name` and `pages`), and shows the same copies of the files it uses from the
other skills:

- the groups of the `access` recipe of `odoo-security`: `admin` is in `library.group_library_manager`, whose
  access rows allow every operation on books (without them, give the `base.group_user` row of the CSV create
  and write);
- the book views of the `views` recipe of `odoo-views-frontend`, a list with its create button and a form with
  the fields `name` and `pages` (the tour uses no other element of them; building without the Owl widget, drop
  `widget="library_copies"`);
- the window action `library.library_book_action` of its `actions-menus` recipe, which opens the list first,
  and its menus.

It follows `crm`'s `crm_rainbowman` tour (`addons/crm/static/tests/tours/crm_rainbowman.js`, run by
`addons/crm/tests/test_crm_ui.py`).

## Files

1. `library/static/tests/tours/library_book_tour.js`: the tour.
2. `library/__manifest__.py`: the tour file in the `web.assets_tests` bundle under `assets` (15.0
   `addons/crm/__manifest__.py:91`; 19.0 `addons/crm/__manifest__.py:83`). `data` keeps its usual order; the
   tour needs no `data` entry.
3. `library/tests/__init__.py`: imports the test file.
4. `library/tests/test_ui.py`: the `HttpCase` that starts the tour.
5. `library/security/library_groups.xml`, `library/views/library_book_views.xml` and
   `library/views/library_menus.xml`: the groups, the book views and the action with its menus, the same copies
   as their recipes, after the access CSV in `data`.
6. The Python package `websocket-client` in the Odoo environment: without it every `HttpCase` browser test is
   skipped with "websocket-client module is not installed" (15.0 `odoo/tests/common.py:931-933`; 19.0
   `odoo/tests/common.py:1272-1274`), the run still reports 0 failed and `test-module` exits 0. Neither
   series' `requirements.txt` lists it; check the log for `skipped TestLibraryUi`.

## Example

`library/static/tests/tours/library_book_tour.js`:

```javascript id=tour-js since=15.0
/** @odoo-module **/

import tour from 'web_tour.tour';

tour.register('library_book_tour', {
    test: true,
}, [
    {
        content: "create a book from the list",
        trigger: ".o_list_button_add",
        run: "click",
    },
    {
        content: "type its title",
        trigger: ".o_field_widget[name=name] input, input[name=name]",
        run: "text Dune",
    },
    {
        content: "type its pages",
        trigger: ".o_field_widget[name=pages] input, input[name=pages]",
        run: "text 412",
    },
    {
        content: "save it",
        trigger: ".o_form_button_save",
        run: "click",
    },
    {
        content: "the record is saved",
        trigger: ".o_form_readonly",
    },
]);
```

```javascript id=tour-js since=19.0
import { registry } from "@web/core/registry";

registry.category("web_tour.tours").add("library_book_tour", {
    steps: () => [
        {
            content: "create a book from the list",
            trigger: ".o_list_button_add",
            run: "click",
        },
        {
            content: "type its title",
            trigger: ".o_field_widget[name=name] :is(input, textarea)",
            run: "edit Dune",
        },
        {
            content: "type its pages",
            trigger: ".o_field_widget[name=pages] :is(input, textarea)",
            run: "edit 412",
        },
        {
            content: "save it",
            trigger: ".o_form_button_save",
            run: "click",
        },
        {
            content: "the record is saved",
            trigger: ".o_form_saved",
        },
    ],
});
```

`library/__manifest__.py`, the manifest of `module.md` (building only this piece, keep the `data` entries of
the pieces you build and the `web.assets_tests` bundle):

```python id=manifest-version-bundles since=15.0
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

```python id=manifest-version-bundles since=19.0
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

`library/security/library_groups.xml`, the same copy as the `access` recipe of `odoo-security`:

```xml id=groups-xml since=15.0
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <record id="module_category_library" model="ir.module.category">
        <field name="name">Library</field>
        <field name="parent_id" ref="base.module_category_services"/>
    </record>
    <record id="group_library_user" model="res.groups">
        <field name="name">User</field>
        <field name="category_id" ref="module_category_library"/>
        <field name="implied_ids" eval="[Command.link(ref('base.group_user'))]"/>
    </record>
    <record id="group_library_manager" model="res.groups">
        <field name="name">Manager</field>
        <field name="category_id" ref="module_category_library"/>
        <field name="implied_ids" eval="[Command.link(ref('group_library_user'))]"/>
        <field name="users" eval="[Command.link(ref('base.user_root')), Command.link(ref('base.user_admin'))]"/>
    </record>
</odoo>
```

```xml id=groups-xml since=19.0
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <record id="res_groups_privilege_library" model="res.groups.privilege">
        <field name="name">Library</field>
        <field name="category_id" ref="base.module_category_services"/>
    </record>
    <record id="group_library_user" model="res.groups">
        <field name="name">User</field>
        <field name="sequence">10</field>
        <field name="privilege_id" ref="res_groups_privilege_library"/>
        <field name="implied_ids" eval="[Command.link(ref('base.group_user'))]"/>
    </record>
    <record id="group_library_manager" model="res.groups">
        <field name="name">Manager</field>
        <field name="sequence">20</field>
        <field name="privilege_id" ref="res_groups_privilege_library"/>
        <field name="implied_ids" eval="[Command.link(ref('group_library_user'))]"/>
        <field name="user_ids" eval="[Command.link(ref('base.user_root')), Command.link(ref('base.user_admin'))]"/>
    </record>
</odoo>
```

`library/views/library_book_views.xml`, the same copy as the `views` recipe of `odoo-views-frontend`:

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

`library/views/library_menus.xml`, the same copy as the `actions-menus` recipe of `odoo-views-frontend`:

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

`library/tests/__init__.py`, the file of the [model test](model-tests.md) (building only this piece, keep the
`test_ui` import):

```python
from . import test_library_book
from . import test_library_rules
from . import test_ui
```

`library/tests/test_ui.py`:

```python id=test-ui since=15.0
from odoo.tests import HttpCase, tagged


@tagged('post_install', '-at_install')
class TestLibraryUi(HttpCase):

    def test_create_book_tour(self):
        self.start_tour('/web#action=library.library_book_action', 'library_book_tour', login='admin')
        book = self.env['library.book'].search([('name', '=', 'Dune')])
        self.assertEqual(book.pages, 412)
```

```python id=test-ui since=19.0
from odoo.tests import HttpCase, tagged


@tagged('post_install', '-at_install')
class TestLibraryUi(HttpCase):

    def test_create_book_tour(self):
        self.start_tour('/odoo/action-library.library_book_action', 'library_book_tour', login='admin')
        book = self.env['library.book'].search([('name', '=', 'Dune')])
        self.assertEqual(book.pages, 412)
```

- `start_tour(url, name, login=...)` opens the URL in a headless Chrome as that user, waits for the tour to be
  ready and runs it (15.0 `odoo/tests/common.py:1767`; 19.0 `odoo/tests/common.py:2590`). The browser's
  requests use the test's transaction, so the Python test sees what the tour created.
- A step waits for its `trigger`, then performs its `run`. End the tour with a step that only checks the saved
  form, so it ends after the save, not before, and assert the record in Python.
- `web_tour` depends on `web` and installs itself with it (15.0 `addons/web_tour/__manifest__.py:44`; 19.0
  `addons/web_tour/__manifest__.py:70`), and `mail` depends on it (15.0 `addons/mail/__manifest__.py:11`; 19.0
  `addons/mail/__manifest__.py:63`), so the manifest does not list it.

<!-- since=15.0 id=tour-registration -->
- The tour is registered with `tour.register(name, options, steps)` from `web_tour.tour`
  (`addons/web_tour/static/src/js/tour_manager.js:74`), with `test: true` so it is never offered to users, as
  `addons/crm/static/tests/tours/crm_rainbowman.js:3-7` does; `steps` is an array, the last argument.
<!-- end -->

<!-- since=19.0 id=tour-registration -->
- The tour is added to the `web_tour.tours` registry, the category the tour service reads
  (`addons/web_tour/static/src/js/tour_service.js:58`, `:67`); `steps` is a function that returns the steps
  (`:53`, called at `:95`), and the schema has no `test` key (`:51-56`).
<!-- end -->

<!-- since=15.0 id=module-header -->
- `/** @odoo-module **/` on the first line lets the file use `import`; without it the file is not transpiled
  (`odoo/tools/js_transpiler.py:585-594`).
<!-- end -->

<!-- since=19.0 id=module-header -->
- Every file under `static/src` and `static/tests` is a module, so the file needs no `/** @odoo-module **/`
  header (`odoo/tools/js_transpiler.py:725-727`).
<!-- end -->

<!-- since=15.0 id=tour-url -->
- `start_tour` opens the action; the tour has no `url`, because a `url` option makes the run load that URL
  instead (`addons/web_tour/static/src/js/tour_manager.js:208-215`): with `url: '/web'` the tour starts on the
  home menu and fails waiting for `.o_list_button_add`.
<!-- end -->

<!-- since=19.0 id=tour-url -->
- `start_tour` opens the action; the tour has no `url`, because a `url` that differs from the start URL makes
  the run redirect to it (`addons/web_tour/static/src/js/tour_service.js:157-158`).
<!-- end -->

<!-- since=15.0 id=web-url -->
- The web client URL of an action is `/web#action=<xml id>` (`addons/web/controllers/main.py:816`); the hash
  takes the XML id as well as the number, as `addons/test_website_modules/tests/test_configurator.py:17` starts
  its tour (`addons/web/static/src/webclient/actions/action_service.js:256-267`).
<!-- end -->

<!-- since=19.0 id=web-url -->
- The web client URL of an action is `/odoo/action-<xml id>` (`addons/web/static/src/core/browser/router.js:206-209`).
<!-- end -->

<!-- since=15.0 id=step-without-run -->
- A step without `run` performs a default action, a click or typing in an input, except on the last step
  (`addons/web_tour/static/src/js/tour_manager.js:516-525`): write `run` on every action step and only the
  last step without it.
<!-- end -->

<!-- since=19.0 id=step-without-run -->
- A step without `run` only waits for its trigger (`addons/web_tour/static/src/js/tour_automatic/tour_step_automatic.js:191-193`):
  write `run: "click"` to click.
<!-- end -->

<!-- since=15.0 id=typing -->
- Typing is `run: "text Dune"` (`addons/web_tour/static/src/js/running_tour_action_helper.js:28-29`), which
  replaces the value of the input (`:85-96`).
<!-- end -->

<!-- since=19.0 id=typing -->
- Typing is `run: "edit Dune"` (`addons/web_tour/static/src/js/tour_automatic/tour_helpers_hoot.js:130-133`).
<!-- end -->

<!-- since=15.0 id=field-selector -->
- The root element of a field widget carries the field's `name` and the class `o_field_widget`
  (`addons/web/static/src/legacy/js/fields/abstract_field.js:223-224`). For a char or number field that root is
  the `<input>` itself, `input[name=<field>]` (`addons/crm/static/tests/tours/crm_rainbowman.js:17`); other
  widgets put a `div` there with the input inside: a many2one (`div.o_field_widget[name=partner_id] div input`,
  `addons/account/static/tests/tours/tax_group_tests.js:36`), and the partner's `name` and `vat` once the
  auto-installed `partner_autocomplete` is there, whose widget turns into a `div` in edit mode and appends an
  input without a `name` (`addons/partner_autocomplete/static/src/js/partner_autocomplete_fieldchar.js:47-49`,
  `:102`; `addons/partner_autocomplete/views/res_partner_views.xml:8-15`). So write
  `.o_field_widget[name=<field>] input, input[name=<field>]`, which matches both: a trigger is a jQuery selector
  whose first visible match is used (`addons/web_tour/static/src/js/tour_manager.js:280-282`).
<!-- end -->

<!-- since=19.0 id=field-selector -->
- A field renders as `.o_field_widget[name=<field>]` (`addons/web/static/src/views/fields/field.js:375`) around
  the element its widget draws: an `<input>` for a char or number field
  (`addons/crm/static/tests/tours/crm_rainbowman.js:19`), a `<textarea>` for `widget="text"`
  (`addons/web/static/src/views/fields/text/text_field.xml:10`), as the partner's `name` is in
  `base.view_partner_form` (`odoo/addons/base/views/res_partner_views.xml:140-141`). So write
  `.o_field_widget[name=<field>] :is(input, textarea)`; `:is()` is plain CSS, which the tour's query passes to the
  browser when the trigger has no hoot pseudo-class such as `:contains`
  (`addons/web/static/lib/hoot-dom/helpers/dom.js:1037-1040`). A many2one is the same `input`
  (`addons/account/static/tests/tours/tax_group_tests.js:30`).
<!-- end -->

<!-- since=15.0 id=saved-form -->
- After a save the form goes back to read mode, `.o_form_readonly`
  (`addons/web/static/src/legacy/js/views/form/form_renderer.js:1189-1190`), the check
  `addons/crm/static/tests/tours/crm_email_and_phone_propagation.js:29` ends on.
<!-- end -->

<!-- since=19.0 id=saved-form -->
- A saved record without changes gets `.o_form_saved` (`addons/web/static/src/views/form/form_compiler.js:227`).
<!-- end -->

<!-- since=15.0 id=extra-trigger -->
- `extra_trigger` is a second selector the step also waits for (`addons/crm/static/tests/tours/crm_rainbowman.js:33`).
<!-- end -->

<!-- since=19.0 id=extra-trigger -->
- The step schema has no `extra_trigger` (`addons/web_tour/static/src/js/tour_service.js:26-49`): put both
  conditions in one `trigger`.
<!-- end -->

- An action that opens a kanban first has its create button at `.o-kanban-button-new` (15.0
  `addons/web/static/src/legacy/xml/kanban.xml:5`; 19.0 `addons/web/static/src/views/kanban/kanban_controller.xml:8`),
  where `crm_rainbowman.js` starts (line 14 in both); with `on_create="quick_create"` and quick create enabled it
  opens a quick-create card instead of the form (15.0
  `addons/web/static/src/legacy/js/views/kanban/kanban_controller.js:340`; 19.0
  `addons/web/static/src/views/kanban/kanban_controller.js:446`).

<!-- since=15.0 id=many2one-step -->
- A many2one is typed in its input, then its suggestion is clicked by a step without `run` on
  `.ui-menu-item a:contains(Dune)`, as `addons/account/static/tests/tours/tax_group_tests.js:34-41` does.
<!-- end -->

<!-- since=19.0 id=many2one-step -->
- A many2one is typed in its input with `edit`, then its suggestion is clicked with `run: "click"` on
  `.ui-menu-item a:contains(Dune)`, as `addons/account/static/tests/tours/tax_group_tests.js:28-37` does.
<!-- end -->

<!-- since=15.0 id=list-cell -->
- A list is checked on its cells: a step on `.o_data_row .o_data_cell:contains(Dune)` waits for a row that shows
  the text, `:contains` being jQuery's (`addons/sale_product_configurator/static/tests/tours/product_configurator_advanced_ui.js:102`).
  A display-only widget is checked the same way, on the text of its cell or field.
<!-- end -->

<!-- since=19.0 id=list-cell -->
- A list is checked on its cells: a step on `.o_data_row .o_data_cell:contains(Dune)` waits for a row that shows
  the text, `:contains` being hoot's (`addons/web/static/lib/hoot-dom/helpers/dom.js:1217`, as
  `addons/hr_skills/static/tests/tours/skills_tour.js:117` writes it). A display-only widget is checked the same
  way, on the text of its cell or field.
<!-- end -->

- Records the test creates in `setUpClass` or `setUp` with `cls.env` reach the browser: the server's requests
  run on the test's cursor (15.0 `odoo/tests/common.py:1599-1603`; 19.0 `odoo/tests/common.py:2241-2244`), and
  the browser call flushes it before opening the URL (15.0 `odoo/tests/common.py:1724-1728`; 19.0
  `odoo/tests/common.py:2542-2546`). They are rolled back with the test, like the records the tour creates.

<!-- since=15.0 id=js-unit-tests -->
- JavaScript unit tests are QUnit, bundled in `web.qunit_suite_tests` (`addons/web/__manifest__.py:498`); a tour
  is not one.
<!-- end -->

<!-- since=19.0 id=js-unit-tests -->
- JavaScript unit tests are Hoot, bundled in `web.assets_unit_tests` (`addons/web/__manifest__.py:471`); a tour
  is not one.
<!-- end -->

<!-- since=19.0 id=docs-form -->
The official 19.0 testing page still shows the older form, `import tour from 'web_tour.tour'; tour.register(...)`;
the 19.0 source registers with `registry.category("web_tour.tours").add(...)`, and this recipe follows the
source.
<!-- end -->

## Mistakes

### Put the tour in `static/tests/tours` and `web.assets_tests`

Why: a tour in `static/src` or in `web.assets_backend` is loaded for every user of the web client, not only for
the test browser.

Exceptions: none.

```python
{'assets': {'web.assets_backend': ['library/static/src/tours/library_book_tour.js']}}
```

```python
{'assets': {'web.assets_tests': ['library/static/tests/tours/**/*']}}
```

### Start the tour by the name it is registered with

Why: `start_tour` waits for a tour of that name to be ready, so a different name fails the test after the
timeout without running a step.

Exceptions: none.

```python
self.start_tour(self.url, 'library_tour', login='admin')
```

```python
self.start_tour(self.url, 'library_book_tour', login='admin')
```

### Tag an `HttpCase` `post_install`

<!-- since=15.0 id=post-install-why -->
Why: at install time the registry is not fully loaded, and the browser run warns "HttpCase test should be in
post_install only" (`odoo/tests/common.py:1713-1714`).
<!-- end -->

<!-- since=19.0 id=post-install-why -->
Why: at install time the registry is not fully loaded, and the browser run warns "HttpCase test should be in
post_install only" (`odoo/tests/common.py:2507-2508`).
<!-- end -->

Exceptions: none.

```python
@tagged('at_install')
class TestLibraryUi(HttpCase):
    pass
```

```python
@tagged('post_install', '-at_install')
class TestLibraryUi(HttpCase):
    pass
```

### Register the tour in the form of the checkout's series

<!-- since=15.0 id=register-rule -->
Why: the 15.0 tour manager reads only the tours of `tour.register`, so a tour added to a registry category is
never found and `start_tour` times out.

Exceptions: none.

```javascript
import { registry } from "@web/core/registry";

registry.category("web_tour.tours").add("library_book_tour", {
    steps: () => [{ trigger: ".o_list_button_add", run: "click" }],
});
```

```javascript
/** @odoo-module **/

import tour from 'web_tour.tour';

tour.register('library_book_tour', { test: true }, [
    { trigger: ".o_list_button_add", run: "click" },
]);
```
<!-- end -->

<!-- since=19.0 id=register-rule -->
Why: `web_tour.tour` and `tour.register` no longer exist, and the service calls `steps()`, so a tour written
for 15.0 either fails to load or has an array where a function is expected.

Exceptions: none.

```javascript
import tour from 'web_tour.tour';

tour.register('library_book_tour', { test: true }, [
    { trigger: ".o_list_button_add", run: "click" },
]);
```

```javascript
import { registry } from "@web/core/registry";

registry.category("web_tour.tours").add("library_book_tour", {
    steps: () => [{ trigger: ".o_list_button_add", run: "click" }],
});
```
<!-- end -->

### Write the field steps the way the series renders and types them

<!-- since=15.0 id=field-step-rule -->
Why: depending on the widget, the 15.0 input is the `.o_field_widget[name=...]` element itself or sits inside
it, and `edit` is not an action, so a step written for one of the two shapes, or for 19.0, waits for an element
that never appears.

Exceptions: buttons such as `.o_list_button_add` and `.o_form_button_save` have the same class in every series.

```javascript
const step = { trigger: ".o_field_widget[name=name] input", run: "edit Dune" };
```

```javascript
const step = { trigger: ".o_field_widget[name=name] input, input[name=name]", run: "text Dune" };
```
<!-- end -->

<!-- since=19.0 id=field-step-rule -->
Why: the 19.0 input sits inside `.o_field_widget`, which carries the `name`, the inner element depends on the
widget (`<textarea>` for `widget="text"`), and `text` is not an action, so a step written for 15.0 or for one
widget waits for an element that never appears or fails on its `run`.

Exceptions: buttons such as `.o_list_button_add` and `.o_form_button_save` have the same class in every series.

```javascript
const step = { trigger: "input[name=name]", run: "text Dune" };
```

```javascript
const step = { trigger: ".o_field_widget[name=name] :is(input, textarea)", run: "edit Dune" };
```
<!-- end -->

### End on a check of the saved form, then assert in Python

<!-- since=15.0 id=end-check-rule -->
Why: a tour that ends on the save click can finish before the server saved, so the Python assertion races the
browser; a last step on `.o_form_readonly` waits for the save.

Exceptions: none.

```javascript
const steps = [
    { trigger: ".o_form_button_save", run: "click" },
];
```

```javascript
const steps = [
    { trigger: ".o_form_button_save", run: "click" },
    { trigger: ".o_form_readonly" },
];
```
<!-- end -->

<!-- since=19.0 id=end-check-rule -->
Why: a tour that ends on the save click can finish before the server saved, so the Python assertion races the
browser; a last step on `.o_form_saved` waits for the save.

Exceptions: none.

```javascript
const steps = [
    { trigger: ".o_form_button_save", run: "click" },
];
```

```javascript
const steps = [
    { trigger: ".o_form_button_save", run: "click" },
    { trigger: ".o_form_saved" },
];
```
<!-- end -->

### Log in as a user with the groups the flow needs

Why: a user without the library groups cannot create books, so the tour stops at the first step the access
rows forbid.

Exceptions: `admin`, when the module puts it in the manager group as the `access` recipe does.

```python
self.start_tour(self.url, 'library_book_tour', login='reader')
```

```python
user = new_test_user(self.env, login='librarian', groups='library.group_library_manager')
self.start_tour(self.url, 'library_book_tour', login=user.login)
```

## Verify

`<root>` is the project's absolute path: `--project` refuses a relative one.

- `oasis --project <root> test-module --compact library`: the tour runs in the `post_install` phase of a
  disposable database. Report the `phase=tests database=<name> exit=<code>` line, the `stdout_log=` and
  `stderr_log=` paths and the failures; the number of tests is only in the Odoo log (`stderr_log`), the line
  `<N> failed, <M> error(s) of <K> tests when loading database ...` (15.0 `odoo/service/server.py:566-568`;
  19.0 `odoo/service/server.py:722-725`). The tour ran only when the log shows it succeeded; a log line
  `skipped TestLibraryUi` means it did not run (no `websocket-client`) even though the run exits 0.
- `oasis --project <root> test-module --compact --only TestLibraryUi.test_create_book_tour library`: the tour
  alone while iterating. `--reuse` keeps the test database (`test_prefix`, the checkout slug, then `library`)
  between runs; run once without it at the end. The kept database stays afterwards (`gc` drops only disposable
  `_r<hex>` ones): `oasis --project <root> drop-database <name>` moves it to the trash, and it runs only with
  `--confirm <name>`.
- `oasis --project <root> view-info library.book` and
  `oasis --project <root> xmlid-info library.library_book_action`: the fields and the action the tour depends
  on.
- `oasis --project <root> verify-module --compact library`: the separate update check after a manifest
  `assets` or `data` change.
