# Recipe: groups and model access (ir.model.access.csv)

Checked against: 15.0, 19.0.

Official docs: [19.0](https://www.odoo.com/documentation/19.0/developer/reference/backend/security.html#access-rights), [15.0](https://www.odoo.com/documentation/15.0/developer/reference/backend/security.html#access-rights)

Part of the [security skill](../SKILL.md). Record rules that filter *which* records a group sees are in
[record-rules.md](record-rules.md). Paths in `path:line` are relative to the Odoo source root of each series
(15.0 commit 3a28e5b0, 19.0 commit 8a2481dfc).

## When to use

A module adds a model, or a group that grants operations on a model: every concrete model, wizards
(`TransientModel`) included, needs at least one `ir.model.access` row, or only the superuser can use it
(the loader warns "The models [...] have no access rules in module ...", `odoo/modules/loading.py:259` in both
series). Typical shape: a *user* group with limited rights, a *manager* group that implies it with full rights.

## Files

1. `library/models/*.py`: the models (`library.book`, `library.loan`, `library.author`) of the backend recipes
   ([model.md](../../odoo-backend/references/model.md),
   [compute-constraint.md](../../odoo-backend/references/compute-constraint.md),
   [inheritance.md](../../odoo-backend/references/inheritance.md)), imported by `models/__init__.py`.
2. `library/security/library_groups.xml`: the privilege (19.0) and the groups, before anything that refers to
   them.
3. `library/security/ir.model.access.csv`: one row per (model, group); it refers to the groups, so it comes
   after them.
4. `library/security/library_rules.xml` ([record-rules.md](record-rules.md)), then views, menus and data.
5. `library/__manifest__.py` `data`: in that order, security first, as core modules do
   (`addons/fleet/__manifest__.py:32-33` and `addons/maintenance/__manifest__.py:14-15` in 19.0;
   `addons/fleet/__manifest__.py:32-33` in 15.0).

The model XML id `model_<model with dots as underscores>` (`model_library_book`) exists as soon as the model
is loaded, before the `data` files; a model of another module needs its prefix (`sale.model_sale_order`).

## Example

`library/__manifest__.py` (the final manifest of the
[module recipe](../../odoo-backend/references/module.md)):

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

`library/security/library_groups.xml`, the shape of `addons/maintenance/security/maintenance.xml:3-16` (19.0):
the application is the privilege's `category_id`, and the manager implies the user, who implies
`base.group_user` (internal user), so a manager has every right of both. `admin` is a manager, which the
[tour](../../odoo-testing/references/tours.md) relies on.

```xml
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

`library/security/ir.model.access.csv`: the header the loader itself suggests (`odoo/modules/loading.py:260`),
with the `ir.model.access` fields `name`, `model_id`, `group_id`, `perm_read`, `perm_write`, `perm_create`,
`perm_unlink` (19.0 `odoo/addons/base/models/ir_model.py:2101-2108`; 15.0 `:1717-1724`). Every internal user
(`base.group_user`) reads; the library user reads, writes and creates; only the manager deletes.

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

ACLs of a user's groups add up: a model is allowed for an operation when any active row of one of the
user's groups, or a row without group, grants it (19.0 `odoo/addons/base/models/ir_model.py:2157-2175`).
In code, test membership with `self.env.user.has_group('library.group_library_manager')`
(both series: 19.0 `odoo/addons/base/models/res_users.py:1066`, 15.0 `:895`) and a specification
`'a,!b'` with `self.env.user.has_groups(...)` (see *Changed in*).

## Changed in

| Point | Since | Before | Source |
|---|---|---|---|
| A group's application: `privilege_id` (`res.groups.privilege`), whose `category_id` is the `ir.module.category`; `res.groups` has no `category_id` | 19.0 | `category_id` on `res.groups` (`ir.module.category`, 15.0 `odoo/addons/base/models/res_users.py:208`); no privileges | `odoo/addons/base/models/res_groups.py:36`, `odoo/addons/base/models/res_groups_privilege.py:13` |
| A group's users: `res.groups.user_ids` | 19.0 | `users` (15.0 `odoo/addons/base/models/res_users.py:201`) | `odoo/addons/base/models/res_groups.py:17` |
| A user's groups: `res.users.group_ids` (given explicitly; write this in data and tests) and `all_group_ids` (adds the implied ones) | 19.0 | `groups_id` (15.0 `odoo/addons/base/models/res_users.py:367`); `group_ids` and `all_group_ids` do not exist | `odoo/addons/base/models/res_users.py:257-258` |
| Group name unique per privilege: `UNIQUE (privilege_id, name)` | 19.0 | unique per application, `unique (category_id, name)` (15.0 `odoo/addons/base/models/res_users.py:214`) | `odoo/addons/base/models/res_groups.py:39` |
| Transitive implied groups: `all_implied_ids` (and `implied_by_ids`); `implied_ids` itself is unchanged | 19.0 | `trans_implied_ids` (15.0 `odoo/addons/base/models/res_users.py:1131`; `implied_ids` at `:1129`) | `odoo/addons/base/models/res_groups.py:69-77` |
| Group specification `'a,!b'`: `self.env.user.has_groups(spec)`; `user_has_groups` is gone | 19.0 | `self.user_has_groups('a,!b')` on any model (15.0 `odoo/models.py:1466`); `res.users.has_groups` does not exist | `odoo/addons/base/models/res_users.py:1034` |
| An ACL row without group that grants an operation logs "Rule ... has no group, this is a deprecated feature" | 19.0 | accepted silently | `odoo/addons/base/models/ir_model.py:2229` |

A *Since* the source does not state is 19.0: the point changed after 15.0, by 19.0 at the latest.

The official security page of neither series describes `res.groups.privilege`; the privilege rows rely on the
source.

## Mistakes

- CSV listed before the groups XML in `data`: install fails on an external ID that does not exist yet.
- `model_id:id` written as the model name (`library.book`) instead of `model_library_book`, or a model of
  another module without its module prefix.
- Writing 15.0 names on 19.0 or the reverse: `category_id` or `users` on `res.groups`, `groups_id` on
  `res.users` in 19.0; `privilege_id`, `user_ids` or `group_ids` in 15.0. Either fails at install.
- An empty `group_id` "to make it work": the row applies to every user, portal and public included.
- No row for a new model or wizard: the loader warning is easy to miss, and every non-superuser gets an
  access error.
- A manager group that does not imply the user group, so managers lack the user rows (and rules).
- `perm_unlink` (or `perm_write`) granted to the user group by copy-paste; state the intended matrix and
  grant only that.
- Testing as admin only: `base.user_admin` is usually in the manager group (and `base.user_root` is the
  superuser), so it proves nothing about the user group.
- `has_group('group_library_user')` without the module prefix: the XML id must be fully qualified.

## Verify

- `oasis --project <root> model-info res.groups` and `oasis --project <root> model-info res.users --field group_ids`
  confirm the field names of the checkout's series before writing them.
- `oasis --project <root> module-info library --section security` lists the groups, the ACL lines per model
  and the rules as the module declares them, and `--section data` the `data` order.
- `oasis --project <root> update-module --compact library <database>` reports the "have no access rules"
  warning and install errors.
- `oasis --project <root> verify-module --compact library` (fresh install, update, tests) and
  `oasis --project <root> test-module --compact library` with tests that use a non-admin user of each group
  (`with_user`), for allowed and denied operations.
