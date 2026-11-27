# Recipe: record rules (ir.rule), multi-company rules and sudo

Checked against: 15.0.

Official docs: [15.0](https://www.odoo.com/documentation/15.0/developer/reference/backend/security.html#record-rules)

Part of the [security skill](../../SKILL.md). A path in `path:line` is relative to the Odoo source root of the
series written before it (15.0 at commit 3a28e5b0, 19.0 at commit 8a2481dfc), or of this series when none is
written. The groups and the access rows a rule builds on are explained in [access.md](access.md); this recipe
shows the same copies of their files, so it can be followed alone.

The example restricts the `library.book` of the `library` module the recipes build. It needs, from
`odoo-backend` (`references/<series>/` of that skill), `module.md` (the manifest, `models/__init__.py` and the
access CSV) and `model.md` (`library.book`, whose `user_id`, the librarian, and `company_id` the rules
filter on).

## When to use

An access row ([access.md](access.md)) allows an operation on a whole model; a record rule narrows it to the
records its domain matches. Use one when a group may see or change only some records (its own, its team's,
its companies'), and a global rule for company isolation.

How rules combine (15.0 `odoo/addons/base/models/ir_rule.py:148-170`; 19.0
`odoo/addons/base/models/ir_rule.py:141-174`):

- "Record rules are default-allow" (official security page): with no rule on a model for an operation, the
  access rows alone decide.
- A rule applies only to the operations whose `perm_read`, `perm_write`, `perm_create`, `perm_unlink` is
  true; all four default to true and at least one must be (15.0 `:25-34`; 19.0 `:27-35`).
- **Global** rules (no `groups`; `global` is computed as `not groups`, 15.0 `:64`, 19.0 `:56`) are AND-ed: no
  group can widen them.
- **Group** rules of the user's groups are OR-ed together, then AND-ed with the global ones. Rules of groups
  the user is not in are ignored; when none applies to an operation, only the global rules filter it.
- Superuser mode skips both the rules and the access rows: `_get_rules` returns no rule when `env.su` (15.0
  `:128-129`; 19.0 `:120-121`) and the access check returns true (15.0
  `odoo/addons/base/models/ir_model.py:1787-1789`; 19.0 `odoo/addons/base/models/ir_model.py:2179-2181`).

- `domain_force` is evaluated with `user` (the current user), `time` (the Python module), `company_ids` (the
  companies enabled in the switcher, by default all the user's companies) and `company_id` (the current
  company) (`odoo/addons/base/models/ir_rule.py:54-59`).

- A model filters only with its own rules: the rules of an `_inherits` parent do not apply to the child
  (`odoo/addons/base/models/ir_rule.py:148-151`).

## Files

1. `library/security/library_groups.xml` and `library/security/ir.model.access.csv`: the groups and rows of
   [access.md](access.md), the same copies.
2. `library/security/library_rules.xml`: the rules, in `<data noupdate="1">` as core modules do (15.0
   `addons/maintenance/security/maintenance.xml:11-70`; 19.0 `addons/maintenance/security/maintenance.xml:18-73`),
   after the groups they name.
3. `library/tests/test_library_rules.py`: allowed and denied paths for a non-admin user of each group,
   imported by `library/tests/__init__.py` (the file of the `model-tests` recipe of `odoo-testing`, shown
   here).
4. `library/__manifest__.py` `data`: groups, access CSV, rules, then views and data.

## Example

`library/__manifest__.py`, the manifest of `module.md` (building only this piece, keep the three
`security/` entries of `data` and drop the others and `assets`):

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

`library/security/library_groups.xml`, the file of [access.md](access.md): a user group and a manager group
that implies it, with `admin` among the managers.

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

`library/security/ir.model.access.csv`, the file of `module.md` (building only the book, keep its three rows):

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

`library/security/library_rules.xml`: library users read every book of their companies but write, create and
delete only the books they are the librarian of (`perm_read` false: the rule does not filter reads); managers,
who imply the user group, get a rule that matches everything, OR-ed with the user rule; a global rule isolates
companies, as the multi-company rules of `addons/maintenance/security/maintenance.xml` do (15.0 lines 42-64;
19.0 lines 49-71).

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

`+ [False]` keeps records without a company visible in every company, the form core uses (15.0
`addons/fleet/security/fleet_security.xml:86`; 19.0 `addons/fleet/security/fleet_security.xml:46`); it is
harmless here because `company_id` is required.

`library/tests/__init__.py`, the file of the `model-tests` recipe (building only this piece, keep the
`test_library_rules` import):

```python
from . import test_library_book
from . import test_library_rules
from . import test_ui
```

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
        with self.assertRaises(AccessError):
            self.theirs.with_user(self.user).check_access_rule('write')
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

The manager test writes `pages`, not `name`: the unique title of `model.md` refuses one title on two books. The
books are created by the superuser of the test (`cls.env`); `with_user` runs each check as the user it names,
with that user's rules.

In code, `records.check_access_rights('write')` checks the access rows (with `raise_exception=False` it returns
a boolean) and `records.check_access_rule('write')` the record rules of `records`, raising an `AccessError`
(`odoo/models.py:3559`, `:3565`); call both. `check_access` and `has_access` do not exist.

`records._filter_access_rules('write')` keeps the allowed subset (`odoo/models.py:3602`;
`_filter_access_rules_python` at `:3631` filters in Python).

`sudo()` keeps the user but skips both checks; its docstring warns it can cross record rules and mix companies
(`odoo/models.py:5259-5291`). `sudo(user)` with a user only logs "deprecated use of sudo(user), use
with_user(user) instead" and acts as `with_user` (`:5286-5288`).

So read or write only the fields needed, on records already checked, and never return sudo records to the
caller unfiltered. `with_user(user)` runs as that user with its rules: use it in tests.

A `Many2one` with `check_company=True` gets the company domain in the form only when it has no `domain` of its
own (`odoo/fields.py:2651-2652`).

A controller that returns records to the web client runs as the logged-in user, so the rules apply unless it
switches to `sudo()`; a JSON route there takes `type='json'`, as the only route types are `'http'` and `'json'`
(`odoo/http.py:451`).

`check_access`, `has_access` and `_filtered_access` are not on the official security page of either series;
those points rely on the source.

## Mistakes

### Remove an operation from the access row, not with `perm_read="False"`

Why: `perm_read` false on a rule means the rule does not filter reads, so every record stays readable; it
never forbids the operation.

Exceptions: a rule that should filter only writes, as the user rule of the example, sets the read flag false on
purpose.

```xml
<odoo>
    <record id="library_book_rule_no_read" model="ir.rule">
        <field name="name">Books: employees do not read</field>
        <field name="model_id" ref="model_library_book"/>
        <field name="groups" eval="[Command.link(ref('base.group_user'))]"/>
        <field name="perm_read" eval="False"/>
    </record>
</odoo>
```

```csv
id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink
access_library_book_user,library.book.user,model_library_book,group_library_user,1,1,1,0
```

### Isolate companies in one global rule and put ownership in group rules

Why: global rules are AND-ed for every user, admins included, so an ownership rule without group hides other
librarians' books from the managers too; several global rules on one model can leave no record at all, which
the 19.0 security page warns about.

Exceptions: none; one global company rule per model, the rest in group rules.

```xml
<odoo>
    <record id="library_book_rule_own" model="ir.rule">
        <field name="name">Books: own books</field>
        <field name="model_id" ref="model_library_book"/>
        <field name="domain_force">[('user_id', '=', user.id)]</field>
    </record>
</odoo>
```

```xml
<odoo>
    <record id="library_book_rule_own" model="ir.rule">
        <field name="name">Books: own books</field>
        <field name="model_id" ref="model_library_book"/>
        <field name="groups" eval="[Command.link(ref('group_library_user'))]"/>
        <field name="domain_force">[('user_id', '=', user.id)]</field>
    </record>
</odoo>
```

### Give the manager a rule that matches everything

Why: the manager implies the user group, so the user rule applies to managers too; without a manager rule to
OR it with, managers are restricted to their own books.

Exceptions: a manager that should be restricted like the user.

```xml
<odoo>
    <record id="library_book_rule_user" model="ir.rule">
        <field name="name">Books: own books</field>
        <field name="model_id" ref="model_library_book"/>
        <field name="groups" eval="[Command.link(ref('group_library_user'))]"/>
        <field name="domain_force">[('user_id', '=', user.id)]</field>
    </record>
</odoo>
```

```xml
<odoo>
    <record id="library_book_rule_user" model="ir.rule">
        <field name="name">Books: own books</field>
        <field name="model_id" ref="model_library_book"/>
        <field name="groups" eval="[Command.link(ref('group_library_user'))]"/>
        <field name="domain_force">[('user_id', '=', user.id)]</field>
    </record>
    <record id="library_book_rule_manager" model="ir.rule">
        <field name="name">Books: all books</field>
        <field name="model_id" ref="model_library_book"/>
        <field name="groups" eval="[Command.link(ref('group_library_manager'))]"/>
        <field name="domain_force">[(1, '=', 1)]</field>
    </record>
</odoo>
```

### Prove a changed `noupdate` rule on a fresh install

Why: an update does not overwrite a record of a `noupdate="1"` block that already exists
(`odoo/tools/convert.py:510`), so the changed domain never reaches an existing database and the update
"passes".

Exceptions: a rule outside a `noupdate` block, which an update rewrites.

```bash
oasis --project <root> update-module --compact library <database>
```

```bash
oasis --project <root> verify-module --compact library
```

### Filter companies on `company_ids`

Why: `company_id` is only the current company, so a rule on it hides the records of the other companies the
user enabled in the switcher.

Exceptions: drop `+ [False]` only when records without a company must be hidden; with an optional `company_id`
it keeps them visible.

```xml
<odoo>
    <record id="library_book_rule_company" model="ir.rule">
        <field name="name">Books: multi-company</field>
        <field name="model_id" ref="model_library_book"/>
        <field name="domain_force">[('company_id', '=', company_id)]</field>
    </record>
</odoo>
```

```xml
<odoo>
    <record id="library_book_rule_company" model="ir.rule">
        <field name="name">Books: multi-company</field>
        <field name="model_id" ref="model_library_book"/>
        <field name="domain_force">[('company_id', 'in', company_ids + [False])]</field>
    </record>
</odoo>
```

### Check access with the methods of the checkout's series

Why: `check_access` and `has_access` do not exist on this series, so the call raises `AttributeError`.

Exceptions: code that does not switch to `sudo()` needs no explicit check: the ORM checks the current user.

```python
def action_mark_lost(self):
    if not self.has_access('write'):
        return False
    self.sudo().write({'state': 'lost'})
    return True
```

```python
def action_mark_lost(self):
    self.check_access_rights('write')
    self.check_access_rule('write')
    self.sudo().write({'state': 'lost'})
    return True
```

### Switch the user with `with_user`, not `sudo(user)`

Why: `sudo(user)` only works through a deprecation path that logs a warning with a stack trace on every call,
and the name says superuser while the records run as the user with its rules.

Exceptions: none.

```python
book.sudo(self.user).write({'name': 'Taken'})
```

```python
book.with_user(self.user).write({'name': 'Taken'})
```

### Fix the rule, not the caller, after an access error

Why: `sudo()` around the failing call hides the bug, skips every rule and can mix companies; the next user of
the method inherits the hole.

Exceptions: a narrow read the user may not do but the feature needs (a count, a sequence), on records already
checked, with a comment that says why.

```python
def action_borrow(self):
    self.sudo().write({'state': 'borrowed', 'borrower_id': self.env.user.partner_id.id})
```

```python
def action_borrow(self):
    self.write({'state': 'borrowed', 'borrower_id': self.env.user.partner_id.id})
```

### Test rules as a user of each group

Why: `self.env` of a test is the superuser, which skips the rules, and `base.user_admin` is a manager, whose
rule matches everything; neither shows what the user group sees.

Exceptions: none.

```python
def test_user_cannot_take_a_book(self):
    self.theirs.write({'name': 'Taken'})
```

```python
def test_user_cannot_take_a_book(self):
    with self.assertRaises(AccessError):
        self.theirs.with_user(self.user).write({'name': 'Taken'})
```

## Verify

- `oasis --project <root> module-info library --section security` lists each rule with its model and groups
  (or global).
- `oasis --project <root> model-info library.book` confirms the fields a `domain_force` names exist (a wrong name
  fails the rule's domain check at install).
- `oasis --project <root> verify-module --compact library`: fresh install (noupdate rules created), update
  and tests.
- `oasis --project <root> test-module --compact library` runs the allowed and denied tests per group.

## Changed from earlier series

Oldest supported series.
