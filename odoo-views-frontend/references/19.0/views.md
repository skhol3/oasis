# Recipe: form, list and search views

Checked against: 19.0.

Official docs: [19.0](https://www.odoo.com/documentation/19.0/developer/reference/user_interface/view_architectures.html)

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
                <chatter/>
            </form>
        </field>
    </record>
</odoo>
```

How it behaves:

- The list view is `<list>` and its type is `list` (`odoo/addons/base/models/ir_ui_view.py:149`,
  `odoo/addons/base/rng/list_view.rng:24`); `tree` is not a view type any more.

- `invisible`, `readonly`, `required` and `column_invisible` hold a Python expression on the record's values,
  such as `invisible="state != 'borrowed'"` (`odoo/addons/base/models/ir_ui_view.py:34`). A view that still
  holds `attrs` or `states` is refused with "Since 17.0, the "attrs" and "states" attributes are no longer
  used." (`:495-497`).

- In a `<list>`, `column_invisible` drops the column (`addons/web/static/src/views/list/list_renderer.js:331`,
  as `addons/point_of_sale/views/pos_payment_views.xml:35` writes it); `invisible` only empties the cell of
  each record it is true for (`addons/web/static/src/views/list/list_renderer.xml:288`).

- A field an expression names is added to the view by itself when it is missing
  (`odoo/addons/base/models/ir_ui_view.py:1547-1548`).

- `<separator/>` splits the filters into blocks: the active filters of one block are OR-ed, the blocks AND-ed
  (15.0 `addons/web/static/src/legacy/js/control_panel/control_panel_model_extension.js:1075`, `:1140`; 19.0
  `addons/web/static/src/search/search_model.js:1620-1630`). A `group_by` filter has `domain="[]"` and the
  field in its `context`. A window action turns a filter on with
  `{'search_default_<filter name>': 1}` in its `context`, as `addons/point_of_sale/views/pos_payment_views.xml`
  does (15.0 line 62, 19.0 line 67).
- The search root takes `string` in both series (`odoo/addons/base/rng/search_view.rng:24`), although the
  19.0 view architectures page says it "takes no attributes": the source wins.

- The chatter of a `mail.thread` form is `<chatter/>` after `</sheet>`; the form compiler builds it only from
  that tag (`addons/mail/static/src/chatter/web/form_compiler.js:46-49`).

## Mistakes

### Write the list tag of the checkout's series

Why: `tree` is not a view type on this series, so a `<tree>` view is refused when the module loads.

Exceptions: none.

```xml
<tree string="Books">
    <field name="name"/>
</tree>
```

```xml
<list string="Books">
    <field name="name"/>
</list>
```

### Write a condition on record values the series' way

Why: a view that holds `attrs` or `states` is refused since 17.0, so the module update stops.

Exceptions: none.

```xml
<field name="borrower_id" attrs="{'invisible': [('state', '!=', 'borrowed')]}"/>
```

```xml
<field name="borrower_id" invisible="state != 'borrowed'"/>
```

### Hide a list column the series' way

Why: `invisible` in a list hides the value per record and keeps an empty column; only `column_invisible`
removes the column.

Exceptions: hiding the value of some records while keeping the column is the point.

```xml
<field name="borrower_id" invisible="context.get('hide_borrower')"/>
```

```xml
<field name="borrower_id" column_invisible="context.get('hide_borrower')"/>
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

## Changed from 15.0

- `book-views`: `<?xml version="1.0" encoding="utf-8"?>`
- `chatter`: `<?xml version="1.0" encoding="utf-8"?>`
- `list-tag`: The list view is `<list>` and its type is `list` (`odoo/addons/base/models/ir_ui_view.py:149`,
- `modifiers`: `invisible`, `readonly`, `required` and `column_invisible` hold a Python expression on the record's values,
- `column-hide`: In a `<list>`, `column_invisible` drops the column (`addons/web/static/src/views/list/list_renderer.js:331`,
- `fields-in-view`: A field an expression names is added to the view by itself when it is missing
- `chatter-form`: The chatter of a `mail.thread` form is `<chatter/>` after `</sheet>`; the form compiler builds it only from
- `list-rule`: Why: `tree` is not a view type on this series, so a `<tree>` view is refused when the module loads.
- `modifier-rule`: Why: a view that holds `attrs` or `states` is refused since 17.0, so the module update stops.
- `column-rule`: Why: `invisible` in a list hides the value per record and keeps an empty column; only `column_invisible`
