# Recipe: a model test (TransactionCase)

Checked against: 19.0.

Official docs: [19.0](https://www.odoo.com/documentation/19.0/developer/reference/backend/testing.html)

Part of the [testing skill](../../SKILL.md). A path in `path:line` is relative to the Odoo source root of the
series written before it (15.0 at commit 3a28e5b0, 19.0 at commit 8a2481dfc), or of this series when none is
written.

## When to use

A test of model logic: a constraint that rejects a value, a computed or written result, or an access right
checked as a given user. Use a [tour](tours.md) for a flow through the web client.

The example tests the `library.book` of the `library` module the recipes build. It needs, from `odoo-backend`
(`references/<series>/` of that skill), `module.md` (the manifest and the access CSV, whose
`base.group_user` row gives internal users read access only) and `model.md` (`library.book`: `name` with a
unique SQL constraint, `pages` with an `@api.constrains` that raises `ValidationError` below 1).

## Files

1. `library/tests/__init__.py`: imports each test file. Odoo imports the `tests` package of the module and
   collects only its submodules named `test_*` (15.0 `odoo/tests/loader.py:45-46`; 19.0
   `odoo/tests/loader.py:65`). The module's three test files are this recipe's, the record rule test of the
   `record-rules` recipe of `odoo-security` and the tour test of the [tour recipe](tours.md); building only
   this piece, keep the `test_library_book` import.
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

- `setUpClass` builds the data once for the class; each test runs in a savepoint rolled back after it (15.0
  `odoo/tests/common.py:803`, `:862-864`; 19.0 `odoo/tests/common.py:990`). `cls.env` is the superuser:
  access is only tested through `with_user`.
- `self.assertRaises` opens a savepoint and rolls it back when the exception is raised, so the test goes on
  with the data unchanged; for `AccessError` it also clears the cache first (15.0
  `odoo/tests/common.py:419-431`; 19.0 `odoo/tests/common.py:502-512`).
- A Python constraint raises on `create` or `write`; an SQL constraint raises `IntegrityError` only when the
  write reaches the database, hence the flush inside the block, and `mute_logger('odoo.sql_db')` silences the
  `bad query` error it logs (15.0 `odoo/sql_db.py:314`; 19.0 `odoo/sql_db.py:443`).

- The flush is `self.env.flush_all()` (`odoo/orm/environments.py:380`); records have no `flush()` method.

- `new_test_user` takes a comma-separated list of group XML ids, writes them to `group_ids` and fills name,
  password and email (`odoo/tests/common.py:195`, `:221-222`).

- Tags: a test class gets `standard` and `at_install` by default. `at_install` runs right after the module is
  installed; `post_install` runs after every module of the run is installed, so overrides from other modules
  are present. Name one of the two: `tagged` warns when a class has both or neither (15.0
  `odoo/tests/common.py:2834-2835`; 19.0 `odoo/tests/common.py:2767`).

- The default tags are set only on a class that has none (`odoo/tests/common.py:316-317`), so a subclass
  inherits the parent's `tagged`.

- From a test file the loader runs only the classes defined in that file and, of each, only the methods it
  defines itself (`odoo/tests/loader.py:25`, `:29`).

- `SavepointCase` no longer exists: write `TransactionCase`.

- `Form` lives in `odoo/tests/form.py:27`, re-exported by `odoo.tests` (`odoo/tests/__init__.py:10`); importing
  it from `odoo.tests.common` warns "Since 18.0: odoo.tests.common.Form is deprecated"
  (`odoo/tests/common.py:92-104`).

- `self.env.cr.commit()` and `rollback()` raise "Cannot commit or rollback a cursor from inside a test"
  (`odoo/tests/common.py:1069-1073`).

- `--test-tags` implies `--stop-after-init` (`odoo/tools/config.py:725-726`).

- A new database loads no demo data unless `--with-demo` (`odoo/tools/config.py:238-239`); oasis still passes
  `--without-demo` to its test runs, and `install-module --with-demo` and `create-database --with-demo` pass
  `--with-demo`.

- The second server port of a test run is `--gevent-port` (`odoo/tools/config.py:266`).

The official 15.0 testing page writes `odoo.tests.common.TransactionCase`, the 19.0 page
`odoo.tests.TransactionCase`; `odoo.tests` re-exports `common` in both series (15.0 `odoo/tests/__init__.py:2`;
19.0 `odoo/tests/__init__.py:9`), so the example's import works on both. The same holds for
`@tagged('post_install', '-at_install')`, `with_user` and `new_test_user(env, login, groups=...)`; and
`test-module --only Class[.method]` becomes `--test-tags /<module>:Class.method` in both.

## Mistakes

### Name test files `test_*.py` and import them

Why: a file with another name, or one `tests/__init__.py` does not import, is never collected, and the run
passes with no test of it.

Exceptions: helper modules (a base class, fixtures) are imported by the test files, not collected.

```python
from . import library_book_tests
```

```python
from . import test_library_book
```

### Tag a class `post_install` and remove `at_install`

Why: `at_install` is a default tag, so `@tagged('post_install')` alone leaves both and `tagged` warns that the
class is neither one nor the other.

Exceptions: a test that must run before other modules are installed keeps `at_install` only.

```python
@tagged('post_install')
class TestLibraryBook(TransactionCase):
    pass
```

```python
@tagged('post_install', '-at_install')
class TestLibraryBook(TransactionCase):
    pass
```

### Call `super().setUpClass()` first

Why: the parent's `setUpClass` opens the cursor and builds `cls.env`; without it there is no environment and
the class fails before its first test.

Exceptions: none.

```python
@classmethod
def setUpClass(cls):
    cls.book = cls.env['library.book'].create({'name': 'Dune'})
```

```python
@classmethod
def setUpClass(cls):
    super().setUpClass()
    cls.book = cls.env['library.book'].create({'name': 'Dune'})
```

### Test access through `with_user`

Why: `self.env` is the superuser and never raises `AccessError`, and a value it already cached is returned
without a check; read through `read()` or a search as the user.

Exceptions: none.

```python
def test_reader_cannot_create(self):
    self.env['library.book'].create({'name': 'Emma'})
```

```python
def test_reader_cannot_create(self):
    with self.assertRaises(AccessError):
        self.env['library.book'].with_user(self.reader).create({'name': 'Emma'})
```

### Create the users and records a test needs

Why: oasis installs test databases without demo data, so `base.user_demo` and demo records do not exist and
`env.ref` raises.

Exceptions: data the module itself loads in `data` (not `demo`).

```python
@classmethod
def setUpClass(cls):
    super().setUpClass()
    cls.reader = cls.env.ref('base.user_demo')
```

```python
@classmethod
def setUpClass(cls):
    super().setUpClass()
    cls.reader = new_test_user(cls.env, login='reader', groups='base.group_user')
```

### Flush before expecting an SQL error

Why: the write stays pending in the cache until a flush, so the block ends without `IntegrityError` and the
assertion fails; records have no `flush()` here.

Exceptions: a Python constraint raises on the write itself and needs no flush.

```python
with self.assertRaises(IntegrityError), mute_logger('odoo.sql_db'):
    other.name = 'Dune'
    other.flush()
```

```python
with self.assertRaises(IntegrityError), mute_logger('odoo.sql_db'):
    other.name = 'Dune'
    self.env.flush_all()
```

### Roll back to a savepoint, never commit

Why: the test cursor refuses it with "Cannot commit or rollback a cursor from inside a test", and the test
fails.

Exceptions: none; `assertRaises` and `self.env.cr.savepoint()` give the rollback a test needs.

```python
def test_name_is_unique(self):
    self.env['library.book'].create({'name': 'Emma'})
    self.env.cr.commit()
```

```python
def test_name_is_unique(self):
    with self.env.cr.savepoint():
        self.env['library.book'].create({'name': 'Emma'})
```

### Keep shared setup in a base class without tests

Why: the loader runs only the methods a class defines itself, so a subclass that adds only setup runs none of
the parent's tests.

Exceptions: none.

```python
@tagged('post_install', '-at_install')
class TestLibraryBook(TransactionCase):
    def test_pages_must_be_positive(self):
        pass


class TestLibraryBookManager(TestLibraryBook):
    pass
```

```python
class LibraryCase(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.book = cls.env['library.book'].create({'name': 'Dune'})


@tagged('post_install', '-at_install')
class TestLibraryBook(LibraryCase):
    def test_pages_must_be_positive(self):
        pass
```

### Write `TransactionCase`, not `SavepointCase`

Why: `SavepointCase` does not exist here, so the import fails and no test of the file runs.

Exceptions: none.

```python
from odoo.tests.common import SavepointCase


class TestLibraryBook(SavepointCase):
    pass
```

```python
from odoo.tests import TransactionCase


class TestLibraryBook(TransactionCase):
    pass
```

### Import `Form` from `odoo.tests`

Why: `odoo.tests` exports `Form` in every series, while the `odoo.tests.common` import warns as deprecated
from 18.0 on.

Exceptions: none.

```python
from odoo.tests.common import Form
```

```python
from odoo.tests import Form
```

## Verify

`<root>` is the project's absolute path: `--project` refuses a relative one.

- `oasis --project <root> test-module --compact library`: installs on a disposable database and runs the
  tests. Report the `phase=tests database=<name> exit=<code>` line, the `stdout_log=` and `stderr_log=` paths
  and the failures; the number of tests is only in the Odoo log (`stderr_log`), the line
  `<N> failed, <M> error(s) of <K> tests when loading database ...` (15.0 `odoo/service/server.py:566-568`;
  19.0 `odoo/service/server.py:722-725`), and `0 tests` there means none ran.
- `oasis --project <root> test-module --compact --only TestLibraryBook.test_name_is_unique library`: one
  class or method while iterating; add `--reuse` to keep the test database between runs, then run once
  without it. The kept database stays afterwards: `oasis --project <root> drop-database <name>` moves it to the
  trash, and it runs only with `--confirm <name>`.
- `oasis --project <root> model-info library.book`: the fields and constraints the test relies on.
- `oasis --project <root> verify-module --compact library`: lint, update and test when stored fields,
  data or security changed with the test.

## Changed from 15.0

- `book-test`: `self.env.flush_all()`
- `flush`: The flush is `self.env.flush_all()` (`odoo/orm/environments.py:380`); records have no `flush()` method.
- `new-test-user-groups`: `new_test_user` takes a comma-separated list of group XML ids, writes them to `group_ids` and fills name,
- `subclass-tags`: The default tags are set only on a class that has none (`odoo/tests/common.py:316-317`), so a subclass
- `test-collection`: From a test file the loader runs only the classes defined in that file and, of each, only the methods it
- `savepoint-case`: `SavepointCase` no longer exists: write `TransactionCase`.
- `form-import`: `Form` lives in `odoo/tests/form.py:27`, re-exported by `odoo.tests` (`odoo/tests/__init__.py:10`); importing
- `commit`: `self.env.cr.commit()` and `rollback()` raise "Cannot commit or rollback a cursor from inside a test"
- `test-tags-stop`: `--test-tags` implies `--stop-after-init` (`odoo/tools/config.py:725-726`).
- `demo-data`: A new database loads no demo data unless `--with-demo` (`odoo/tools/config.py:238-239`); oasis still passes
- `server-port`: The second server port of a test run is `--gevent-port` (`odoo/tools/config.py:266`).
- `flush-rule`: Why: the write stays pending in the cache until a flush, so the block ends without `IntegrityError` and the
- `commit-why`: Why: the test cursor refuses it with "Cannot commit or rollback a cursor from inside a test", and the test
- `inherited-tests-why`: Why: the loader runs only the methods a class defines itself, so a subclass that adds only setup runs none of
- `savepoint-case-why`: Why: `SavepointCase` does not exist here, so the import fails and no test of the file runs.
