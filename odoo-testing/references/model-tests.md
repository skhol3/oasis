# Recipe: a model test (TransactionCase)

Checked against: 15.0, 19.0.

Official docs: [19.0](https://www.odoo.com/documentation/19.0/developer/reference/backend/testing.html), [15.0](https://www.odoo.com/documentation/15.0/developer/reference/backend/testing.html)

## When to use

A test of model logic: a constraint that rejects a value, a computed or written result, or an access right
checked as a given user. Use a [tour](tours.md) for a flow through the web client.

The example tests the `library.book` of the `library` module the recipes build
([module recipe](../../odoo-backend/references/module.md), [model recipe](../../odoo-backend/references/model.md)):
`name` with a unique SQL constraint, `pages` with an `@api.constrains` that raises `ValidationError` below 1,
and an ACL that gives `base.group_user` read access only
([access recipe](../../odoo-security/references/access.md)). Paths are relative to the Odoo source root.

## Files

1. `library/tests/__init__.py`: imports each test file. Odoo imports the `tests` package of the module and
   collects only its submodules named `test_*` (`odoo/tests/loader.py:56`). The module's three test files:
   this recipe's, the record rule test of the
   [record rules recipe](../../odoo-security/references/record-rules.md) and the tour test of the
   [tour recipe](tours.md).
2. `library/tests/test_library_book.py`: the test class.

The module's own `__init__.py` does not import `tests`, and the manifest lists no test file.

## Example

`library/tests/__init__.py`:

```python
from . import test_library_book
from . import test_library_rules
from . import test_ui
```

`library/tests/test_library_book.py`:

```python
from psycopg2 import IntegrityError

from odoo.exceptions import AccessError, ValidationError
from odoo.tests import TransactionCase, new_test_user, tagged
from odoo.tools import mute_logger


@tagged('post_install', '-at_install')
class TestLibraryBook(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.book = cls.env['library.book'].create({'name': 'Dune', 'pages': 412})
        cls.reader = new_test_user(cls.env, login='reader', groups='base.group_user')

    def test_pages_must_be_positive(self):
        with self.assertRaises(ValidationError):
            self.book.pages = 0
        self.assertEqual(self.book.pages, 412)

    def test_name_is_unique(self):
        other = self.env['library.book'].create({'name': 'Emma', 'pages': 300})
        with self.assertRaises(IntegrityError), mute_logger('odoo.sql_db'):
            other.name = 'Dune'
            self.env.flush_all()

    def test_reader_reads_but_cannot_create(self):
        self.assertEqual(self.book.with_user(self.reader).read(['name'])[0]['name'], 'Dune')
        with self.assertRaises(AccessError):
            self.env['library.book'].with_user(self.reader).create({'name': 'Emma', 'pages': 300})
```

- `setUpClass` builds the data once for the class; each test runs in a savepoint rolled back after it
  (`odoo/tests/common.py:990`). `cls.env` is the superuser: access is only tested through `with_user`.
- `self.assertRaises` opens a savepoint and rolls it back when the exception is raised, so the test goes on
  with the data unchanged (`odoo/tests/common.py:502`). For `AccessError` it also clears the cache first.
- A Python constraint raises on `create` or `write`; an SQL constraint raises `IntegrityError` only when
  the write reaches the database, hence `flush_all()` inside the block, and `mute_logger('odoo.sql_db')`
  silences the `bad query` error it logs (`odoo/sql_db.py:443`).
- `new_test_user` takes a comma-separated list of group XML ids and fills name, password and email
  (`odoo/tests/common.py:195`).
- Tags: every test class starts with `standard` and `at_install` (`odoo/tests/common.py:316`). `at_install`
  runs right after the module is installed; `post_install` runs after every module of the run is installed,
  so overrides from other modules are present. Name one of the two: `tagged` warns when a class has both or
  neither (`odoo/tests/common.py:2767`).
- The official 15.0 testing page writes `odoo.tests.common.TransactionCase`, the 19.0 page
  `odoo.tests.TransactionCase`; `odoo.tests` re-exports `common` in both series (`odoo/tests/__init__.py:9`;
  15.0 `odoo/tests/__init__.py:2`), so the example's import works on both.

## Changed in

| Point | Since | Before | Source |
|---|---|---|---|
| `from odoo.tests import Form` | 18.0 | `from odoo.tests.common import Form` (15.0 `odoo/tests/common.py:1884`) | `odoo/tests/common.py:101` |
| `TransactionCase` only | 19.0 | `SavepointCase` also existed, a deprecated alias that warns (15.0 `odoo/tests/common.py:869`) | `odoo/tests/common.py:990` |
| Flush before asserting an SQL error | 19.0 | `self.env['base'].flush()` or `records.flush()` (15.0 `odoo/models.py:5668`) | `odoo/orm/environments.py:380` |
| Groups of a user written with `create` | 19.0 | `groups_id` (15.0 `odoo/tests/common.py:136`) | `odoo/tests/common.py:221` |
| Tags of a test subclass | 19.0 | reset to `standard`, `at_install` on every class, so a subclass does not inherit `tagged` (15.0 `odoo/tests/common.py:295`) | `odoo/tests/common.py:316` |
| Tests collected from a test file | 19.0 | every test class in the file's namespace, imported ones and inherited `test_*` methods included (15.0 `odoo/tests/loader.py:85`); 19.0 runs only the classes defined in the file and their own methods | `odoo/tests/loader.py:25` |
| `cr.commit()` in a test | 19.0 | not blocked: the class cursor is a plain database cursor, so it commits test data (15.0 `odoo/modules/registry.py:728`) | `odoo/tests/common.py:1071` |
| `--test-tags` ends the server | 19.0 | does not imply `--stop-after-init` (15.0 `odoo/tools/config.py:534`); oasis passes `--stop-after-init` on every test run, so a run still ends | `odoo/tools/config.py:726` |
| Demo data in a new database | 19.0 | loaded by default; `--without-demo` takes a value (15.0 `odoo/tools/config.py:111`), so oasis passes `--without-demo=all`, and `install-module --with-demo` and `init-dev-database --with-demo` pass nothing and get the default demo data. On 19.0 there is none unless `--with-demo`; oasis still passes `--without-demo`, and those two commands pass `--with-demo` | `odoo/tools/config.py:238` |
| Second server port of a test run | 19.0 | `--longpolling-port` (15.0 `odoo/tools/config.py:136`) | `odoo/tools/config.py:266` |

A *Since* the source does not state is 19.0: the point changed after 15.0, by 19.0 at the latest.

Unchanged: `@tagged('post_install', '-at_install')`, `assertRaises` with its savepoint, `with_user`,
`new_test_user(env, login, groups=...)`, and `test-module --only Class[.method]`, which becomes
`--test-tags /<module>:Class.method` (15.0 `odoo/tests/common.py:2842`).

## Mistakes

- A test file not named `test_*.py` or not imported in `tests/__init__.py`: nothing collects it and the run
  passes with no test of it.
- `@tagged('post_install')` without `-at_install`: the class keeps `at_install` too and `tagged` warns.
- Forgetting `super().setUpClass()`: there is no `cls.env`.
- Testing access with `self.env`: it is the superuser and never raises `AccessError`. Switch with
  `with_user(user)` and read through `read()` or a search, not a value the superuser already cached.
- Relying on demo records such as `base.user_demo`: oasis installs without demo data. Create users with
  `new_test_user` and records in `setUpClass`.
- Expecting `IntegrityError` from a `write` without `flush_all()`: the update is still pending when the
  block ends and the assertion fails.
- Calling `self.env.cr.commit()` or `rollback()`: 19.0 raises `AssertionError`; 15.0 commits test data
  into the database. Use `assertRaises` or `self.env.cr.savepoint()`.
- A subclass of a test class expecting the parent's tests to run again on 19.0: they do not (Changed in).

## Verify

- `oasis --project <root> test-module --compact library`: installs on a disposable database and runs the
  tests; report the result line, the `log:` line and failures.
- `oasis --project <root> test-module --compact --only TestLibraryBook.test_name_is_unique library`: one
  class or method while iterating; add `--reuse` to keep the test database between runs, then run once
  without it.
- `oasis --project <root> model-info library.book`: the fields and constraints the test relies on.
- `oasis --project <root> verify-module --compact library`: lint, update and test when stored fields,
  data or security changed with the test.
