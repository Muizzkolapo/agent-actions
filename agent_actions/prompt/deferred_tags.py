"""Leave the Jinja tags of a workflow file the load cannot resolve for a later stage.

A workflow file is rendered through Jinja when it loads, before it is parsed, so it can
import macros, set variables and generate actions. A prompt written in the file is also a
template, but of a record: `source`, an upstream action and `i` do not exist at load.

`defer_unresolved_tags` passes every tag whose names nothing at load binds through the
render verbatim, between two marks. An action's `prompt:` drops the marks and keeps the
tag for the per-record render; any other value is rendered by `render_marked` once the
names exist (a version's, at expansion) or the load fails on the missing name.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import jinja2
from jinja2 import Environment, FileSystemLoader, nodes

OPEN = ""
CLOSE = ""
_MARKED = re.compile(f"{OPEN}(.*?){CLOSE}", re.S)
_LITERALS = "_agac_literal_text"

_RAW_BLOCK = re.compile(r"\{%[-+]?\s*raw\s*[-+]?%\}.*?\{%[-+]?\s*endraw\s*[-+]?%\}", re.S)
_STATEMENT = re.compile(r"\{%[-+]?\s*(\w*)(.*?)\s*[-+]?%\}\Z", re.S)

_CLOSERS = {
    "if": "endif",
    "for": "endfor",
    "macro": "endmacro",
    "call": "endcall",
    "filter": "endfilter",
    "with": "endwith",
    "block": "endblock",
    "autoescape": "endautoescape",
    "trans": "endtrans",
}
# Bound by Jinja itself inside the block that introduces them.
_ALWAYS_BOUND = frozenset({"self", "super"})


@dataclass
class _Tag:
    start: int
    end: int
    text: str
    keyword: str | None = None  # None for `{{ ... }}`
    rest: str = ""
    members: list[int] = field(default_factory=list)  # an opener's elif/else/closer


def defer_unresolved_tags(
    source: str, env: Environment, known: Iterable[str]
) -> tuple[str, set[str]]:
    """Mark every tag of *source* whose names the load cannot bind; also return those names.

    *known* is what the load binds besides the file's own `set`, `import`, loop and macro
    names: the environment's globals and the templates folder's exports. A file whose tags
    cannot be read is returned unchanged, so the render reports its syntax error.
    """
    tags = _scan(source)
    if tags is None or not _pair_blocks(tags):
        return source, set()
    deferred, unresolved = _Resolver(env, set(known) | _ALWAYS_BOUND).walk(tags)
    if not deferred:
        return source, unresolved
    pieces = []
    cursor = 0
    for index in sorted(deferred):
        tag = tags[index]
        pieces.append(source[cursor : tag.start])
        pieces.append(f"{OPEN}{{% raw %}}{tag.text}{{% endraw %}}{CLOSE}")
        cursor = tag.end
    pieces.append(source[cursor:])
    return "".join(pieces), unresolved


def is_marked(text: str) -> bool:
    return OPEN in text


def strip_marks(text: str) -> str:
    return text.replace(OPEN, "").replace(CLOSE, "")


def render_marked(env: Environment, text: str, context: Mapping[str, Any]) -> str:
    """Render the marked tags of *text* with *context*; the text around them stays as it is."""
    literals: list[str] = []
    parts: list[str] = []
    cursor = 0
    for match in _MARKED.finditer(text):
        literals.append(strip_marks(text[cursor : match.start()]))
        parts.append(f"{{{{ {_LITERALS}[{len(literals) - 1}] }}}}")
        parts.append(match.group(1))
        cursor = match.end()
    literals.append(strip_marks(text[cursor:]))
    parts.append(f"{{{{ {_LITERALS}[{len(literals) - 1}] }}}}")
    return env.from_string("".join(parts)).render({**context, _LITERALS: literals})


def template_folder_names(env: Environment, templates_folder: Path) -> set[str]:
    """Names the templates folder's files export to the workflow as globals.

    Read without running them, so a template can use another's macro whichever loads first.
    """
    names: set[str] = set()
    if not templates_folder.is_dir():
        return names
    for path in templates_folder.iterdir():
        if path.suffix not in (".j2", ".jinja2"):
            continue
        try:
            template = env.parse(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, jinja2.TemplateSyntaxError):
            continue  # loading it raises with the details
        for node in template.body:
            names |= _bound_by(node)
    return names


class DeferringFileSystemLoader(FileSystemLoader):
    """A templates folder whose files leave unresolved tags for later, as the workflow does."""

    def __init__(self, searchpath: str, known: set[str]):
        super().__init__(searchpath)
        self.known = known

    def get_source(
        self, environment: Environment, template: str
    ) -> tuple[str, str, Callable[[], bool]]:
        source, filename, uptodate = super().get_source(environment, template)
        known = self.known | set(environment.globals)
        return defer_unresolved_tags(source, environment, known)[0], filename, uptodate


def _bound_by(node: nodes.Node) -> set[str]:
    """The names a top-level statement binds for whoever imports the template."""
    if isinstance(node, nodes.Macro):
        return {node.name}
    if isinstance(node, nodes.Assign | nodes.AssignBlock):
        return {n.name for n in _name_nodes(node.target)}
    if isinstance(node, nodes.FromImport):
        return {alias if isinstance(alias, str) else alias[1] for alias in node.names}
    if isinstance(node, nodes.Import):
        return {node.target}
    return set()


def _scan(source: str) -> list[_Tag] | None:
    """Every `{{ }}` and `{% %}` tag outside comments and raw blocks, or None if one is open."""
    tags: list[_Tag] = []
    i = 0
    while True:
        start = source.find("{", i)
        if start == -1:
            return tags
        opener = source[start : start + 2]
        if opener == "{#":
            close = source.find("#}", start + 2)
            if close == -1:
                return None
            i = close + 2
            continue
        if opener == "{%":
            raw = _RAW_BLOCK.match(source, start)
            if raw:
                i = raw.end()
                continue
        if opener not in ("{{", "{%"):
            i = start + 1
            continue
        end = _tag_end(source, start + 2, "}}" if opener == "{{" else "%}")
        if end is None:
            return None
        text = source[start:end]
        tag = _Tag(start, end, text)
        if opener == "{%":
            match = _STATEMENT.match(text)
            if match is None:
                return None
            tag.keyword, tag.rest = match.group(1), match.group(2).strip()
        tags.append(tag)
        i = end


def _tag_end(source: str, i: int, closer: str) -> int | None:
    depth = 0
    quote = ""
    while i < len(source):
        char = source[i]
        if quote:
            if char == "\\":
                i += 2
                continue
            if char == quote:
                quote = ""
        elif char in "'\"":
            quote = char
        elif depth == 0 and source.startswith(closer, i):
            return i + 2
        elif char in "([{":
            depth += 1
        elif char in ")]}" and depth:
            depth -= 1
        i += 1
    return None


def _pair_blocks(tags: list[_Tag]) -> bool:
    """Give each block opener its elif/else/break/continue and closer; False if unbalanced."""
    stack: list[int] = []
    for index, tag in enumerate(tags):
        keyword = tag.keyword
        if keyword is None:
            continue
        if keyword in _CLOSERS or (keyword == "set" and "=" not in _top_level(tag.rest)):
            stack.append(index)
        elif keyword in ("elif", "else"):
            if not stack or tags[stack[-1]].keyword not in ("if", "for"):
                return False
            tags[stack[-1]].members.append(index)
        elif keyword in ("break", "continue"):
            loops = [i for i in stack if tags[i].keyword == "for"]
            if not loops:
                return False
            tags[loops[-1]].members.append(index)
        elif keyword.startswith("end"):
            if not stack:
                return False
            opener = tags[stack.pop()]
            if _CLOSERS.get(opener.keyword or "", "endset") != keyword:
                return False
            opener.members.append(index)
    return not stack


def _top_level(text: str) -> str:
    """*text* with its bracketed and quoted parts removed, to find a top-level `=`."""
    out = []
    depth = 0
    quote = ""
    for char in text:
        if quote:
            quote = "" if char == quote else quote
        elif char in "'\"":
            quote = char
        elif char in "([{":
            depth += 1
        elif char in ")]}":
            depth = max(depth - 1, 0)
        elif depth == 0:
            out.append(char)
    return "".join(out).replace("==", "").replace("!=", "").replace("<=", "").replace(">=", "")


class _Resolver:
    def __init__(self, env: Environment, known: set[str]):
        self.env = env
        self.known = known
        self.scopes: list[dict[str, bool]] = [{}]  # name -> bound only later (per record)
        self.deferred: set[int] = set()
        self.unresolved: set[str] = set()

    def walk(self, tags: list[_Tag]) -> tuple[set[int], set[str]]:
        frames: list[bool] = []  # per open block: did it push a scope
        for index, tag in enumerate(tags):
            keyword = tag.keyword
            if keyword is None:
                if self._later(self._names(tag.text)):
                    self.deferred.add(index)
            elif keyword in ("elif", "else", "break", "continue"):
                continue  # decided with the block they belong to
            elif keyword.startswith("end"):
                if frames.pop():
                    self.scopes.pop()
            elif keyword in _CLOSERS or tag.members:
                frames.append(self._open(index, tag, tags))
            else:
                self._statement(index, tag)
        return self.deferred, self.unresolved

    def _open(self, index: int, tag: _Tag, tags: list[_Tag]) -> bool:
        """Enter a block; True if it pushed a scope."""
        keyword = tag.keyword
        scope: dict[str, bool] = {}
        if keyword == "if":
            conditions = [tag] + [tags[i] for i in tag.members if tags[i].keyword == "elif"]
            names: set[str] = set()
            for condition in conditions:
                names |= self._names(f"{{% if {condition.rest} %}}{{% endif %}}")
            if self._later(names):
                self.deferred.update([index, *tag.members])
            return False
        node = self._parse(f"{tag.text}{{% end{keyword} %}}")
        if keyword == "for" and isinstance(node, nodes.For):
            targets = {n.name for n in _name_nodes(node.target)}
            names = _free(node.iter) | (_free(node.test) - targets if node.test else set())
            later = self._later(names)
            if later:
                self.deferred.update([index, *tag.members])
            scope = dict.fromkeys(targets | {"loop"}, later)
        elif keyword == "macro" and isinstance(node, nodes.Macro):
            self.scopes[-1][node.name] = False
            params = {arg.name for arg in node.args} | {"varargs", "kwargs", "caller"}
            scope = dict.fromkeys(params, False)
        elif keyword == "call" and isinstance(node, nodes.CallBlock):
            scope = dict.fromkeys({arg.name for arg in node.args}, False)
        elif keyword == "with" and isinstance(node, nodes.With):
            scope = dict.fromkeys({n.name for t in node.targets for n in _name_nodes(t)}, False)
        elif keyword == "set" and isinstance(node, nodes.AssignBlock):
            self.scopes[-1].update(dict.fromkeys(_bound_by(node), False))
            return False
        self.scopes.append(scope)
        return True

    def _statement(self, index: int, tag: _Tag) -> None:
        node = self._parse(tag.text)
        if isinstance(node, nodes.Assign):
            names = _free(node.node)
            if isinstance(node.target, nodes.NSRef):
                names.add(node.target.name)
            later = self._later(names)
            if later:
                self.deferred.add(index)
            for target in _name_nodes(node.target):
                self.scopes[-1][target.name] = later
        elif isinstance(node, nodes.Import | nodes.FromImport):
            self.scopes[-1].update(dict.fromkeys(_bound_by(node), False))

    def _parse(self, text: str) -> nodes.Node | None:
        try:
            body = self.env.parse(text).body
        except jinja2.TemplateSyntaxError:
            return None  # the render itself raises it
        return body[0] if body else None

    def _names(self, text: str) -> set[str]:
        try:
            return _free(self.env.parse(text))
        except jinja2.TemplateSyntaxError:
            return set()

    def _later(self, names: set[str]) -> bool:
        """True if a name is bound only later: by a deferred tag, or by nothing at load."""
        later = False
        for name in names:
            for scope in reversed(self.scopes):
                if name in scope:
                    later = later or scope[name]
                    break
            else:
                if name not in self.known:
                    self.unresolved.add(name)
                    later = True
        return later


def _name_nodes(node: nodes.Node) -> list[nodes.Name]:
    """Every Name in *node*, *node* itself included (`find_all` leaves it out)."""
    found = list(node.find_all(nodes.Name))
    return [node, *found] if isinstance(node, nodes.Name) else found


def _free(node: nodes.Node) -> set[str]:
    """Names *node* reads, leaving out the operand of an `is defined` test."""
    tested = {
        id(test.node)
        for test in node.find_all(nodes.Test)
        if test.name in ("defined", "undefined") and isinstance(test.node, nodes.Name)
    }
    return {
        name.name for name in _name_nodes(node) if name.ctx == "load" and id(name) not in tested
    }
