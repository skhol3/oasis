# Recipe: groups and model access (ir.model.access.csv)

Checked against: 15.0.

Official docs: [15.0](https://www.odoo.com/documentation/15.0/developer/reference/backend/security.html#access-rights)

Part of the [security skill](../../SKILL.md). A path in `path:line` is relative to the Odoo source root of the
series written before it (15.0 at commit 3a28e5b0, 19.0 at commit 8a2481dfc), or of this series when none is
written. Record rules, which narrow an allowed operation to some records, are in [record-rules.md](record-rules.md).

The example adds the groups of the `library` module the recipes build. It needs, from `odoo-backend`
(`references/<series>/` of that skill), `module.md` (the manifest, `models/__init__.py` and the access CSV)
and `model.md` (`library.book`). The CSV also has the rows of `library.loan` (`compute-constraint.md`) and
`library.author` (`inheritance.md`); building only the book, keep its three rows.

## When to use

A module adds a model, or a group that grants operations on a model. Every concrete model, wizards
(`TransientModel`) included, needs at least one `ir.model.access` row, or only the superuser can use it: the
loader only warns "The models [...] have no access rules in module ..." (`odoo/modules/loading.py:259` in both
series). The usual shape is a *user* group with limited rights and a *manager* group that implies it and adds
the rest.

## Files

1. `library/security/library_groups.xml`: the groups, and the record that names their application, before
   anything that refers to them.
2. `library/security/ir.model.access.csv`: one row per model and group; it names the groups, so it comes
   after them. The file is the one of `module.md`, shown here unchanged.
3. `library/security/library_rules.xml` ([record-rules.md](record-rules.md)), then views, menus and data.
4. `library/__manifest__.py` `data`: in that order, security first, as `addons/fleet/__manifest__.py:32-33`
   does in both series.

The model XML id `model_<model with dots as underscores>` (`model_library_book`) exists as soon as the model
is loaded, before the `data` files; a model of another module takes that module's prefix
(`sale.model_sale_order`).

## Example

`library/__manifest__.py`, the manifest of `module.md` (building only this piece, keep the two first `data`
entries and drop the others and `assets`):

```python
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

`library/security/library_groups.xml`: a group's application is its `category_id`, an `ir.module.category`
(`odoo/addons/base/models/res_users.py:208`). The file adds a `Library` category under Services
(`parent_id`, `odoo/addons/base/models/ir_module.py:98`), as `addons/hr_timesheet/security/hr_timesheet_security.xml:4-13`
gives its groups a category of their own. The manager implies the user, who implies `base.group_user` (internal
user), so a manager has every right of both; `users` puts `admin` in the manager group, as
`addons/fleet/security/fleet_security.xml:12-17` does.

```xml
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

`Command` is in the evaluation context of data files in both series (15.0 `odoo/tools/convert.py:58`; 19.0
`odoo/tools/convert.py:45`), so `Command.link(...)` replaces the numeric `(4, id)` that older files write.

`library/security/ir.model.access.csv`, the file of `module.md`:

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

The header is the one the loader suggests (`odoo/modules/loading.py:260` in both series); the columns are the
`ir.model.access` fields `name`, `model_id`, `group_id`, `perm_read`, `perm_write`, `perm_create` and
`perm_unlink` (15.0 `odoo/addons/base/models/ir_model.py:1717-1724`; 19.0
`odoo/addons/base/models/ir_model.py:2101-2108`). The matrix: every internal user reads; the library user
reads, writes and creates; only the manager deletes.

The rows of a user's groups add up: an operation is allowed when an active row of one of the user's groups
grants it, and only when none does, a row without group (`odoo/addons/base/models/ir_model.py:1786-1820`).

In code, test membership with `self.env.user.has_group('library.group_library_manager')`, the full XML id
(15.0 `odoo/addons/base/models/res_users.py:895`; 19.0 `odoo/addons/base/models/res_users.py:1066`).

The names below differ between the series; `oasis --project <root> model-info res.groups` lists the ones of the
checkout.

- A group specification such as `'library.group_library_user,!library.group_library_manager'` is checked with
  `self.user_has_groups(spec)`, a method of every model (`odoo/models.py:1466`); `res.users` has no `has_groups`.

- `res.groups` has no `sequence` field (`_order = 'name'`, `odoo/addons/base/models/res_users.py:197`): a
  `sequence` in the XML fails the install with "Invalid field 'sequence' on model 'res.groups'". The user form
  orders the groups of an application by their implied groups (`odoo/addons/base/models/res_users.py:1400-1401`).

- A group's users are `users` (`odoo/addons/base/models/res_users.py:201`).

- A user's groups are `groups_id` (`odoo/addons/base/models/res_users.py:367`), implied groups included;
  `group_ids` and `all_group_ids` do not exist.

- A group name is unique per application, `unique (category_id, name)`
  (`odoo/addons/base/models/res_users.py:213-214`).

- The groups a group implies, transitively, are `trans_implied_ids`; `implied_ids` holds the direct ones
  (`odoo/addons/base/models/res_users.py:1129`, `:1131`).

- A row without group is accepted silently and applies to every user.

The official security page of neither series describes `res.groups.privilege` or the order of the groups;
those points rely on the source.

## Mistakes

### List the groups before the CSV that names them

Why: the loader reads `data` in order, so a CSV row whose `group_id` is not loaded yet stops the install with
an external ID that does not exist.

Exceptions: rows that name only groups of other modules (`base.group_user`) may come before the groups file.

```python
{
    'data': [
        'security/ir.model.access.csv',
        'security/library_groups.xml',
    ],
}
```

```python
{
    'data': [
        'security/library_groups.xml',
        'security/ir.model.access.csv',
    ],
}
```

### Write the model XML id in `model_id:id`

Why: the column takes an XML id; the model name (`library.book`) is not one, so the import fails, and a model
of another module without its prefix is looked up in this module.

Exceptions: none.

```csv
id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink
access_library_book_employee,library.book.employee,library.book,base.group_user,1,0,0,0
access_sale_order_library,sale.order.library,model_sale_order,group_library_user,1,0,0,0
```

```csv
id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink
access_library_book_employee,library.book.employee,model_library_book,base.group_user,1,0,0,0
access_sale_order_library,sale.order.library,sale.model_sale_order,group_library_user,1,0,0,0
```

### Write the group fields of the checkout's series

Why: `privilege_id`, `sequence` and `user_ids` do not exist on `res.groups` here, so a group written for 19.0
fails the install with "Invalid field".

Exceptions: `name`, `implied_ids` and `comment` are the same in every series.

```xml
<odoo>
    <record id="group_library_manager" model="res.groups">
        <field name="name">Manager</field>
        <field name="sequence">20</field>
        <field name="privilege_id" ref="res_groups_privilege_library"/>
        <field name="user_ids" eval="[Command.link(ref('base.user_admin'))]"/>
    </record>
</odoo>
```

```xml
<odoo>
    <record id="group_library_manager" model="res.groups">
        <field name="name">Manager</field>
        <field name="category_id" ref="module_category_library"/>
        <field name="users" eval="[Command.link(ref('base.user_admin'))]"/>
    </record>
</odoo>
```

### Write the user groups field of the checkout's series

Why: `group_ids` does not exist on `res.users` here; a create or write with it raises "Invalid field
'group_ids' on model 'res.users'" (`odoo/models.py:4052`).

Exceptions: `new_test_user(env, login, groups='...')` takes XML ids and fills the field of its series.

```python
user = env['res.users'].create({
    'name': 'Reader',
    'login': 'reader',
    'group_ids': [(6, 0, [env.ref('library.group_library_user').id])],
})
```

```python
user = env['res.users'].create({
    'name': 'Reader',
    'login': 'reader',
    'groups_id': [(6, 0, [env.ref('library.group_library_user').id])],
})
```

### Give every row a group

Why: a row without group applies to every user, portal and public users included, so it opens the model far
wider than intended.

Exceptions: none; even a read for everybody names `base.group_user` (internal users) or the portal group.

```csv
id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink
access_library_book_all,library.book.all,model_library_book,,1,1,1,0
```

```csv
id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink
access_library_book_employee,library.book.employee,model_library_book,base.group_user,1,0,0,0
access_library_book_user,library.book.user,model_library_book,group_library_user,1,1,1,0
```

### Make the manager group imply the user group

Why: a manager that does not imply the user lacks the user's rows and record rules, and the user form shows two
unrelated groups instead of one choice per application.

Exceptions: groups that are meant to be independent (a separate feature), not levels of one application.

```xml
<odoo>
    <record id="group_library_manager" model="res.groups">
        <field name="name">Manager</field>
        <field name="implied_ids" eval="[Command.link(ref('base.group_user'))]"/>
    </record>
</odoo>
```

```xml
<odoo>
    <record id="group_library_manager" model="res.groups">
        <field name="name">Manager</field>
        <field name="implied_ids" eval="[Command.link(ref('group_library_user'))]"/>
    </record>
</odoo>
```

### Grant each group only the operations of its matrix

Why: a row copied from the manager's gives the user group delete (or write) rights nobody decided, and no test
fails because the allowed path still works.

Exceptions: none; write the intended matrix first and grant only that.

```csv
id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink
access_library_book_user,library.book.user,model_library_book,group_library_user,1,1,1,1
access_library_book_manager,library.book.manager,model_library_book,group_library_manager,1,1,1,1
```

```csv
id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink
access_library_book_user,library.book.user,model_library_book,group_library_user,1,1,1,0
access_library_book_manager,library.book.manager,model_library_book,group_library_manager,1,1,1,1
```

### Test access as a user of each group, not as admin

Why: the test environment is the superuser, and `base.user_admin` is usually a manager, so neither proves what
the user group may or may not do.

Exceptions: none.

```python
def test_user_cannot_delete(self):
    book = self.env['library.book'].create({'name': 'Dune'})
    book.unlink()
```

```python
def test_user_cannot_delete(self):
    user = new_test_user(self.env, login='library_user', groups='library.group_library_user')
    book = self.env['library.book'].create({'name': 'Dune'})
    with self.assertRaises(AccessError):
        book.with_user(user).unlink()
```

### Check a group by its full XML id

Why: `has_group` asserts the XML id is fully qualified, so a name without the module prefix raises
"External ID ... must be fully qualified" (`odoo/addons/base/models/res_users.py:914`) for every user.

Exceptions: none.

```python
if self.env.user.has_group('group_library_manager'):
    self.state = 'lost'
```

```python
if self.env.user.has_group('library.group_library_manager'):
    self.state = 'lost'
```

## Verify

- `oasis --project <root> model-info res.groups` and
  `oasis --project <root> model-info res.users --field group_ids` (or `--field groups_id`) confirm the field
  names of the checkout's series before writing them.
- `oasis --project <root> module-info library --section security` lists the groups, the ACL rows per model and
  the rules as the module declares them; `--section data` the `data` order.
- `oasis --project <root> update-module --compact library <database>` reports the "have no access rules"
  warning and install errors.
- `oasis --project <root> verify-module --compact library` (fresh install, update, tests) and
  `oasis --project <root> test-module --compact library` with tests that use a non-admin user of each group
  (`with_user`), for allowed and denied operations.

## Changed from earlier series

Oldest supported series.
