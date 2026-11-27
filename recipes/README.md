# Recipe sources

One source per recipe: `recipes/<skill>/<recipe>.md` renders into `<skill>/references/<series>/<recipe>.md`
for every series `tools/odoo_versions.py` supports. These files are not skills (no `SKILL.md`); agents
read the rendered files, which are committed because `install.sh` installs the committed HEAD.

```bash
python3 tools/render_recipes.py           # write the rendered files that differ
python3 tools/render_recipes.py --check   # exit 1 listing stale files; the suite runs it
```

Edit the source, never a rendered file. A source error (`<source>:<line>: <reason>`) exits 2 and writes
nothing.

## Format

- Unmarked text and unmarked fences are shared by every series.
- A fence with an `id` is one variant of that block: ` ```python id=book since=19.0 `. It applies from
  its `since` series (from the oldest supported series without `since`) until a later `since` block with
  the same `id` replaces it. Attributes are `id=` and `since=` only, in any order; `since` needs `id`.
  The rendered fence keeps the language only (` ```python `).
- Prose that differs per series is a prose block, marked the same way:

  ```markdown
  <!-- since=19.0 id=display-name -->
  Override `_compute_display_name`.
  <!-- end -->
  ```

  An empty prose block removes its id from that series on. Fences inside a prose block take no
  attributes; a fence and a prose block may share an id.
- A block applies to no series older than its first `since`. Adding a series means adding only the
  blocks where it differs, and its `Official docs:` entry.
- `Checked against: <anything>` renders as `Checked against: <series>.`
- `Official docs: 15.0=<url>, 19.0=<url>` maps each series to its page; it needs an entry for every
  supported series and renders as `Official docs: [<series>](<url>)`.
- Do not write `## Changed from`: the renderer appends it. The oldest series gets
  `## Changed from earlier series` with `Oldest supported series.`; a later one gets
  `## Changed from <previous supported series>` listing, as `` - `<id>`: <first line> ``, each id whose
  content differs from that series (`removed` when it is gone), else `No change from <previous>.`
  Choose ids that name the change (`display-name`, `list-tag`).
- Links are relative to the rendered file: `[model](model.md)` is the same series' recipe,
  `../../SKILL.md` the skill.

## Sections

A rendered recipe has `## When to use`, `## Files`, `## Example`, `## Mistakes`, `## Verify` and the
generated `## Changed from ...`, in that order (`tests/test_skill_recipes.py`). Each mistake is a rule:

````markdown
### <rule>

Why: <what breaks>.

Exceptions: <when the rule does not apply, or none>.

```python
<the bad form>
```

```python
<the good form>
```
````

A `SKILL.md` names no series: each Decision Gates row names its recipe as `` `references/<series>/<recipe>.md` ``
(not a link), and the body says to run `oasis doctor` and open `references/<series>/` for its `series=`.
