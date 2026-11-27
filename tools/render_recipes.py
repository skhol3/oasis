#!/usr/bin/env python3
"""Render the recipe sources under recipes/ into one file per supported Odoo series (v0.19.0 S2).

Each `recipes/<skill>/<recipe>.md` renders, for every series tools/odoo_versions.py supports, into
`<skill>/references/<series>/<recipe>.md`. recipes/README.md describes the source format: unmarked text
is shared; a fenced block (```python id=book since=<series>) or a prose block
(<!-- since=<series> id=book --> ... <!-- end -->) with an `id` applies from its `since` series (from the
oldest without one) until a later block of the same id replaces it; `Checked against:` and
`Official docs:` lines name the rendered series. Each rendered file ends with a generated
`## Changed from <previous series>` section listing the ids whose content differs from that series.

Usage: render_recipes.py [--check] [--root <repository>]
Without --check it writes the rendered files that differ. --check renders into a temporary directory
and exits 1 listing every stale file (differing, missing, or in a series directory with no source).
A source error exits 2 and writes nothing.
"""
import argparse
import importlib.util
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERIES = re.compile(r'\d+\.0')
ATTRIBUTES = ('id', 'since')
PROSE_OPEN = re.compile(r'<!--((?:\s+[\w-]+=\S+)+)\s+-->$')
PROSE_END = '<!-- end -->'
OLDEST_TITLE = 'earlier series'
OLDEST_TEXT = 'Oldest supported series.'
# Lines of a fenced block that say nothing about it in the Changed from section: blank or punctuation
# only, an XML declaration, a root <odoo>, <templates> or <data> tag, an import, a module header.
UNINFORMATIVE = re.compile(r'''[\W_]*$|<\?xml\b|</?(?:odoo|templates|data)\b[^<]*$|(?:from\s+\S+\s+)?import\b
                               |/\*\*\s*@odoo-module|["']use\ strict["'];?$''', re.X)


class RecipeError(ValueError):
    """A recipe source that does not follow recipes/README.md: `<source>:<line>: <reason>`."""


def series_key(series):
    return tuple(int(part) for part in series.split('.'))


def supported_series():
    spec = importlib.util.spec_from_file_location('render_recipes_odoo_versions',
                                                  Path(__file__).with_name('odoo_versions.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.supported()


class Variant:
    """One block of an id: its content lines (a fence with its plain info string, or prose) from since."""

    def __init__(self, block_id, since, kind, line):
        self.id, self.since, self.kind, self.line, self.lines = block_id, since, kind, line, []

    def key(self):
        return series_key(self.since) if self.since else (0,)

    def text(self):
        """The rendered content, or None for an empty prose block (the id is removed from its series)."""
        if self.kind == 'prose' and not any(line.strip() for line in self.lines):
            return None
        return ''.join(self.lines)

    def label(self, previous=None):
        """What the Changed from section shows after the id, or '' for the id alone. Prose: its first line.
        A fence: its first informative line (not UNINFORMATIVE), preferring one the block of the previous
        series lacks, so a manifest is labelled by its changed `version` line rather than by `{`."""
        if self.kind == 'prose':
            first = next((line.strip() for line in self.lines if line.strip()), '')
            return re.sub(r'^(?:#+|[-*]|\d+\.)\s+', '', first)
        informative = [line.strip() for line in self.lines[1:-1]
                       if line.strip() and not UNINFORMATIVE.match(line.strip())]
        before = {line.strip() for line in previous.lines} if previous is not None else set()
        first = next((line for line in informative if line not in before), informative[0] if informative else '')
        if not first:
            return ''
        return f'`` {first} ``' if '`' in first else f'`{first}`'


def attributes(tokens, where):
    found = {}
    for token in tokens:
        key, equals, value = token.partition('=')
        if not equals or key not in ATTRIBUTES:
            raise RecipeError(f'{where}: unknown attribute {key}')
        found[key] = value
    if 'since' in found and not SERIES.fullmatch(found['since']):
        raise RecipeError(f'{where}: since={found["since"]} is not a series')
    if 'since' in found and 'id' not in found:
        raise RecipeError(f'{where}: since= needs id=')
    return found


def parse(text, source):
    """The source as items: ('text' or 'code', line, number) for shared lines, Variant for marked blocks."""
    items, seen, current, fence, opened = [], set(), None, False, 0
    for number, line in enumerate(text.splitlines(keepends=True), 1):
        where = f'{source}:{number}'
        bare = line.rstrip('\n')
        if fence:
            (current.lines if current else items).append(line if current else ('code', line, number))
            if bare.rstrip() == '```':
                fence = False
                if current and current.kind == 'fence':
                    current = None
            continue
        if current is not None and current.kind == 'prose':
            if bare.strip() == PROSE_END:
                current = None
            elif bare.startswith('```'):
                info = bare[3:].split()
                if [token for token in info if '=' in token]:
                    raise RecipeError(f'{where}: a fence inside the prose block of line {opened} takes no '
                                      f'attributes (is its {PROSE_END} missing?)')
                fence, opened = True, number
                current.lines.append(line)
            elif PROSE_OPEN.match(bare.strip()):
                raise RecipeError(f'{where}: a prose block inside the prose block of line {opened} '
                                  f'(is its {PROSE_END} missing?)')
            else:
                current.lines.append(line)
            continue
        variant = None
        if bare.startswith('```') and bare.rstrip() != '```':
            info = bare[3:].split()
            language = info.pop(0) if info and '=' not in info[0] else ''
            found = attributes(info, where)
            fence, opened = True, number
            if not found:
                items.append(('code', line, number))
                continue
            variant = Variant(found['id'], found.get('since'), 'fence', number)
            variant.lines.append(f'```{language}\n')
        elif match := PROSE_OPEN.match(bare.strip()):
            found = attributes(match[1].split(), where)
            if 'id' not in found:
                raise RecipeError(f'{where}: a prose block needs id=')
            variant = Variant(found['id'], found.get('since'), 'prose', number)
            opened = number
        elif bare.strip() == PROSE_END:
            raise RecipeError(f'{where}: {PROSE_END} without a block')
        elif re.match(r'## Changed from\b', bare):
            raise RecipeError(f'{where}: the renderer writes the Changed from section')
        else:
            items.append(('text', line, number))
            continue
        if (variant.id, variant.since) in seen:
            since = f'since={variant.since}' if variant.since else 'without since'
            raise RecipeError(f'{where}: id={variant.id} {since} twice')
        seen.add((variant.id, variant.since))
        items.append(variant)
        current = variant
    if fence:
        raise RecipeError(f'{source}:{opened}: unclosed fence')
    if current is not None:
        raise RecipeError(f'{source}:{opened}: unclosed block')
    return items


def chosen(items, series):
    """For each id, the variant that applies on series: the latest since at or before it."""
    best = {}
    for item in items:
        if isinstance(item, Variant) and item.key() <= series_key(series):
            if item.id not in best or item.key() > best[item.id].key():
                best[item.id] = item
    return best


def series_lines(line, number, series, supported, source):
    """A shared `Checked against:` or `Official docs:` line, for series."""
    if line.startswith('Checked against:'):
        return f'Checked against: {series}.\n'
    if not line.startswith('Official docs:'):
        return line
    pages = {}
    for entry in line[len('Official docs:'):].strip().split(','):
        match = re.fullmatch(r'(\d+\.0)=(https?://\S+)', entry.strip())
        if not match:
            raise RecipeError(f'{source}:{number}: Official docs entry {entry.strip()!r} is not <series>=<url>')
        pages[match[1]] = match[2]
    for item in supported:
        if item not in pages:
            raise RecipeError(f'{source}:{number}: no Official docs page for {item}')
    return f'Official docs: [{series}]({pages[series]})\n'


def tidy(lines):
    """One blank line at most between blocks outside fences (a block absent from a series leaves two)."""
    out, fence = [], False
    for line in lines:
        blank = not line.strip()
        if not fence and blank and (not out or not out[-1].strip()):
            continue
        if line.startswith('```'):
            fence = not fence
        out.append(line)
    while out and not out[-1].strip():
        out.pop()
    return ''.join(out)


def changed_section(items, series, previous):
    if previous is None:
        return f'## Changed from {OLDEST_TITLE}\n\n{OLDEST_TEXT}\n'
    now, before = chosen(items, series), chosen(items, previous)
    order = list(dict.fromkeys(item.id for item in items if isinstance(item, Variant)))
    entries = []
    for block_id in order:
        new, old = now.get(block_id), before.get(block_id)
        new_text = new.text() if new else None
        if new_text == (old.text() if old else None):
            continue
        label = new.label(old if old is not None and old.text() is not None else None) if new_text is not None else 'removed'
        entries.append(f'- `{block_id}`' + (f': {label}' if label else '') + '\n')
    return f'## Changed from {previous}\n\n' + (''.join(entries) or f'No change from {previous}.\n')


def render(text, series, supported, source='<source>'):
    """The recipe source text rendered for series, one of supported."""
    ordered = sorted(supported, key=series_key)
    if series not in ordered:
        raise ValueError(f'{series} is not among {ordered}')
    items = parse(text, source)
    best = chosen(items, series)
    lines = []
    for item in items:
        if isinstance(item, Variant):
            if best.get(item.id) is item and item.text() is not None:
                lines += item.lines
        elif item[0] == 'code':
            lines.append(item[1])
        else:
            lines.append(series_lines(item[1], item[2], series, ordered, source))
    index = ordered.index(series)
    previous = ordered[index - 1] if index else None
    return tidy(lines) + '\n' + changed_section(items, series, previous)


def render_tree(root, supported):
    """{repository-relative path: text} of every source rendered for every series, in source order."""
    rendered = {}
    for path in sorted((root / 'recipes').glob('*/*.md')):
        source = path.relative_to(root).as_posix()
        text = path.read_text(encoding='utf-8')
        for series in sorted(supported, key=series_key):
            rendered[f'{path.parent.name}/references/{series}/{path.name}'] = render(text, series, supported, source)
    return rendered


def without_source(root, rendered):
    """Files in a series directory of a skill with sources that no source renders."""
    skills = {path.split('/')[0] for path in rendered}
    found = []
    for skill in sorted(skills):
        for path in sorted((root / skill / 'references').glob('*/*.md')):
            relative = path.relative_to(root).as_posix()
            if SERIES.fullmatch(path.parent.name) and relative not in rendered:
                found.append(relative)
    return found


def write(base, path, text):
    target = base / path
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, 'w', encoding='utf-8', newline='\n') as handle:
        handle.write(text)


def check(root, rendered):
    with tempfile.TemporaryDirectory(prefix='oasis-render-recipes-') as scratch:
        for path, text in rendered.items():
            write(Path(scratch), path, text)
        stale = [path for path in rendered if not (root / path).is_file()
                 or (root / path).read_bytes() != (Path(scratch) / path).read_bytes()]
    stale = sorted(stale + without_source(root, rendered))
    for path in stale:
        print(f'render_recipes: stale {path}')
    if stale:
        files = 'file' if len(stale) == 1 else 'files'
        print(f'render_recipes: {len(stale)} stale {files}; run python3 tools/render_recipes.py.')
        return 1
    print(f'render_recipes: {len(rendered)} files fresh.')
    return 0


def update(root, rendered):
    written = 0
    for path, text in rendered.items():
        target = root / path
        if target.is_file() and target.read_text(encoding='utf-8') == text:
            continue
        write(root, path, text)
        written += 1
        print(f'render_recipes: wrote {path}')
    print(f'render_recipes: {len(rendered)} files, {written} written.')
    orphans = without_source(root, rendered)
    for path in orphans:
        print(f'render_recipes: no source renders {path}; remove it.')
    return 1 if orphans else 0


def main(arguments=None):
    parser = argparse.ArgumentParser(description='Render recipes/ into <skill>/references/<series>/.')
    parser.add_argument('--check', action='store_true', help='exit 1 listing stale rendered files')
    parser.add_argument('--root', type=Path, default=ROOT, help='repository root (default: this checkout)')
    options = parser.parse_args(arguments)
    root = options.root.resolve()
    try:
        rendered = render_tree(root, supported_series())
    except RecipeError as error:
        print(f'render_recipes: {error}', file=sys.stderr)
        return 2
    return check(root, rendered) if options.check else update(root, rendered)


if __name__ == '__main__':
    raise SystemExit(main())
