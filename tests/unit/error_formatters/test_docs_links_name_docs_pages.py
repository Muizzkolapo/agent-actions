"""Every docs link the package prints is a constant of one module, and names a docs page."""

from __future__ import annotations

import ast
import importlib
import os
import re
import subprocess
from pathlib import Path
from typing import NamedTuple

import pytest
import yaml

_REPO = Path(__file__).resolve().parents[3]
_PACKAGE = _REPO / "agent_actions"
_DOCS = _REPO / "docs.agent-actions" / "docs"
_LINKS_MODULE = "agent_actions.logging.errors.docs_links"
_LINKS_FILE = _PACKAGE / "logging" / "errors" / "docs_links.py"
_LINKS_REL = "agent_actions/logging/errors/docs_links.py"
_SITE_ROOT = "https://docs.runagac.com/docs/"
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
_HEADING = re.compile(r"^ {0,3}#{1,6}\s+(.*?)\s*$")
_CLOSING_HASHES = re.compile(r"\s+#+$")
_COMMENT_ID = re.compile(r"\s*\{/\*\s*#([\w-]+)\s*\*/\}$")
_PLAIN_HEADING = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 &-]*$")
_NUMBER_PREFIX = re.compile(r"^\d+\s*[-_.]+\s*")


class _Heading(NamedTuple):
    raw: str
    explicit_id: str | None
    hidden: bool

    @property
    def base_slug(self) -> str:
        text = _CLOSING_HASHES.sub("", self.raw)
        return re.sub(r"[^\w\- ]", "", text.lower()).replace(" ", "-")


def _front_matter(page: Path) -> dict:
    text = page.read_text()
    if not text.startswith("---\n"):
        return {}
    return yaml.safe_load(text[4 : text.index("\n---", 4)]) or {}


def _rel(path: Path) -> str:
    return str(path.relative_to(_REPO))


def _pages(docs: Path) -> list[Path]:
    return sorted([*docs.rglob("*.md"), *docs.rglob("*.mdx")])


def _tree_problems(docs: Path) -> list[str]:
    """Pages whose URL the site derives by a rule this test does not model."""
    problems = []
    for page in _pages(docs):
        rel = page.relative_to(docs)
        stem = page.stem.lower()
        reasons = []
        if stem == "readme":
            reasons.append("a README page serves its folder")
        if stem == "index" and page.stem != "index":
            reasons.append(f"'{page.stem}' serves its folder like 'index'")
        if len(rel.parts) > 1 and stem == rel.parts[-2].lower():
            reasons.append("a page named like its folder serves the folder")
        if any(_NUMBER_PREFIX.match(part) for part in (*rel.parts[:-1], page.stem)):
            reasons.append("the site strips a number prefix from the URL")
        slug = _front_matter(page).get("slug")
        if slug is not None and not str(slug).startswith("/"):
            reasons.append(f"'slug: {slug}' is relative to the folder")
        problems += [
            f"UNSUPPORTED: {rel} in docs.agent-actions/docs: {reason}. Rename the file, or set "
            f"an absolute 'slug:' (one that starts with '/') in its front matter. Until then the "
            f"test cannot check the links in {_LINKS_REL}."
            for reason in reasons
        ]
    return problems


def _exists_as_written(docs: Path, rel: str) -> bool:
    """True when *rel* is a file under *docs* with every name in the same case."""
    folder = docs
    parts = rel.split("/")
    for part in parts[:-1]:
        if part not in os.listdir(folder) or not (folder / part).is_dir():
            return False
        folder = folder / part
    return parts[-1] in os.listdir(folder) and (folder / parts[-1]).is_file()


def _headings(text: str) -> list[_Heading]:
    lines = text.splitlines()
    front_end = lines.index("---", 1) if lines and lines[0] == "---" else -1
    headings = []
    fence: str | None = None
    comment_end: str | None = None
    for number, line in enumerate(lines):
        hidden = number <= front_end or comment_end is not None
        if comment_end is not None:
            if comment_end in line:
                comment_end = None
        elif not hidden:
            marker = _FENCE.match(line)
            if fence is None and marker:
                fence = marker.group(1)
                continue
            if fence is not None:
                closes = marker and marker.group(1)[0] == fence[0]
                if closes and len(marker.group(1)) >= len(fence) and not marker.group(2).strip():
                    fence = None
                continue
            for opener, closer in (("{/*", "*/}"), ("<!--", "-->")):
                start = line.find(opener)
                if start != -1 and closer not in line[start:]:
                    comment_end, hidden = closer, True
        heading = _HEADING.match(line)
        if heading is None:
            continue
        title = heading.group(1)
        explicit = _COMMENT_ID.search(title)
        if explicit:
            headings.append(_Heading(title[: explicit.start()], explicit.group(1), hidden))
        else:
            headings.append(_Heading(title, None, hidden))
    return headings


def _heading_problem(anchor: str, text: str, where: str, shown: str) -> str | None:
    fix = (
        f"Give the heading an explicit id, for example '## Heading {{/* #{anchor} */}}', "
        f"or change the constant in {_LINKS_REL}."
    )
    headings = _headings(text)
    named = [h for h in headings if anchor in (h.explicit_id, h.base_slug)]
    if any(h.hidden for h in named):
        return (
            f"UNSUPPORTED: {where}\n  The heading for '{anchor}' in {shown} is inside front "
            f"matter or a {{/* */}} or <!-- --> comment, so the site shows no such heading. {fix}"
        )
    if len(named) > 1:
        return (
            f"UNSUPPORTED: {where}\n  {len(named)} headings in {shown} share the id or base "
            f"slug '{anchor}'. {fix}"
        )
    if named and named[0].explicit_id == anchor:
        return None
    if not named or named[0].explicit_id is not None:
        return (
            f"HEADING MISSING: {where}\n  The page {shown} exists, but no heading in it has the "
            f"id '{anchor}'. Add an explicit id to the heading in that page, for example "
            f"'## Heading {{/* #{anchor} */}}', or change the constant in {_LINKS_REL}."
        )
    if not _PLAIN_HEADING.match(named[0].raw):
        return (
            f"UNSUPPORTED: {where}\n  The heading '{named[0].raw}' in {shown} holds markup or "
            f"punctuation, and the test does not derive its id. {fix}"
        )
    return None


def _problem(name: str, url: str, docs: Path) -> str | None:
    """Why *url* names no page or heading under *docs*, or None when it does."""
    where = f"{name} = {url}"
    if not url.startswith(_SITE_ROOT):
        return (
            f"NOT A DOCS PAGE: {where}\n  The link must start with {_SITE_ROOT}. "
            f"Change the constant in {_LINKS_REL}."
        )
    path, _, anchor = url[len(_SITE_ROOT) :].partition("#")
    route = path.strip("/")
    stem = f"{route}/" if route else ""
    serves_folder = route.rsplit("/", 1)[-1] in ("", "index")
    candidates = [] if serves_folder else [f"{route}.md", f"{route}.mdx"]
    candidates += [f"{stem}index.md", f"{stem}index.mdx"]
    found = [docs / c for c in candidates if _exists_as_written(docs, c)]
    label = _rel(docs) if docs.is_relative_to(_REPO) else str(docs)
    if not found:
        return (
            f"PAGE MISSING: {where}\n  No page serves /docs/{route}. Looked in {label} for: "
            + ", ".join(candidates)
            + f". Restore a page at that path, or change the constant in {_LINKS_REL}."
        )
    unsupported = f"UNSUPPORTED: {where}\n  "
    after = f" Change the constant in {_LINKS_REL}, or extend the test to model this."
    if len(found) > 1:
        files = ", ".join(str(p.relative_to(docs)) for p in found)
        return f"{unsupported}Two files serve the route: {files}.{after}"
    page = found[0]
    shown = str(page.relative_to(docs))
    if any(part.startswith("_") for part in page.relative_to(docs).parts):
        return f"{unsupported}{shown} has a '_' prefix, so the site does not publish it.{after}"
    meta = _front_matter(page)
    for key in ("id", "draft"):
        if key in meta:
            return f"{unsupported}{shown} sets '{key}:' in front matter.{after}"
    if "slug" in meta and str(meta["slug"]).strip("/") != route:
        return f"{unsupported}{shown} sets 'slug: {meta['slug']}', not its own path.{after}"
    for other in _pages(docs):
        slug = _front_matter(other).get("slug")
        if other != page and slug is not None and str(slug).strip("/") == route:
            claimer = other.relative_to(docs)
            return f"{unsupported}{claimer} claims the route by 'slug: {slug}'.{after}"
    return _heading_problem(anchor, page.read_text(), where, shown) if anchor else None


def _write(root: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return root


def _link_constants() -> dict[str, str]:
    """Every module-level string of the link module except the site root."""
    assert _LINKS_FILE.is_file(), (
        f"No docs-link module at {_LINKS_REL}. Every docs link must be a constant there."
    )
    module = importlib.import_module(_LINKS_MODULE)
    names = {
        n: v for n, v in vars(module).items() if not (n.startswith("__") and n.endswith("__"))
    }
    refused = sorted(n for n, v in names.items() if n.startswith("_") or not isinstance(v, str))
    assert refused == [], (
        f"{_LINKS_REL} may hold only public link strings; it also holds: {refused}"
    )
    assert names.pop("DOCS_BASE", None) == _SITE_ROOT, (
        f"{_LINKS_REL} must set DOCS_BASE = {_SITE_ROOT!r}"
    )
    assert names, f"{_LINKS_REL} holds no link constants"
    return names


def _tracked_package_files() -> list[Path]:
    try:
        listed = subprocess.run(
            ["git", "ls-files", "-z", "--", "agent_actions"], cwd=_REPO, capture_output=True
        )
    except FileNotFoundError:
        pytest.fail(
            "git is not on PATH. The test reads the tracked files of agent_actions/ from git."
        )
    if listed.returncode != 0:
        pytest.fail(f"git ls-files failed in {_REPO}: {listed.stderr.decode().strip()}")
    paths = {_REPO / name for name in listed.stdout.decode().split("\0") if name}
    # The link module is read even before git tracks it, so its own control holds.
    paths.add(_LINKS_FILE)
    return sorted(path for path in paths if path.is_file())


@pytest.mark.parametrize(
    "url",
    [
        _SITE_ROOT,
        _SITE_ROOT + "guides/troubleshooting",
        _SITE_ROOT + "reference/tools",
        _SITE_ROOT + "reference/tools/",
        _SITE_ROOT + "guides/troubleshooting#common-errors--fixes",
        _SITE_ROOT + "guides/troubleshooting#template-variable-error",
    ],
)
def test_a_known_page_or_heading_resolves(url):
    assert _problem("KNOWN", url, _DOCS) is None


@pytest.mark.parametrize(
    ("url", "verdict"),
    [
        ("https://docs.runagac.com/troubleshooting", "NOT A DOCS PAGE"),
        (_SITE_ROOT + "troubleshooting", "PAGE MISSING"),
        (_SITE_ROOT + "index", "PAGE MISSING"),
        (_SITE_ROOT + "guides/troubleshooting#no-such-heading", "HEADING MISSING"),
    ],
)
def test_an_unknown_page_or_heading_is_named_as_missing(url, verdict):
    problem = _problem("UNKNOWN", url, _DOCS)
    assert problem is not None and problem.startswith(verdict)


@pytest.mark.parametrize(
    ("files", "url"), [({"a.mdx": "# A\n"}, "a"), ({"a/index.mdx": "# A\n"}, "a")]
)
def test_an_mdx_page_or_mdx_folder_index_resolves(tmp_path, files, url):
    assert _problem("X", _SITE_ROOT + url, _write(tmp_path, files)) is None


def test_a_missing_heading_names_the_page_and_the_two_remedies():
    problem = _problem("X", _SITE_ROOT + "guides/troubleshooting#no-such-heading", _DOCS)
    assert problem == (
        "HEADING MISSING: X = https://docs.runagac.com/docs/guides/troubleshooting#no-such-heading\n"
        "  The page guides/troubleshooting.md exists, but no heading in it has the id "
        "'no-such-heading'. Add an explicit id to the heading in that page, for example "
        "'## Heading {/* #no-such-heading */}', or change the constant in "
        "agent_actions/logging/errors/docs_links.py."
    )


def test_a_missing_page_names_the_files_it_looked_for_and_the_two_remedies():
    problem = _problem("X", _SITE_ROOT + "troubleshooting", _DOCS)
    assert problem == (
        "PAGE MISSING: X = https://docs.runagac.com/docs/troubleshooting\n"
        "  No page serves /docs/troubleshooting. Looked in docs.agent-actions/docs for: "
        "troubleshooting.md, troubleshooting.mdx, troubleshooting/index.md, "
        "troubleshooting/index.mdx. Restore a page at that path, or change the constant in "
        "agent_actions/logging/errors/docs_links.py."
    )


@pytest.mark.parametrize(
    ("files", "url", "reason"),
    [
        ({"a.md": "---\nid: b\n---\n# A\n"}, "a", "sets 'id:'"),
        ({"a.md": "---\ndraft: true\n---\n# A\n"}, "a", "sets 'draft:'"),
        ({"a.md": "---\nslug: /other\n---\n# A\n"}, "a", "sets 'slug: /other'"),
        ({"a.md": "# A\n", "b.md": "---\nslug: /a\n---\n# B\n"}, "a", "claims the route"),
        ({"a.md": "# A\n", "a/index.md": "# A\n"}, "a", "Two files serve"),
        ({"_a.md": "# A\n"}, "_a", "'_' prefix"),
    ],
)
def test_a_route_the_mapping_does_not_model_fails_by_name(tmp_path, files, url, reason):
    problem = _problem("X", _SITE_ROOT + url, _write(tmp_path, files))
    assert problem is not None and problem.startswith("UNSUPPORTED") and reason in problem
    assert _LINKS_REL in problem


@pytest.mark.parametrize(
    ("rel", "text", "reason"),
    [
        ("guide/README.md", "# G\n", "README"),
        ("guide/readme.mdx", "# G\n", "README"),
        ("guide/guide.md", "# G\n", "named like its folder"),
        ("x/X.md", "# X\n", "named like its folder"),
        ("faq/Faq.md", "# F\n", "named like its folder"),
        ("faq/Index.md", "# F\n", "'Index' serves its folder"),
        ("01-intro.md", "# I\n", "number prefix"),
        ("2 _ setup.md", "# S\n", "number prefix"),
        ("03.guides/a.md", "# A\n", "number prefix"),
        ("a.md", "---\nslug: elsewhere\n---\n# A\n", "relative to the folder"),
    ],
)
def test_a_docs_tree_rule_the_test_does_not_model_fails_by_name(tmp_path, rel, text, reason):
    problems = _tree_problems(_write(tmp_path, {rel: text, "ok.md": "# Ok\n"}))
    assert len(problems) == 1
    assert problems[0].startswith(f"UNSUPPORTED: {rel} ") and reason in problems[0]
    assert "Rename the file, or set an absolute 'slug:'" in problems[0]
    assert _LINKS_REL in problems[0]


@pytest.mark.parametrize(
    ("docs", "url"),
    [
        (None, "Reference/Tools#tool-discovery"),
        (None, "guides/Troubleshooting"),
        ({"a/b.md": "# B\n"}, "A/b"),
        ({"a/b.md": "# B\n"}, "a/B"),
    ],
)
def test_a_route_in_another_case_is_a_missing_page(tmp_path, docs, url):
    root = _DOCS if docs is None else _write(tmp_path, docs)
    problem = _problem("X", _SITE_ROOT + url, root)
    assert problem is not None and problem.startswith("PAGE MISSING")


def test_the_shipped_docs_tree_uses_only_modelled_rules():
    assert _tree_problems(_DOCS) == []


@pytest.mark.parametrize(
    ("text", "anchor"),
    [
        ("## Tool Discovery\n", "tool-discovery"),
        ("## Common Errors & Fixes\n", "common-errors--fixes"),
        ("## Fancy `x` *heading* {/* #chosen */}\n", "chosen"),
    ],
)
def test_a_plain_or_explicitly_named_heading_resolves(text, anchor):
    assert _heading_problem(anchor, text, "X", "a.md") is None


@pytest.mark.parametrize(
    ("text", "anchor", "reason"),
    [
        ("## The `x` value\n", "the-x-value", "holds markup"),
        ("## A <b>bold</b> step\n", "a-bboldb-step", "holds markup"),
        ("## A &amp; B\n", "a-amp-b", "holds markup"),
        ("## See [docs](https://x)\n", "see-docshttpsx", "holds markup"),
        ("## An *important* step\n", "an-important-step", "holds markup"),
        ("## Snake_case name\n", "snake_case-name", "holds markup"),
        ("## Setup ##\n", "setup", "holds markup"),
        ("## Same\n## Same\n", "same", "2 headings"),
        ("## Same {/* #same */}\n## Same\n", "same", "2 headings"),
        ("{/*\n## Hidden\n*/}\n", "hidden", "comment"),
        ("<!--\n### Hidden\n-->\n", "hidden", "comment"),
        ("<!-- start\n## Hidden {/* #hid */}\nend -->\n", "hid", "comment"),
        ("---\n# Hidden {/* #hid */}\n---\n", "hid", "front matter"),
        ("---\n# Hidden\n---\n", "hidden", "front matter"),
    ],
)
def test_a_heading_whose_id_the_test_cannot_derive_fails_closed(text, anchor, reason):
    problem = _heading_problem(anchor, text, "X", "a.md")
    assert problem is not None and problem.startswith("UNSUPPORTED") and reason in problem
    assert "{/* #" + anchor + " */}" in problem and _LINKS_REL in problem


def test_a_heading_inside_a_code_fence_is_not_a_heading():
    text = "# Real\n````md\n```\n## Inside\n```\n````\n## After\n~~~\n# Tilde\n~~~\n"
    assert [h.raw for h in _headings(text)] == ["Real", "After"]
    assert _heading_problem("inside", text, "X", "a.md").startswith("HEADING MISSING")


def test_every_link_constant_names_an_existing_page_and_heading():
    constants = _link_constants()
    problems = _tree_problems(_DOCS)
    problems += [p for name, url in sorted(constants.items()) if (p := _problem(name, url, _DOCS))]
    assert problems == [], "Docs links that name no page or heading:\n" + "\n".join(problems)


def test_no_file_outside_the_link_module_names_the_docs_site():
    mentions = []
    for path in _tracked_package_files():
        if "__pycache__" in path.parts:
            continue
        mentions += [
            f"{_rel(path)}:{number}: {line.decode(errors='replace').strip()}"
            for number, line in enumerate(path.read_bytes().splitlines(), 1)
            if b"runagac" in line.lower() or b"DOCS_BASE" in line
        ]
    own = f"{_LINKS_REL}:"
    outside = [m for m in mentions if not m.startswith(own)]
    assert outside == [], (
        "Only the docs-link module may name the docs site. Make each link a constant in "
        f"{_LINKS_REL} and import it:\n" + "\n".join(outside)
    )
    inside = [m for m in mentions if m.startswith(own)]
    assert any("runagac" in m for m in inside) and any("DOCS_BASE" in m for m in inside)


def _docs_url_values(tree: ast.Module) -> list[ast.AST]:
    """Each value given to a docs_url: keyword, sixth UserError argument, or attribute write."""
    found: list[ast.AST] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            found += [kw.value for kw in node.keywords if kw.arg == "docs_url"]
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
            if name == "UserError" and len(node.args) > 5:
                found.append(node.args[5])
        elif isinstance(node, ast.Assign | ast.AnnAssign):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(t, ast.Attribute) and t.attr == "docs_url" for t in targets):
                found.append(node.value)
        elif isinstance(node, ast.AugAssign):
            if isinstance(node.target, ast.Attribute) and node.target.attr == "docs_url":
                found.append(node)
    return [value for value in found if value is not None]


def _call_site_problems(where: str, tree: ast.Module, links: set[str]) -> tuple[int, list[str]]:
    """How many docs_url values *tree* sets, and each one or each link use that is not bare."""
    bare: set[int] = set()
    problems = []
    values = _docs_url_values(tree)
    for value in values:
        if isinstance(value, ast.Name) and value.id in links:
            bare.add(id(value))
            continue
        problems.append(f"{where}:{value.lineno}: docs_url set to {ast.unparse(value)}")
        bare.update(id(child) for child in ast.walk(value))
    problems += [
        f"{where}:{node.lineno}: {node.id} is used outside a docs_url value"
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and node.id in links and id(node) not in bare
    ]
    return len(values), sorted(problems, key=lambda p: int(p.split(":")[1]))


def _absolute_module(source: Path, node: ast.ImportFrom) -> str:
    if not node.level:
        return node.module or ""
    package = list(source.relative_to(_REPO).with_suffix("").parts[:-1])
    base = package[: len(package) - (node.level - 1)]
    return ".".join(base + ([node.module] if node.module else []))


def _names_imported_from_the_link_module(source: Path, tree: ast.Module) -> set[str]:
    return {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and _absolute_module(source, node) == _LINKS_MODULE
        for alias in node.names
        if alias.asname is None
    }


_GOOD_CALLS = """
def f(a, b, c, d, e, err):
    UserError(category="x", docs_url=TROUBLESHOOTING)
    UserError(a, b, c, d, e, TROUBLESHOOTING)
    err.docs_url = TROUBLESHOOTING
"""


def test_a_bare_link_constant_as_a_docs_url_value_passes():
    seen, problems = _call_site_problems("m.py", ast.parse(_GOOD_CALLS), {"TROUBLESHOOTING"})
    assert (seen, problems) == (3, [])


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (
            'UserError(fix="See " + TROUBLESHOOTING + "#nope", docs_url=TROUBLESHOOTING)',
            ["m.py:1: TROUBLESHOOTING is used outside a docs_url value"],
        ),
        (
            'err.docs_url = TROUBLESHOOTING + "#nope"',
            ["m.py:1: docs_url set to TROUBLESHOOTING + '#nope'"],
        ),
        ('err.docs_url += "#nope"', ["m.py:1: docs_url set to err.docs_url += '#nope'"]),
        (
            'UserError(docs_url="https://example.com")',
            ["m.py:1: docs_url set to 'https://example.com'"],
        ),
        ("link = TROUBLESHOOTING", ["m.py:1: TROUBLESHOOTING is used outside a docs_url value"]),
    ],
)
def test_a_link_constant_used_other_than_bare_is_named(source, expected):
    assert _call_site_problems("m.py", ast.parse(source), {"TROUBLESHOOTING"})[1] == expected


def test_every_docs_url_argument_is_a_link_constant_as_it_stands():
    constants = set(_link_constants())
    bad = []
    seen = 0
    for source in _tracked_package_files():
        if source.suffix != ".py" or source == _LINKS_FILE:
            continue
        tree = ast.parse(source.read_text())
        links = constants & _names_imported_from_the_link_module(source, tree)
        count, problems = _call_site_problems(_rel(source), tree, links)
        seen += count
        bad += problems

    assert seen >= 12, seen
    assert bad == [], (
        "A docs_url must be one link constant, imported by its own name from "
        f"{_LINKS_MODULE}, with nothing added to it, and a link constant may appear only "
        "there:\n" + "\n".join(bad)
    )
