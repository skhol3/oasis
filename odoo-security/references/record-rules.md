# Recipe: record rules (ir.rule), multi-company rules and sudo

Checked against: 15.0, 19.0.

Official docs: [19.0](https://www.odoo.com/documentation/19.0/developer/reference/backend/security.html#record-rules), [15.0](https://www.odoo.com/documentation/15.0/developer/reference/backend/security.html#record-rules)

Part of the [security skill](../SKILL.md). The groups and ACLs a rule builds on are in [access.md](access.md),
whose groups this recipe reuses, on the `library.book` of the
[model recipe](../../odoo-backend/references/model.md) (its `user_id`, the librarian, and `company_id`). Paths in
`path:line` are relative to the Odoo source root of each series (15.0 commit 3a28e5b0, 19.0 commit 8a2481dfc).

## When to use

An ACL ([access.md](access.md)) allows an operation on a whole model; a record rule narrows it to the
records whose domain matches. Use one when a group may see or change only some records (its own, its team's,
its companies'), and a global rule for company isolation.

How rules combine (19.0 `odoo/addons/base/models/ir_rule.py:141-173`, 15.0 `:148-170`):

- "Record rules are default-allow" (official security page): with no rule on a model for an operation, the
  ACL alone decides.
- A rule applies only to the operations whose `perm_read`, `perm_write`, `perm_create`, `perm_unlink` is
  true; all four default to true and at least one must be (19.0 `:27-35`, 15.0 `:25-34`).
- **Global** rules (no `groups`, `global` computed as `not groups`, 19.0 `:53-56`) are AND-ed: no group can
  widen them.
- **Group** rules (`groups`, 19.0 `:25`, 15.0 `:23`, the same field) of the user's groups are OR-ed
  together, then AND-ed with the global ones. Group rules of groups the user is not in are ignored; when
  none applies to an operation, only the global rules filter it.
- `domain_force` is evaluated with `user` (the current user), `company_ids` (the enabled companies:
  `allowed_company_ids`, else all the user's companies) and `company_id` (the current company)
  (19.0 `:47-51`, 15.0 `:54-59`).
- Superuser mode skips rules and ACLs: `_get_rules` returns no rule when `env.su` (19.0 `:120-121`, 15.0
  `:128-129`) and the ACL check returns true (19.0 `odoo/addons/base/models/ir_model.py:2179-2181`).

## Files

1. `library/security/library_groups.xml` and `library/security/ir.model.access.csv` from [access.md](access.md).
2. `library/security/library_rules.xml`: the rules, in `<data noupdate="1">` as core modules do
   (`addons/maintenance/security/maintenance.xml:18-73`, 19.0), after the groups they name.
3. `library/tests/test_library_rules.py` (imported by `tests/__init__.py`, given in
   [model-tests.md](../../odoo-testing/references/model-tests.md)): allowed and denied paths for a non-admin
   user of each group.
4. `library/__manifest__.py` `data`: groups, ACL CSV, rules, then views and data.

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

`library/security/library_rules.xml`: library users read all books of their companies but write and delete
only the books they are the librarian of (`perm_read` false: the rule does not filter reads); managers, who
imply the user group, get a rule that matches everything, OR-ed with the user rule; a global rule isolates
companies, as `addons/maintenance/security/maintenance.xml:21-58` (19.0) does.

```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <data noupdate="1">
        <record id="library_book_rule_user" model="ir.rule">
            <field name="name">Books: users change the books they are the librarian of</field>
            <field name="model_id" ref="model_library_book"/>
            <field name="groups" eval="[Command.link(ref('group_library_user'))]"/>
            <field name="domain_force">[('user_id', '=', user.id)]</field>
            <field name="perm_read" eval="False"/>
            <field name="perm_write" eval="True"/>
            <field name="perm_create" eval="True"/>
            <field name="perm_unlink" eval="True"/>
        </record>
        <record id="library_book_rule_manager" model="ir.rule">
            <field name="name">Books: managers change all books</field>
            <field name="model_id" ref="model_library_book"/>
            <field name="groups" eval="[Command.link(ref('group_library_manager'))]"/>
            <field name="domain_force">[(1, '=', 1)]</field>
        </record>
        <record id="library_book_rule_company" model="ir.rule">
            <field name="name">Books: multi-company</field>
            <field name="model_id" ref="model_library_book"/>
            <field name="domain_force">[('company_id', 'in', company_ids + [False])]</field>
        </record>
    </data>
</odoo>
```

`+ [False]` keeps records without a company visible in every company (core's form, e.g.
`addons/fleet/security/fleet_security.xml:43-47`); it is harmless here because `company_id` is required.

`library/tests/test_library_rules.py`:

```python
from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged('post_install', '-at_install')
class TestLibraryRules(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = new_test_user(cls.env, login='library_user', groups='library.group_library_user')
        cls.manager = new_test_user(cls.env, login='library_manager', groups='library.group_library_manager')
        cls.mine = cls.env['library.book'].create({'name': 'Mine', 'user_id': cls.user.id})
        cls.theirs = cls.env['library.book'].create({'name': 'Theirs', 'user_id': cls.manager.id})
        cls.books = cls.mine | cls.theirs

    def test_user_reads_all_but_writes_only_own(self):
        visible = self.env['library.book'].with_user(self.user).search([('id', 'in', self.books.ids)])
        self.assertEqual(visible, self.books)
        self.mine.with_user(self.user).write({'name': 'Still mine'})
        self.assertFalse(self.theirs.with_user(self.user).has_access('write'))
        with self.assertRaises(AccessError):
            self.theirs.with_user(self.user).write({'name': 'Taken'})

    def test_manager_writes_all(self):
        self.books.with_user(self.manager).write({'pages': 100})
        self.assertEqual(set(self.books.mapped('pages')), {100})

    def test_other_company_is_hidden(self):
        other = self.env['res.company'].create({'name': 'Other company'})
        hidden = self.env['library.book'].create({'name': 'Elsewhere', 'company_id': other.id})
        self.assertFalse(self.env['library.book'].with_user(self.manager).search([('id', '=', hidden.id)]))
```

The manager test writes `pages`, not `name`: the book's `UNIQUE (name)` constraint
([model.md](../../odoo-backend/references/model.md)) refuses one title on two books.

In code, `records.check_access('write')` raises an `AccessError` and `records.has_access('write')` returns
a boolean; both cover the ACL and the rules (19.0 `odoo/orm/models.py:4106`, `:4123`), and
`records._filtered_access('write')` keeps the allowed subset (`:4130`). `sudo()` keeps the user but skips
both checks (19.0 `:5973-5996`; its docstring warns it can cross record rules and mix companies), so read
or write only the fields needed, on records already checked, and never return sudo records to the caller
unfiltered. `with_user(user)` runs as that user with its rules: use it in tests.

## Changed in

| Point | Since | Before | Source |
|---|---|---|---|
| `check_access(op)` checks ACL and rules together and raises; `has_access(op)` returns a boolean; `check_access_rights` and `check_access_rule` are deprecated | 18.0 | `check_access_rights(op, raise_exception=True)` for the ACL and `check_access_rule(op)` for the rules, called separately (15.0 `odoo/models.py:3559`, `:3565`); `check_access` and `has_access` do not exist | `odoo/orm/models.py:4167`, `odoo/orm/models.py:4181` |
| Allowed subset: `_filtered_access(op)`; `_filter_access_rules` and `_filter_access_rules_python` are deprecated | 18.0 | `_filter_access_rules(op)` (15.0 `odoo/models.py:3602`) or `_filter_access_rules_python(op)` (`:3631`) | `odoo/orm/models.py:4191`, `odoo/orm/models.py:4196` |
| `domain_force` context has no `time`: only `user`, `company_ids`, `company_id` | 19.0 | `time` also available (15.0 `odoo/addons/base/models/ir_rule.py:56`) | `odoo/addons/base/models/ir_rule.py:47-51` |
| Rules of an `_inherits` parent model also filter the child (on its stored link field) | 19.0 | only the model's own rules (15.0 `odoo/addons/base/models/ir_rule.py:148-151`) | `odoo/addons/base/models/ir_rule.py:146-150` |
| `sudo()` takes only a boolean (`assert isinstance(flag, bool)`) | 19.0 | `sudo(user)` logged "deprecated use of sudo(user), use with_user(user) instead" and acted as `with_user` (15.0 `odoo/models.py:5286-5288`) | `odoo/orm/models.py:5994` |
| A `check_company=True` field with its own `domain` gets the company domain added to it | 19.0 | the company domain was used only when the field had no `domain` (15.0 `odoo/fields.py:2652`) | `odoo/orm/fields_relational.py:153-158` |

A *Since* the source does not state is 19.0: the point changed after 15.0, by 19.0 at the latest.

`check_access`, `has_access` and `_filtered_access` are not on the official security page of either series;
those rows rely on the source.

## Mistakes

- Reading `perm_read=False` as "cannot read": it means the rule does not filter reads. To forbid an
  operation, remove it from the ACL ([access.md](access.md)).
- Expecting a group rule to widen a global rule: globals are AND-ed for everybody, admins included unless
  in superuser mode. Company isolation belongs in a global rule; ownership in group rules.
- Several global rules on one model: they are AND-ed, and the 19.0 security page warns "Creating multiple
  global rules is risky as it's possible to create non-overlapping rulesets, which will remove all access."
  Keep one global company rule per model and put the rest in group rules.
- A manager rule missing: since the manager implies the user group, the user rule alone restricts managers
  too; add a manager rule with `[(1, '=', 1)]` to OR it away.
- Editing a rule in a `noupdate="1"` block and expecting `update-module` to change it on an existing
  database: an update does not overwrite a noupdate record that already exists (19.0
  `odoo/tools/convert.py:360`, 15.0 `:510`); prove the change on a fresh
  install.
- `company_id` in a multi-company rule instead of `company_ids`: it hides records of the other enabled
  companies.
- Forgetting `+ [False]` when `company_id` is optional: records without company disappear.
- Using `time` in `domain_force` on 19.0, or `check_access`/`has_access` on 15.0: the 19.0 rule fails its
  domain check, the 15.0 call raises `AttributeError`.
- `sudo()` to get past an access error in a test or a fix: it hides the bug and crosses company
  boundaries; fix the ACL or the rule, or keep `sudo()` to the narrowest read and justify it.
- Testing as `base.user_admin` or in the superuser `env` of a test: rules are skipped or widened; use
  `with_user` with a user of each group.

## Verify

- `oasis --project <root> module-info library --section security` lists each rule with its model and groups
  (or global).
- `oasis --project <root> model-info library.book` confirms the fields a `domain_force` names exist (a wrong name
  fails the rule's domain check at install).
- `oasis --project <root> verify-module --compact library`: fresh install (noupdate rules created), update
  and tests.
- `oasis --project <root> test-module --compact library` runs the allowed and denied tests per group.
