# Recipe evals: did the agent write its series' forms?

The code skills hold one recipe per series (`<skill>/references/<series>/`). Having the right recipe
does not mean an agent used it: in Vercel's agent evals the skill was never opened in more than half of
the cases. Following Anthropic's advice to build the evaluations first, these evals check the result
rather than the route: in a module an agent wrote,
`tools/recipe_evals.py` looks for the forms of another series that are wrong on the checkout's series,
such as `<tree>` or `attrs` on 19.0, or `<list>`, `models.Constraint` and `invisible="state != 'draft'"`
on 15.0. A module without such forms whose tests pass shows that the agent followed its series' recipe.

## The checker

```bash
python3 tools/recipe_evals.py <series> <module-dir>
```

It scans the module's `.py`, `.xml`, `.js` and `.csv` files and prints one line per hit, then the count:

```text
wrong=views/library_member_views.xml:5: <tree> (list views are <list>: tree is not a view type)
hits=1
```

Exit codes: 0 no hit, 1 hits, 2 usage error (a series `tools/odoo_versions.py` does not support, a
supported series without forms, a missing directory). The forms are the `FORMS` table in the script:
per series, each form with its regular expression, the file kinds it applies to, the reason and the
line of the Odoo source of that series that proves it. Adding a series to `tools/odoo_versions.py`
makes the checker refuse it until its forms are added.

## In the release gate

For each supported series, in the field-run checkout of that series ([release gate](release-gate.md)),
give a fresh agent (a subagent) each of these tasks, one per run, with no hint of the series beyond what
oasis shows:

1. Add a model `library.member` with a unique email and a list view that hides inactive members.
2. Add a record rule so members see only the books of their company.
3. Add a field widget that shows the number of copies of a book.
4. Add a tour that creates a member.

After each task, run:

```bash
python3 tools/recipe_evals.py <series> <module>
oasis --project <root> test-module --compact <module>
```

Record per series and task: the hits, the test result and the recipe files the agent says it opened. A
task passes with `hits=0` and `test-module` exit 0. The release row names the series, the passed
tasks and each hit or failure; a hit on a form the recipe shows is a recipe fix before the release.
