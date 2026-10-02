"""A manifest's Project Surface cannot name a symbol that does not exist.

Nothing compared the manifests to the code they describe, and prose drifts in one direction:
a symbol is renamed, the table keeps the old name, and the row still reads as current. Three
findings in one review round were this shape — a documented absolute the code had withdrawn,
an architecture diagram describing a removed branch, a key count that was wrong when written
(#1201).

Scoped deliberately to the Project Surface tables rather than to prose in general. Those
tables are structured, their first column is a symbol, and "does this symbol exist" is
decidable. A general prose linter is not, and would drown the signal: 433 backticked dotted
paths across the markdown are mostly filenames and config examples.

The check is per subtree, not per directory: a package manifest documents symbols that live
in its sub-packages.
"""

import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3] / "agent_actions"
_SECTION = re.compile(r"## Project Surface(.*?)(?=\n## |\Z)", re.S)
_SYMBOL = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*$")


def _rows(manifest: Path) -> list[tuple[str, str]]:
    """(symbol, file) per Project Surface row, bare names only."""
    section = _SECTION.search(manifest.read_text(encoding="utf-8"))
    if not section:
        return []
    out = []
    for line in section.group(1).splitlines():
        cells = [c.strip().strip("`") for c in line.split("|")[1:-1]]
        if len(cells) < 2 or cells[0] in ("Symbol", "") or set(cells[0]) <= set("-: "):
            continue
        symbol = re.sub(r"\(.*\)$", "", cells[0]).strip()
        if _SYMBOL.match(symbol):
            out.append((symbol, cells[1]))
    return out


def _manifests() -> list[Path]:
    return sorted(_ROOT.rglob("_MANIFEST.md"))


def _subtree_source(manifest: Path) -> str:
    return "\n".join(
        p.read_text(encoding="utf-8", errors="ignore") for p in manifest.parent.rglob("*.py")
    )


@pytest.mark.parametrize("manifest", _manifests(), ids=lambda p: str(p.relative_to(_ROOT)))
def test_every_documented_symbol_exists_in_its_subtree(manifest: Path):
    """The leaf name must appear in the package the manifest describes.

    Leaf, not the dotted path: a row may write `Class.method` while the source defines the
    method inside the class body, so the full string never appears verbatim. That is weaker
    than resolving the attribute, and still catches a symbol that is simply gone — which is
    the drift that happens.
    """
    source = _subtree_source(manifest)
    missing = [
        f"{symbol} (row names {file_path})"
        for symbol, file_path in _rows(manifest)
        if symbol.split(".")[-1] not in source
    ]

    assert missing == [], (
        f"{manifest.relative_to(_ROOT)} documents symbols absent from its subtree: {missing}"
    )


def test_the_check_reads_a_meaningful_number_of_rows():
    """Guards the parser: a regex that silently matched nothing would make every test above
    pass and assert nothing. If the table format changes, this fails rather than going quiet."""
    total = sum(len(_rows(m)) for m in _manifests())

    assert len(_manifests()) > 50, len(_manifests())
    assert total > 150, f"only {total} Project Surface rows parsed — has the format changed?"
