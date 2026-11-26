"""What a new requirement input would make fail later, found while `oasis setup` plans (v0.16.0 S3).

setup asks about each problem in its plan instead of failing at --apply (docs/setup.md#anticipated-problems):

- python-ldap: the series' ldap_override (tools/odoo_versions.py) names an Odoo pin that does not build
  against OpenLDAP 2.6 (python-ldap 3.4.0 links libldap_r, which 2.6 removed). It is a problem when the
  source's requirements.txt has that pin for the environment's Python and this machine has OpenLDAP 2.6 or
  later without libldap_r: `pkg-config --modversion ldap`, else the libldap names `ldconfig -p` lists
  (libldap-2.<x>.so is that version, libldap.so the 2.6 name); with libldap_r, or when neither program says
  anything, there is no problem to report.
- external_dependencies: each python requirement a module manifest of the checkout declares that the
  requirements do not list (missing), or that an Odoo pin does not satisfy (conflict). Import names that
  name another distribution (ldap: python-ldap, ...) are translated, and standard library modules skipped.

Requirement lines are read as pip reads them closely enough for pins: `name[extras] <clauses> ; marker`,
comments and options (-r, -c, --...) left out; a marker is evaluated for python_version, python_full_version,
sys_platform and platform_system joined by `and` (any other marker counts as applying). Versions compare
numerically; one that is not numbers and dots is never reported.
"""
import ast
import re
import shutil
import subprocess
import sys
from pathlib import Path

REQUIREMENT = re.compile(r'([A-Za-z0-9][A-Za-z0-9._-]*)\s*(?:\[[^\]]*\])?\s*(.*)')
CLAUSE = re.compile(r'(===|==|>=|<=|~=|!=|>|<)\s*([0-9][0-9.]*(?:\.\*)?)')
MARKER = re.compile(r'''(python_version|python_full_version|sys_platform|platform_system)\s*(==|!=|>=|<=|>|<)\s*'''
                    r'''['"]([^'"]*)['"]''')
# Import names that external_dependencies may list for a distribution of another name.
DISTRIBUTIONS = {'ldap': 'python-ldap', 'dateutil': 'python-dateutil', 'yaml': 'pyyaml', 'pil': 'pillow',
                 'serial': 'pyserial', 'usb': 'pyusb', 'openssl': 'pyopenssl', 'jwt': 'pyjwt',
                 'crypto': 'pycryptodome', 'magic': 'python-magic', 'stdnum': 'python-stdnum',
                 'docx': 'python-docx', 'barcode': 'python-barcode', 'slugify': 'python-slugify',
                 'bs4': 'beautifulsoup4', 'sklearn': 'scikit-learn', 'git': 'gitpython'}


def normalized(name: str) -> str:
    return re.sub(r'[-_.]+', '-', name).lower()


def version(text: str):
    return tuple(int(part) for part in text.split('.')) if re.fullmatch(r'[0-9]+(\.[0-9]+)*', text) else None


def requirement(line: str):
    """(name as written, [(operator, version)], marker) of one requirement, or None."""
    text, _semicolon, marker = line.partition(';')
    match = REQUIREMENT.fullmatch(text.strip())
    if match is None:
        return None
    clauses = CLAUSE.findall(match.group(2))
    if match.group(2).strip() and not clauses:
        return None
    return match.group(1), clauses, marker.strip()


def applies(marker: str, python: str) -> bool:
    """Whether a marker holds for Python python on Linux (an unknown one holds)."""
    if not marker or ' or ' in marker:
        return True
    for atom in marker.split(' and '):
        match = MARKER.fullmatch(atom.strip().strip('()').strip())
        if match is None:
            continue
        variable, operator, value = match.groups()
        if variable.startswith('python'):
            held = compare(version(python), operator, value)
        else:
            current = 'linux' if variable == 'sys_platform' else 'Linux'
            held = {'==': current == value, '!=': current != value}.get(operator)
        if held is False:
            return False
    return True


def compare(found, operator: str, wanted: str):
    """Whether version tuple found satisfies `operator wanted`, None when it cannot be told."""
    if found is None:
        return None
    if wanted.endswith('.*'):
        prefix = version(wanted[:-2])
        if prefix is None or operator not in ('==', '!='):
            return None
        return (found[:len(prefix)] == prefix) == (operator == '==')
    target = version(wanted)
    if target is None:
        return None
    width = max(len(found), len(target))
    left, right = found + (0,) * (width - len(found)), target + (0,) * (width - len(target))
    if operator == '~=':
        return left >= right and found[:len(target) - 1] == target[:-1]
    return {'==': left == right, '===': left == right, '!=': left != right, '>=': left >= right,
            '<=': left <= right, '>': left > right, '<': left < right}[operator]


def lines(path: Path) -> list[str]:
    """The requirement lines of a file, comments and options left out ([] when it cannot be read)."""
    try:
        text = path.read_text(encoding='utf-8')
    except (OSError, UnicodeError):
        return []
    found = []
    for line in text.splitlines():
        line = re.sub(r'(^|\s)#.*$', '', line).strip()
        if line and not line.startswith('-') and '://' not in line:
            found.append(line)
    return found


def pins(requirement_lines: list[str], python: str, overrides: list[str] = ()) -> dict:
    """{normalized name: [(line, [(operator, version)])]} of the lines that apply to python; a name an
    override line names keeps only that line, as uv's --override does."""
    found = {}
    for replace, source in ((False, requirement_lines), (True, overrides)):
        replaced = set()
        for line in source:
            parsed = requirement(line)
            if parsed is None or not applies(parsed[2], python):
                continue
            key = normalized(parsed[0])
            if replace and key not in replaced:
                found[key], _ = [], replaced.add(key)
            found.setdefault(key, []).append((line.partition(';')[0].strip(), parsed[1]))
    return found


def pinned(found: dict, line: str) -> bool:
    """Whether the applying lines pin exactly line (`name==version`)."""
    parsed = requirement(line)
    return parsed is not None and any(
        clauses == parsed[1] for _line, clauses in found.get(normalized(parsed[0]), []))


def system_ldap():
    """The OpenLDAP version (text) of this machine when it is 2.6 or later without libldap_r, else None."""
    def output(command):
        program = shutil.which(command[0]) or next(
            (path for path in (f'/usr/sbin/{command[0]}', f'/sbin/{command[0]}') if Path(path).is_file()), None)
        if program is None:
            return ''
        try:
            result = subprocess.run([program, *command[1:]], capture_output=True, text=True, timeout=30,
                                    stdin=subprocess.DEVNULL, cwd='/')
        except (OSError, subprocess.SubprocessError):
            return ''
        return result.stdout if result.returncode == 0 else ''
    listed = output(['ldconfig', '-p'])
    if 'libldap_r' in listed:
        return None
    configured = output(['pkg-config', '--modversion', 'ldap']).strip()
    named = sorted(version(found) for found in re.findall(r'libldap-([0-9]+\.[0-9]+)\.so', listed))
    if configured and version(configured):
        found = configured
    elif named:
        found = '.'.join(map(str, named[-1]))
    elif re.search(r'libldap\.so', listed):
        found = '2.6'
    else:
        return None
    return found if version(found)[:2] >= (2, 6) else None


def module_requirements(roots: list[Path]) -> list[tuple[str, str]]:
    """(module, requirement) of every external_dependencies python entry of the modules directly in roots,
    in module order; a manifest that is not a literal dictionary is skipped."""
    found = []
    for root in roots:
        for manifest in sorted(root.glob('*/__manifest__.py')):
            try:
                document = ast.literal_eval(manifest.read_text(encoding='utf-8'))
                entries = document.get('external_dependencies', {}).get('python', [])
            except (OSError, UnicodeError, ValueError, SyntaxError, AttributeError, TypeError, MemoryError,
                    RecursionError):
                continue
            found += [(manifest.parent.name, entry.strip()) for entry in entries
                      if isinstance(entry, str) and entry.strip()]
    return found


def requirement_problems(entries, found: dict) -> list[dict]:
    """The missing or conflicting module requirements (module_requirements) against found (pins), one per
    distribution, in order: {id, module, entry, kind: missing|conflict, pin, proposal}."""
    problems, seen = [], set()
    for module, entry in entries:
        parsed = requirement(entry)
        if parsed is None or parsed[0].split('.')[0] in sys.stdlib_module_names:
            continue
        name = DISTRIBUTIONS.get(parsed[0].lower(), parsed[0])
        key = normalized(name)
        if key in seen:
            continue
        seen.add(key)
        listed = found.get(key)
        if not listed:
            problems.append({'id': f'requirement:{key}', 'module': module, 'entry': f'{name}{entry[len(parsed[0]):]}'
                             .partition(';')[0].strip(), 'kind': 'missing', 'pin': None, 'proposal': None})
            continue
        for line, clauses in listed:
            exact = [value for operator, value in clauses if operator in ('==', '===')]
            if len(exact) != 1 or not parsed[1]:
                continue
            if False in [compare(version(exact[0]), operator, value) for operator, value in parsed[1]]:
                lowest = next((value for operator, value in parsed[1] if operator in ('>=', '==', '~=')
                               and version(value)), None)
                proposal = f'{name}=={lowest}' if lowest else f'{name}{entry[len(parsed[0]):]}'.partition(';')[0]
                problems.append({'id': f'requirement:{key}', 'module': module, 'entry': entry, 'kind': 'conflict',
                                 'pin': line, 'proposal': proposal.strip()})
                break
    return problems
