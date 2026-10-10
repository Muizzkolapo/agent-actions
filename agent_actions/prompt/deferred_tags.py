"""Leave the Jinja tags of a workflow file the load cannot resolve for a later stage.

A workflow file is rendered through Jinja when it loads, before it is parsed, so it can
import macros, set variables and generate actions. A prompt written in the file is also a
template, but of a record: `source`, an upstream action and `i` do not exist at load.

`defer_unresolved_tags` passes every tag whose names nothing at load binds through the
render verbatim, between two marks. An action's `prompt:` drops the marks and keeps the
tag for the per-record render; any other value is rendered by `render_marked` once the
names exist (a version's, at expansion) or the load fails on the missing name.

A `{% set %}` block or macro whose body holds such a tag has that tag's text for its value
at load. Output whole, it carries the tag on; a tag that tests or filters it waits for
the record with its definition, or fails the load if the definition is in templates/.
"""

from __future__ import annotations

import functools
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
# Joins an included template's name to the names its includer binds at load there.
_CONTEXT = "\ue002"
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
# Filters that hand a value's text on with any tag in it still a tag.
_PASS_FILTERS = frozenset({"indent", "safe", "string", "trim", "dedent"})

_LOAD = "load"
_LATER = "later"  # bound by a tag left for later
_MODULE = "module"  # `{% import 'x' as name %}`
# What waits for the record on the next pass: ("name", scope owner, name) or ("block", index).
_Key = tuple[Any, ...]


@dataclass(frozen=True)
class _Carry:
    """A value the load computes whose text holds a tag left for later.

    Output whole, it carries that tag into the output. Tested or filtered at load, it would
    read the tag's text instead of the record's value, so it waits for the record: by *key*
    when the file defines it, while a value from templates/ (no key) cannot wait.
    """

    key: _Key | None
    name: str


_State = str | _Carry


@dataclass
class _Scope:
    owner: int  # the tag that opened it, or -1 for the file
    names: dict[str, _State] = field(default_factory=dict)


@dataclass
class _Frame:
    """An open block."""

    index: int
    captures: bool  # what its body outputs becomes a value: set block, macro, call, filter
    node: nodes.Node | None = None
    pushed: bool = False
    deferred: bool = False
    carries: bool = False  # what it captures holds a tag left for later
    scope: _Scope | None = None  # where a set block or macro binds
    names: set[str] = field(default_factory=set)


@dataclass
class _Tag:
    start: int
    end: int
    text: str
    keyword: str | None = None  # None for `{{ ... }}`
    rest: str = ""
    members: list[int] = field(default_factory=list)  # an opener's elif/else/closer


@dataclass
class Deferral:
    """What `defer_unresolved_tags` left for a later stage in one source."""

    source: str  # with every tag left for later marked
    unresolved: set[str] = field(default_factory=set)  # names nothing at load binds
    per_record: set[str] = field(default_factory=set)  # names left for later wherever used
    carrying: set[str] = field(default_factory=set)  # top-level names holding a later tag
    tested: set[str] = field(default_factory=set)  # such names from elsewhere tested at load
    leaves_tags: bool = False  # what it outputs can hold a tag left for later


# Whether a template, included where the given names are bound at load, leaves a tag.
IncludeLeavesTags = Callable[[str, frozenset[str]], bool]


def defer_unresolved_tags(
    source: str,
    env: Environment,
    known: Iterable[str],
    carrying: Iterable[str] = (),
    inherited: Iterable[str] = (),
    include: IncludeLeavesTags | None = None,
    in_macros: Iterable[str] = (),
) -> Deferral:
    """Mark every tag of *source* whose names the load cannot bind.

    *known* is what the load binds besides the file's own `set`, `import`, loop and macro
    names: the environment's globals and the templates folder's exports. *carrying* are
    the exports whose value holds a tag left for later. *inherited* are the names an
    includer binds at load, when *source* is an included template. *in_macros* are bound
    only by the time a macro runs: the exports of templates/ files not loaded yet. A file
    whose tags cannot be read is returned unchanged, so the render reports its syntax error.

    An `{% include %}` with context names its template together with the names bound at
    load where it stands, which `DeferringFileSystemLoader` reads them from.
    """
    tags = _scan(source)
    if tags is None or not _pair_blocks(tags):
        return Deferral(source)
    inherited = frozenset(inherited)
    known = set(known) | inherited | _ALWAYS_BOUND
    # A name a deferred tag assigns, or a load-time value a tag tests although it holds a
    # tag left for later, waits for the record in its scope: its definition, every other
    # assignment and every read, or the load would freeze it. Repeat until nothing new waits.
    forced: frozenset[_Key] = frozenset()
    while True:
        resolver = _Resolver(
            env, known, forced, frozenset(carrying), inherited, include, frozenset(in_macros)
        )
        resolver.walk(tags)
        if resolver.force <= forced:
            break
        forced |= resolver.force
    pieces = []
    cursor = 0
    for index in sorted(resolver.deferred | set(resolver.includes)):
        tag = tags[index]
        pieces.append(source[cursor : tag.start])
        if index in resolver.deferred:
            pieces.append(f"{OPEN}{{% raw %}}{tag.text}{{% endraw %}}{CLOSE}")
        else:
            pieces.append(resolver.includes[index])
        cursor = tag.end
    pieces.append(source[cursor:])
    return Deferral(
        "".join(pieces),
        unresolved=resolver.unresolved,
        per_record={key[2] for key in forced if key[0] == "name"},
        carrying={
            name for name, state in resolver.scopes[0].names.items() if isinstance(state, _Carry)
        },
        tested=resolver.tested,
        leaves_tags=bool(resolver.deferred) or resolver.output_carries,
    )


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


@dataclass
class TemplateExports:
    """What the templates folder's files export to the workflow as globals."""

    names: set[str] = field(default_factory=set)
    carrying: set[str] = field(default_factory=set)  # those whose value holds a later tag
    tested: set[str] = field(default_factory=set)  # carrying ones a folder file tests at load


def template_folder_exports(env: Environment, templates_folder: Path) -> TemplateExports:
    """Read the folder's exports without running them.

    So a template can use another's macro whichever loads first.
    """
    exports = TemplateExports()
    if not templates_folder.is_dir():
        return exports
    sources = []
    for path in sorted(templates_folder.iterdir()):
        if path.suffix not in (".j2", ".jinja2"):
            continue
        try:
            source = path.read_text(encoding="utf-8")
            template = env.parse(source)
        except (OSError, UnicodeDecodeError, jinja2.TemplateSyntaxError):
            continue  # loading it raises with the details
        for node in template.body:
            exports.names |= _bound_by(node)
        sources.append(source)
    known = exports.names | set(env.globals)
    while True:
        deferrals = [defer_unresolved_tags(s, env, known, exports.carrying) for s in sources]
        carrying = set().union(*(d.carrying for d in deferrals))
        if carrying <= exports.carrying:
            exports.tested = set().union(*(d.tested for d in deferrals))
            return exports
        exports.carrying |= carrying


class DeferringFileSystemLoader(FileSystemLoader):
    """A templates folder whose files leave unresolved tags for later, as the workflow does.

    An included file also renders at load the names its includer binds there, which the
    include passes in the template name, so each place it is included has its own copy.
    """

    def __init__(self, searchpath: str):
        super().__init__(searchpath)
        self.exports = TemplateExports()
        self._reading: set[str] = set()

    def get_source(
        self, environment: Environment, template: str
    ) -> tuple[str, str, Callable[[], bool]]:
        name, _, context = template.partition(_CONTEXT)
        inherited = frozenset(context.split(",")) if context else frozenset()
        source, filename, uptodate = super().get_source(environment, name)
        return self._defer(environment, source, inherited).source, filename, uptodate

    def leaves_tags(self, environment: Environment, template: str, names: frozenset[str]) -> bool:
        """Whether *template*, included where *names* are bound at load, leaves a tag."""
        if template in self._reading:
            return False  # it includes itself; rendering it raises
        self._reading.add(template)
        try:
            source = super().get_source(environment, template)[0]
            return self._defer(environment, source, names).leaves_tags
        except jinja2.TemplateNotFound:
            return False  # including it raises
        finally:
            self._reading.discard(template)

    def _defer(self, environment: Environment, source: str, inherited: frozenset[str]) -> Deferral:
        # Loading the folder makes each file's exports globals in turn, so a file's top
        # level can count only on those already loaded, and its macros on all of them.
        return defer_unresolved_tags(
            source,
            environment,
            set(environment.globals),
            self.exports.carrying,
            inherited,
            functools.partial(self.leaves_tags, environment),
            in_macros=self.exports.names,
        )


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
    def __init__(
        self,
        env: Environment,
        known: set[str],
        forced: frozenset[_Key],
        carrying: frozenset[str],
        inherited: frozenset[str],
        include: IncludeLeavesTags | None,
        in_macros: frozenset[str],
    ):
        self.env = env
        self.known = known
        self.forced = forced  # left for later on an earlier pass
        self.carrying = carrying  # exports of templates/ whose value holds a later tag
        self.inherited = inherited
        self.include = include
        self.in_macros = in_macros  # bound by the time a macro runs
        self.scopes: list[_Scope] = [_Scope(-1)]
        self.frames: list[_Frame] = []  # open blocks
        self.deferred: set[int] = set()
        self.unresolved: set[str] = set()
        self.force: set[_Key] = set()  # to leave for later on the next pass
        self.tested: set[str] = set()
        self.includes: dict[int, str] = {}  # include tag -> the same, naming its context
        self.output_carries = False  # what the source outputs holds a tag left for later

    def walk(self, tags: list[_Tag]) -> None:
        for index, tag in enumerate(tags):
            keyword = tag.keyword
            if keyword is None:
                self._output(index, tag)
            elif keyword in ("elif", "else", "break", "continue"):
                continue  # decided with the block they belong to
            elif keyword.startswith("end"):
                self._close()
            elif keyword in _CLOSERS or tag.members:
                self._open(index, tag, tags)
            else:
                self._statement(index, tag)

    def _output(self, index: int, tag: _Tag) -> None:
        node = self._parse(tag.text)
        if not isinstance(node, nodes.Output):
            return  # the render itself raises on it
        if self._later(_free(node)):
            self._defer([index])
            return
        head = _pass_through_head(node.nodes[0]) if len(node.nodes) == 1 else None
        carry = self._carry_of(head)
        self._test(node, skip=head if carry else None)
        if carry is not None:
            self._carries()

    def _open(self, index: int, tag: _Tag, tags: list[_Tag]) -> None:
        """Enter a block, deciding whether it is left for later."""
        keyword = tag.keyword
        later = ("block", index) in self.forced
        frame = _Frame(index, captures=keyword in ("set", "macro", "call", "filter"))
        body: set[str] = set()  # names its body's scope binds
        reads: list[nodes.Node] = []  # what it reads on entry
        if keyword == "if":
            conditions = [tag] + [tags[i] for i in tag.members if tags[i].keyword == "elif"]
            for condition in conditions:
                node = self._parse(f"{{% if {condition.rest} %}}{{% endif %}}")
                if isinstance(node, nodes.If):
                    reads.append(node.test)
            later = self._later(_free_all(reads)) or later
        else:
            node = self._parse(f"{tag.text}{{% end{keyword} %}}")
            frame.node = node
            if isinstance(node, nodes.For):
                targets = {n.name for n in _name_nodes(node.target)}
                names = _free(node.iter) | (_free(node.test) - targets if node.test else set())
                reads = [node.iter]
                later = self._later(names) or later
                body = targets | {"loop"}
            elif isinstance(node, nodes.AssignBlock):
                frame.scope, frame.names = self._binding(node.target)
                keys = {("name", frame.scope.owner, name) for name in frame.names}
                reads = [node.filter] if node.filter else []
                later = (
                    self._later(_free_all(reads))
                    or self._within_deferred()
                    or bool(keys & self.forced)
                    or later
                )
                if later:
                    self.force |= keys
            elif isinstance(node, nodes.Macro):
                frame.scope, frame.names = self.scopes[-1], {node.name}
                key = ("name", frame.scope.owner, node.name)
                later = (
                    self._later(_free_all(node.defaults))
                    or self._within_deferred()
                    or key in self.forced
                    or later
                )
                if later:
                    self.force.add(key)
                # Bound on entry, so its body can call it.
                frame.scope.names[node.name] = _LATER if later else _LOAD
                body = {arg.name for arg in node.args} | {"varargs", "kwargs", "caller"}
            elif isinstance(node, nodes.CallBlock):
                reads = [node.call]
                later = self._later(_free(node.call)) or later
                body = {arg.name for arg in node.args}
                if not later:
                    head = _pass_through_head(node.call)
                    if self._carry_of(head) is not None:
                        self._test(node.call, skip=head)
                        self._carries()
                        reads = []
            elif isinstance(node, nodes.FilterBlock):
                reads = [node.filter]
                later = self._later(_free(node.filter)) or later
            elif isinstance(node, nodes.With):
                reads = list(node.values)
                later = self._later(_free_all(reads)) or later
                body = {n.name for t in node.targets for n in _name_nodes(t)}
        if later:
            self._defer([index, *tag.members])
        else:
            for read in reads:
                self._test(read)
        frame.deferred = later
        if keyword != "if":  # the one block Jinja gives no scope of its own
            self.scopes.append(_Scope(index, dict.fromkeys(body, _LATER if later else _LOAD)))
            frame.pushed = True
        self.frames.append(frame)

    def _close(self) -> None:
        frame = self.frames.pop()
        if frame.pushed:
            self.scopes.pop()
        node = frame.node
        if isinstance(node, nodes.AssignBlock) and frame.scope is not None:
            for name in frame.names:
                key = ("name", frame.scope.owner, name)
                state: _State = _LOAD
                if frame.deferred:
                    state = _LATER
                elif frame.carries:
                    if node.filter is not None and not _passes(node.filter):
                        self.force.add(key)
                    state = _Carry(key, name)
                frame.scope.names[name] = state
        elif frame.deferred or not frame.carries:
            return
        elif isinstance(node, nodes.Macro) and frame.scope is not None:
            frame.scope.names[node.name] = _Carry(("name", frame.scope.owner, node.name), node.name)
        elif isinstance(node, nodes.FilterBlock):
            if not _passes(node.filter):
                self.force.add(("block", frame.index))
            self._carries()
        elif isinstance(node, nodes.CallBlock):
            self._carries()

    def _statement(self, index: int, tag: _Tag) -> None:
        node = self._parse(tag.text)
        if isinstance(node, nodes.Assign):
            self._assign(index, node)
        elif isinstance(node, nodes.Import):
            self.scopes[-1].names[node.target] = _MODULE
        elif isinstance(node, nodes.FromImport):
            for alias in node.names:
                name, bound = (alias, alias) if isinstance(alias, str) else alias
                state: _State = _Carry(None, name) if name in self.carrying else _LOAD
                self.scopes[-1].names[bound] = state
        elif isinstance(node, nodes.Include):
            self._include(index, tag, node)

    def _include(self, index: int, tag: _Tag, node: nodes.Include) -> None:
        """An included template renders at load what is bound here at load; the tags it
        leaves for later land here."""
        if self._later(_free(node.template)):
            self._defer([index])
            return
        templates = _template_names(node.template)
        if templates is None:
            return  # named by a variable: it sees the globals and the folder's exports
        site: frozenset[str] = frozenset()
        if node.with_context:
            names = self.inherited.union(*(scope.names for scope in self.scopes))
            site = frozenset(n for n in names if self._state(n) in (_LOAD, _MODULE))
        for template in templates:
            if self.include is not None and self.include(template, site):
                self._carries()
        if site:
            context = _CONTEXT + ",".join(sorted(site))
            self.includes[index] = _include_tag(tag.text, node, [t + context for t in templates])

    def _assign(self, index: int, node: nodes.Assign) -> None:
        """Bind a `set`; one inside a deferred block, of a value only a record has, or to a
        name such an assignment also takes in its scope, is itself left for later."""
        scope, names = self._binding(node.target)
        reads = _free(node.node)
        if isinstance(node.target, nodes.NSRef):
            reads.add(node.target.name)
        keys = {("name", scope.owner, name) for name in names}
        state: _State = _LOAD
        if self._later(reads) or self._within_deferred() or keys & self.forced:
            self._defer([index])
            self.force |= keys
            state = _LATER
        else:
            # `{% set b = a %}` of a value holding a later tag holds it too, waiting with a.
            head = _pass_through_head(node.node) if isinstance(node.target, nodes.Name) else None
            carry = self._carry_of(head)
            self._test(node.node, skip=head if carry else None)
            if carry is not None:
                state = carry
        for name in names:
            scope.names[name] = state

    def _binding(self, target: nodes.Node) -> tuple[_Scope, set[str]]:
        """The scope a `set` binds in and the names it binds: Jinja binds a name in the
        innermost scope, and a namespace attribute in the namespace's scope."""
        if isinstance(target, nodes.NSRef):
            for scope in reversed(self.scopes):
                if target.name in scope.names:
                    return scope, {target.name}
            return self.scopes[-1], {target.name}
        return self.scopes[-1], {n.name for n in _name_nodes(target)}

    def _defer(self, indices: list[int]) -> None:
        self.deferred.update(indices)
        self._carries()

    def _carries(self) -> None:
        """What the innermost capturing block collects now holds a tag left for later."""
        for frame in reversed(self.frames):
            if frame.captures:
                frame.carries = True
                return
        self.output_carries = True

    def _within_deferred(self) -> bool:
        return any(frame.deferred for frame in self.frames)

    def _test(self, node: nodes.Node, skip: nodes.Node | None = None) -> None:
        """Leave for later each value *node* reads, other than to output it whole, whose
        text holds a tag left for later; one from outside the file cannot wait."""
        for ref in _references(node):
            carry = None if ref is skip else self._carry_of(ref)
            if carry is None:
                continue
            if carry.key is None:
                self.tested.add(carry.name)
            else:
                self.force.add(carry.key)

    def _carry_of(self, expr: nodes.Node | None) -> _Carry | None:
        if isinstance(expr, nodes.Name):
            state = self._state(expr.name)
            return state if isinstance(state, _Carry) else None
        if isinstance(expr, nodes.Getattr) and isinstance(expr.node, nodes.Name):
            if self._state(expr.node.name) == _MODULE and expr.attr in self.carrying:
                return _Carry(None, f"{expr.node.name}.{expr.attr}")
        return None

    def _state(self, name: str) -> _State | None:
        for scope in reversed(self.scopes):
            if name in scope.names:
                return scope.names[name]
        in_macro = any(isinstance(frame.node, nodes.Macro) for frame in self.frames)
        if name in self.known or (in_macro and name in self.in_macros):
            return _Carry(None, name) if name in self.carrying else _LOAD
        return None

    def _parse(self, text: str) -> nodes.Node | None:
        try:
            body = self.env.parse(text).body
        except jinja2.TemplateSyntaxError:
            return None  # the render itself raises it
        return body[0] if body else None

    def _later(self, names: set[str]) -> bool:
        """True if a name is bound only later: by a deferred tag, or by nothing at load."""
        later = False
        for name in names:
            state = self._state(name)
            if state is None:
                self.unresolved.add(name)
                later = True
            elif state == _LATER:
                later = True
        return later


def _pass_through_head(expr: nodes.Node | None) -> nodes.Node | None:
    """The name *expr* outputs whole, called or not, through filters that keep a tag a tag."""
    while isinstance(expr, nodes.Filter) and expr.name in _PASS_FILTERS:
        expr = expr.node
    if isinstance(expr, nodes.Call):
        expr = expr.node
    return expr if isinstance(expr, nodes.Name | nodes.Getattr) else None


def _passes(node: nodes.Node | None) -> bool:
    """True if every filter of a `{% filter %}` or `{% set x | f %}` chain keeps tags."""
    while isinstance(node, nodes.Filter):
        if node.name not in _PASS_FILTERS:
            return False
        node = node.node
    return True


def _references(node: nodes.Node) -> list[nodes.Node]:
    """Every name and attribute *node* reads, leaving out the operand of `is defined`."""
    tested = _defined_operands(node)
    found = [node] if isinstance(node, nodes.Name | nodes.Getattr) else []
    found += node.find_all((nodes.Name, nodes.Getattr))
    return [
        ref
        for ref in found
        if id(ref) not in tested and not (isinstance(ref, nodes.Name) and ref.ctx != "load")
    ]


def _template_names(expr: nodes.Node) -> list[str] | None:
    """The templates an `{% include %}` names, or None unless it names them literally."""
    exprs: list[nodes.Node] = [expr]
    if isinstance(expr, nodes.List | nodes.Tuple):
        exprs = list(expr.items)
    names = [e.value for e in exprs if isinstance(e, nodes.Const) and isinstance(e.value, str)]
    return names if len(names) == len(exprs) else None


def _include_tag(text: str, node: nodes.Include, templates: list[str]) -> str:
    """The `{% include %}` *text* with *templates* for what it names."""
    opening = re.match(r"\{%[-+]?", text)
    closing = re.search(r"[-+]?%\}\Z", text)
    assert opening is not None and closing is not None  # it was scanned as a statement
    quoted = ['"' + name.replace("\\", "\\\\").replace('"', '\\"') + '"' for name in templates]
    target = quoted[0] if isinstance(node.template, nodes.Const) else f"[{', '.join(quoted)}]"
    missing = " ignore missing" if node.ignore_missing else ""
    return f"{opening.group()} include {target}{missing} {closing.group()}"


def _free_all(exprs: Iterable[nodes.Node]) -> set[str]:
    return set().union(*(_free(expr) for expr in exprs))


def _name_nodes(node: nodes.Node) -> list[nodes.Name]:
    """Every Name in *node*, *node* itself included (`find_all` leaves it out)."""
    found = list(node.find_all(nodes.Name))
    return [node, *found] if isinstance(node, nodes.Name) else found


def _free(node: nodes.Node) -> set[str]:
    """Names *node* reads, leaving out the operand of an `is defined` test."""
    tested = _defined_operands(node)
    return {
        name.name for name in _name_nodes(node) if name.ctx == "load" and id(name) not in tested
    }


def _defined_operands(node: nodes.Node) -> set[int]:
    tests = [node] if isinstance(node, nodes.Test) else []
    tests += node.find_all(nodes.Test)
    return {
        id(test.node)
        for test in tests
        if test.name in ("defined", "undefined") and isinstance(test.node, nodes.Name)
    }
