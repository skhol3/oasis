# Recipe: a web tour run by an HttpCase

Checked against: 15.0, 19.0.

Official docs: [19.0](https://www.odoo.com/documentation/19.0/developer/reference/backend/testing.html#integration-testing), [15.0](https://www.odoo.com/documentation/15.0/developer/reference/backend/testing.html#integration-testing)

## When to use

A test of a flow through the web client: open an action, fill a form, save, and check the result. Use a
[model test](model-tests.md) for logic that needs no browser; it is faster and more precise.

The example drives the model `library.book` of the [model test](model-tests.md) through its window action
`library.library_book_action` ([actions and menus recipe](../../odoo-views-frontend/references/actions-menus.md))
and the form of the [views recipe](../../odoo-views-frontend/references/views.md), which shows `name` and
`pages`; `admin` is in `library.group_library_manager`, whose ACL rows and record rule allow every operation
([access recipe](../../odoo-security/references/access.md),
[record rules recipe](../../odoo-security/references/record-rules.md)), so `admin` can create. It follows `crm`'s `crm_rainbowman` tour
(`addons/crm/static/tests/tours/crm_rainbowman.js:4`, run by `addons/crm/tests/test_crm_ui.py:31`). Paths
are relative to the Odoo source root.

## Files

1. `library/static/tests/tours/library_book_tour.js`: the tour, registered in the `web_tour.tours` registry.
2. `library/__manifest__.py`: the tour file in the `web.assets_tests` bundle under `assets`
   (`addons/crm/__manifest__.py:83`). `data` keeps its usual order (security before the views and actions
   that the tour opens); the tour needs no `data` entry.
3. `library/tests/__init__.py`: imports the test file.
4. `library/tests/test_ui.py`: the `HttpCase` that starts the tour.
5. The Python package `websocket-client` in the Odoo environment: without it every `HttpCase` browser test
   is skipped with "websocket-client module is not installed" (`odoo/tests/common.py:1273-1274`; 15.0
   `odoo/tests/common.py:932-933`), the run still reports 0 failed and `test-module` exits 0. Neither
   series' `requirements.txt` lists it; check the log for `skipped TestLibraryUi`.

## Example

`library/static/tests/tours/library_book_tour.js`:

```javascript
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
            trigger: ".o_field_widget[name=name] input",
            run: "edit Dune",
        },
        {
            content: "type its pages",
            trigger: ".o_field_widget[name=pages] input",
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

`library/__manifest__.py` (the final manifest of the [module recipe](../../odoo-backend/references/module.md)):

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

`library/tests/__init__.py` (the same file as the [model test](model-tests.md)):

```python
from . import test_library_book
from . import test_library_rules
from . import test_ui
```

`library/tests/test_ui.py`:

```python
from odoo.tests import HttpCase, tagged


@tagged('post_install', '-at_install')
class TestLibraryUi(HttpCase):

    def test_create_book_tour(self):
        self.start_tour('/odoo/action-library.library_book_action', 'library_book_tour', login='admin')
        book = self.env['library.book'].search([('name', '=', 'Dune')])
        self.assertEqual(book.pages, 412)
```

- `start_tour(url, name, login=...)` opens the URL in a headless Chrome as that user, waits for the tour to
  be ready and runs it (`odoo/tests/common.py:2590`). The browser's requests use the test's transaction,
  so the Python test sees what the tour created.
- A step waits for its `trigger`, then performs `run`: `"click"`, `"edit <text>"`, or a function
  (`addons/web_tour/static/src/js/tour_automatic/tour_step_automatic.js:103`). A step without `run` only
  waits for its trigger: end the tour with one, so it ends after the save, not before.
- `web_tour` depends on `web` and installs itself with it (`addons/web_tour/__manifest__.py:70`); on 19.0
  `mail` also depends on it (`addons/mail/__manifest__.py:63`), so the manifest does not list it.

## Changed in

| Point | Since | Before | Source |
|---|---|---|---|
| Tour registration | 19.0 | `import tour from 'web_tour.tour'; tour.register('name', { test: true }, [steps])` (15.0 `addons/web_tour/static/src/js/tour_manager.js:74`); a `url` option makes the run reload that URL, replacing the one `start_tour` opened, so leave it out when `start_tour` opens the action (15.0 `addons/web_tour/static/src/js/tour_manager.js:208-215`) | `addons/web_tour/static/src/js/tour_service.js:51` |
| `steps` | 19.0 | an array, the last argument of `tour.register` | `addons/web_tour/static/src/js/tour_service.js:53` |
| Step without `run` | 19.0 | performs the default action, a click or typing in an input, except on the last step (15.0 `addons/web_tour/static/src/js/tour_manager.js:524`) | `addons/web_tour/static/src/js/tour_automatic/tour_step_automatic.js:191` |
| Typing in a field | 19.0 | `run: 'text Dune'` (15.0 `addons/web_tour/static/src/js/running_tour_action_helper.js:28`) | `addons/web_tour/static/src/js/tour_automatic/tour_helpers_hoot.js:130` |
| `extra_trigger` | 19.0 | a second selector the step also waits for (15.0 `addons/crm/static/tests/tours/crm_rainbowman.js:33`); the 19.0 step schema has no such key | `addons/web_tour/static/src/js/tour_service.js:26` |
| Field input selector | 19.0 | `input[name=name]` (15.0 `addons/crm/static/tests/tours/crm_rainbowman.js:17`) | `addons/crm/static/tests/tours/crm_rainbowman.js:19` |
| A saved form: `.o_form_saved` | 19.0 | no such class: after the save the form goes back to read mode, `.o_form_readonly` (15.0 `addons/crm/static/tests/tours/crm_email_and_phone_propagation.js:29`) | `addons/web/static/src/views/form/form_compiler.js:227` |
| `/** @odoo-module **/` header | 19.0 | required for `import` syntax in any file (15.0 `odoo/tools/js_transpiler.py:593`); 19.0 treats every file under `static/src` and `static/tests` as a module | `odoo/tools/js_transpiler.py:726` |
| Web client URL | 19.0 | `/web`, `/web#action=<xmlid>` (15.0 `addons/web/controllers/main.py:816`) | `addons/web/static/src/core/browser/router.js:206` |
| JavaScript unit tests | 19.0 | QUnit, bundled in `web.qunit_suite_tests` (15.0 `addons/web/__manifest__.py:498`); 19.0 uses Hoot in `web.assets_unit_tests` | `addons/web/__manifest__.py:471` |

A *Since* the source does not state is 19.0: the point changed after 15.0, by 19.0 at the latest.

The official 19.0 testing page still shows the 15.0 form, `import tour from 'web_tour.tour'; tour.register(...)`;
the 19.0 source and the 19.0 tutorial *importable_modules* register with
`registry.category("web_tour.tours").add(...)` (`addons/web_tour/static/src/js/tour_service.js:58`, the category the service reads at `:67`), and this
recipe follows the source.

Unchanged: the `web.assets_tests` bundle under `assets` (15.0 `addons/crm/__manifest__.py:91`), the
`start_tour(url, name, login=...)` signature (15.0 `odoo/tests/common.py:1767`) and the
`post_install` tag of a UI test.

## Mistakes

- Putting the tour in `static/src` or in `web.assets_backend`: it then loads for every user. Test tours go
  in `static/tests/tours` and `web.assets_tests`.
- A tour name in `start_tour` that differs from the registered one: the run fails waiting for a tour that
  does not exist.
- `at_install` on an `HttpCase`: the registry is not fully loaded yet and the browser run warns `HttpCase
  test should be in post_install only` (`odoo/tests/common.py:2508`). Use `@tagged('post_install', '-at_install')`.
- On 19.0, a step without `run` expected to click: it only waits. Write `run: "click"`.
- On 19.0, `steps` as an array or a `test: true` key: the registry validates the tour against its schema in
  debug mode and rejects both (`addons/web/static/src/core/registry.js:14`).
- Ending on an action step and asserting nothing in Python: the tour can end before the server saved.
  End with a check step and assert the records after `start_tour`.
- Logging in as a user without the groups the flow needs: create it with `new_test_user` and pass its login.
- On 15.0, `url: '/web'` in `tour.register` with `start_tour('/web#action=...')`: the tour reloads `/web`
  (the home menu) and fails at its first step, waiting for `.o_list_button_add`.
- Selectors guessed from memory: read the view first; a field renders as `.o_field_widget[name=<field>]`.

## Verify

- `oasis --project <root> test-module --compact library`: the tour runs in the `post_install` phase of a
  disposable database; report the result line, the `log:` line and failures.
- `oasis --project <root> test-module --compact --only TestLibraryUi.test_create_book_tour library`: the
  tour alone while iterating (`--reuse` keeps the database; run once without it at the end).
- `oasis --project <root> view-info library.book` and
  `oasis --project <root> xmlid-info library.library_book_action`: the fields and the action the tour
  depends on.
- `oasis --project <root> verify-module --compact library`: the separate update check after a manifest
  `assets` or `data` change.
