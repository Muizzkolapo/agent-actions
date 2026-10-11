"""A manifest's Project Surface cannot name a symbol that does not exist.

Nothing compared the manifests to the code they describe, and prose drifts one way: a symbol
is renamed, the table keeps the old name, and the row still reads as current. Three findings
in one review round were this shape — a documented absolute the code had withdrawn, a diagram
describing a removed branch, a key count that was wrong when written (#1201).

Resolution is by AST, not by substring. A first version of this test asked whether the leaf
name appeared anywhere in the subtree's concatenated source, and a blind review measured what
that bought: of eight stale rows it caught two, every wrong-class mutation passed (115/115), a
name present only in a comment passed, and `ResponseBuilder.build` passed because "build" is a
substring of "ResponseBuilder". It detected one thing — a string vanishing from a package
entirely. So `Class.attr` now requires the class to exist *and* define the attribute.

Scoped to these tables deliberately. They are structured, column one is a symbol, and
existence is decidable. Prose in general is not.
"""

import ast
import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3] / "agent_actions"
_SECTION = re.compile(r"## Project Surface(.*?)(?=\n## |\Z)", re.S)
_SYMBOL = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$")
# A cell naming a file is documentation of a file, not of a symbol.
_FILE_SUFFIXES = (".md", ".py", ".yml", ".yaml", ".json", ".toml", ".txt", ".sh", ".db")


def _manifests() -> list[Path]:
    return sorted(_ROOT.rglob("_MANIFEST.md"))


def _symbols(manifest: Path) -> list[str]:
    section = _SECTION.search(manifest.read_text(encoding="utf-8"))
    if not section:
        return []
    out = []
    for line in section.group(1).splitlines():
        cells = [c.strip() for c in line.split("|")[1:-1]]
        if len(cells) < 2 or cells[0] in ("Symbol", "") or set(cells[0]) <= set("-: "):
            continue
        # Backticks first: a cell reads `Class.method()`, so stripping the parenthetical
        # before the quoting leaves a trailing backtick and the symbol never matches.
        bare = cells[0].strip().strip("`").strip()
        symbol = re.sub(r"\(.*?\)\s*$", "", bare).strip()
        if symbol.endswith(_FILE_SUFFIXES) or not _SYMBOL.match(symbol):
            continue
        out.append(symbol)
    return out


def _definitions(
    manifest: Path,
) -> tuple[dict[str, set[str]], dict[str, set[str]], set[str], set[str]]:
    """(class -> own names, class -> base names, module-level names, module basenames)."""
    classes: dict[str, set[str]] = {}
    bases: dict[str, set[str]] = {}
    module_level: set[str] = set()
    modules: set[str] = set()
    for path in manifest.parent.rglob("*.py"):
        modules.add(path.stem)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                bases.setdefault(node.name, set()).update(
                    b.id for b in node.bases if isinstance(b, ast.Name)
                )
                owned = classes.setdefault(node.name, set())
                for body in node.body:
                    if isinstance(body, ast.FunctionDef | ast.AsyncFunctionDef):
                        owned.add(body.name)
                    elif isinstance(body, ast.Assign):
                        owned.update(t.id for t in body.targets if isinstance(t, ast.Name))
                    elif isinstance(body, ast.AnnAssign) and isinstance(body.target, ast.Name):
                        owned.add(body.target.id)
            elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                module_level.add(node.name)
            elif isinstance(node, ast.Assign):
                module_level.update(t.id for t in node.targets if isinstance(t, ast.Name))
    return classes, bases, module_level, modules


def _defines(name: str, attr: str, classes, bases, seen=None) -> bool:
    """Whether *name* or one of its bases in this package defines *attr*."""
    seen = seen or set()
    if name in seen:
        return False
    seen.add(name)
    if attr in classes.get(name, ()):  # noqa: SIM118 - set membership on a .get default
        return True
    return any(_defines(b, attr, classes, bases, seen) for b in bases.get(name, ()))


def _unresolved(symbol: str, classes, bases, module_level, modules) -> str | None:
    """Why *symbol* does not resolve in this subtree, or None."""
    if "." not in symbol:
        if symbol in classes or symbol in module_level or symbol in modules:
            return None
        return "not defined in this package"
    owner, _, attr = symbol.rpartition(".")
    if owner in classes:
        # Up the real base chain: an inherited member is a genuine surface, but "some other
        # class in the package happens to define this name" is not inheritance.
        if _defines(owner, attr, classes, bases):
            return None
        return f"class '{owner}' exists but defines no '{attr}'"
    if owner in modules:
        return (
            None
            if (attr in module_level or attr in classes)
            else f"module '{owner}' defines no '{attr}'"
        )
    return f"no class or module '{owner}' in this package"


@pytest.mark.parametrize("manifest", _manifests(), ids=lambda p: str(p.relative_to(_ROOT)))
def test_every_documented_symbol_resolves(manifest: Path):
    classes, bases, module_level, modules = _definitions(manifest)
    broken = [
        f"{symbol}: {why}"
        for symbol in _symbols(manifest)
        if (why := _unresolved(symbol, classes, bases, module_level, modules))
    ]

    assert broken == [], (
        f"{manifest.relative_to(_ROOT)} documents symbols that do not resolve: {broken}"
    )


def test_the_resolver_rejects_a_symbol_that_does_not_exist():
    """Guards the resolver, not the manifests: a check that accepts everything would make
    every case above pass while asserting nothing. The first version of this test did exactly
    that for six real stale rows."""
    classes = {"Real": {"method"}, "Child": set(), "Unrelated": {"method"}}
    bases = {"Child": {"Real"}}

    assert _unresolved("Real.method", classes, bases, set(), set()) is None
    assert _unresolved("Real.absent", classes, bases, set(), set()) is not None
    assert _unresolved("Absent.method", classes, bases, set(), set()) is not None
    assert _unresolved("loose_name", classes, bases, set(), set()) is not None
    assert _unresolved("loose_name", classes, bases, {"loose_name"}, set()) is None
    # Inherited counts; a same-named member on an unrelated class does not.
    assert _unresolved("Child.method", classes, bases, set(), set()) is None
    assert _unresolved("Child.absent", classes, bases, set(), set()) is not None


def test_the_parser_reads_every_manifest_that_has_the_section():
    """A regex that stopped matching would make the suite pass in silence. Asserts both the
    corpus size and that the sections found still carry symbols."""
    manifests = _manifests()
    with_section = [m for m in manifests if _SECTION.search(m.read_text(encoding="utf-8"))]
    total = sum(len(_symbols(m)) for m in manifests)

    assert len(manifests) > 50, len(manifests)
    assert len(with_section) > 15, f"only {len(with_section)} manifests have a Project Surface"
    assert total > 150, f"only {total} symbols parsed — has the table format changed?"
