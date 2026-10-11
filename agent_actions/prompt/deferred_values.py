"""Leave the values of a workflow file that only a record or a version can render.

A workflow file is a Jinja template rendered when it loads, before it is parsed, so it can
import macros, set variables and generate actions. An action's `prompt:` is a template too,
but of a record: `source`, an upstream action and `i` do not exist at load.

Every `prompt:` value of the file and of templates/, and every other value that names a
version variable, is wrapped in a tag that sees exactly what Jinja has bound where the load
reaches it, in block or flow style, on its key's line or below it. A value whose names are
all bound renders at load as it always has. A prompt reading a name only a record supplies
is left whole for the per-record render: its own top-level `{{ }}` tags that read load-time
names and nothing else render into it, and the load-time data its other tags read is set at
its top. A value reading a version variable renders once per version, when its action
expands. A name a prompt reads that the load finds undefined may be an action the file
names by a tag; the file is rendered again keeping that prompt for the record, and the load
fails once the file is parsed if no action has that name.

Every name the load looks up and does not find is recorded, and the load fails when a
record or a version supplies it, so nothing they decide is decided at load.
"""

from __future__ import annotations

import bisect
import copy
import math
import re
import string
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import jinja2
import yaml
from jinja2 import Environment, FileSystemLoader, Undefined, meta, nodes
from jinja2.defaults import DEFAULT_NAMESPACE
from jinja2.environment import TemplateModule
from jinja2.ext import Extension
from jinja2.runtime import Context, LoopContext, Macro
from jinja2.utils import Namespace, missing

from agent_actions.errors import TemplateRenderingError
from agent_actions.prompt.context.scope_application import FRAMEWORK_NAMESPACES
from agent_actions.prompt.context.scope_builder import VersionNamespaceBuilder

# Private-use characters, which no workflow text holds, mark what the render left.
_LEFT_OPEN, _LEFT_CLOSE = "\ue000", "\ue001"
_HELD_OPEN, _HELD_CLOSE = "\ue002", "\ue003"
_TOKEN = re.compile(f"{_LEFT_OPEN}(\\d+){_LEFT_CLOSE}")
# A token as `leave` writes it in place of a value.
_LEFT = re.compile(f" ?{_LEFT_OPEN}(\\d+){_LEFT_CLOSE}")
_HELD = re.compile(f"{_HELD_OPEN}(\\d+){_HELD_CLOSE}")

# Names only a record supplies, whatever the workflow declares.
_RECORD_NAMES = FRAMEWORK_NAMESPACES | {"source", "i", "idx", "base_name", "param_name"}
_VERSION_NAMES = frozenset({"version", "i", "idx", "base_name", "param_name"})

_OPENER = re.compile(r"\{[{%#]")
_RAW_OPEN = re.compile(r"\{%[-+]?\s*raw\s*[-+]?%\}")
_RAW_CLOSE = re.compile(r"\{%[-+]?\s*endraw\s*[-+]?%\}")
_KEY = re.compile(
    r"( *)((?:-[ ]+)*)([A-Za-z_][A-Za-z0-9_.-]*|\"[^\"\n]*\"|'[^'\n]*')[ ]*:(?=[ \t]|$)"
)
# What may stand before a flow collection that is a node of its own: `- {name: a}`.
_ITEM = re.compile(r"[ ]*(?:-[ ]+)*")
_FLOW_KEY = re.compile(
    r"([A-Za-z_][A-Za-z0-9_.-]*|\"[^\"\n]*\"|'[^'\n]*')[ \t]*:(?=[ \t\n,\[\]{}]|$)"
)
_BLOCK_HEADER = re.compile(r"[ \t]+[|>][-+1-9]*[ \t]*(#.*)?\Z")
_NAMED = re.compile(
    r"^[ \t]*(?:-[ \t]+)*(name|param)[ \t]*:[ \t]*[\"']?([A-Za-z_][\w-]*)[\"']?[ \t]*(?:#.*)?$",
    re.M,
)
# An action named by a tag, `name: stage_{{ n }}`: the text before the tag.
_NAMED_BY_TAG = re.compile(r"^[ \t]*(?:-[ \t]+)*name[ \t]*:[ \t]*[\"']?([A-Za-z_]\w*)\{\{", re.M)
_STATEMENT = re.compile(r"\{%[-+]?\s*(\w+)")
_INLINE_SET = re.compile(r"\{%[-+]?\s*set\s+[\w.,\s()]+?=(?!=)")
_OPENS_BLOCK = frozenset(
    {"if", "for", "macro", "call", "filter", "with", "block", "autoescape", "trans"}
)
_UNDEFINED_NAME = re.compile(r"'(\w+)' is undefined")
_PROPERTIES = re.compile(r"[ \t]*((?:[&!]\S*[ \t]+)*)")
# What a Jinja string literal may hold as it is; anything else is escaped.
_PLAIN = frozenset(string.ascii_letters + string.digits + " _.,:;!?()[]/@=+*&^~|<>-")
_LOOP_FIELDS = (
    "index",
    "index0",
    "revindex",
    "revindex0",
    "first",
    "last",
    "length",
    "depth",
    "depth0",
    "previtem",
    "nextitem",
)


@dataclass(frozen=True)
class _Tag:
    start: int
    end: int
    kind: str  # "{", "%", "#" or "raw"


@dataclass(frozen=True)
class _Part:
    text: str
    kind: str  # "data" or a _Tag kind


@dataclass(frozen=True)
class _Region:
    """A value of the file wrapped so the load decides at render time where it renders."""

    site: int
    key: str
    where: str
    keycol: int
    flow: bool  # inside a flow mapping, where YAML reads it without indentation
    text: str  # the YAML text after `key:`, tags and all
    free: frozenset[str]
    assigned: frozenset[str]
    parts: tuple[_Part, ...]
    # The `{{ }}` parts outside every block of the value, with the names each reads.
    top: Mapping[int, frozenset[str]]

    @property
    def is_prompt(self) -> bool:
        return self.key == "prompt"

    def document(self, value: str) -> str:
        """*value* as the only value of a YAML document, read as the file reads it."""
        if self.flow:
            return "{k:" + value + "}"
        return " " * self.keycol + "k:" + value


@dataclass(frozen=True)
class _Value:
    """A `key: value` of the file's text, and where it may end (most likely first)."""

    key: str
    keycol: int
    start: int
    ends: list[int]
    flow: bool = False
    # A flow collection's own keys, tried when the value as a whole is not wrapped.
    inner: tuple[_Value, ...] = ()


@dataclass(frozen=True)
class _Left:
    """A value the render left: a prompt's per-record text, or a value's load names."""

    region: _Region
    text: str = ""
    names: Mapping[str, Any] | None = None
    while_importing: bool = False


class _NotData(Exception):
    pass


class LoadRender:
    """One load of a workflow: its environment, the values it left, the names it missed."""

    def __init__(self, templates_folder: Path, workflow: str) -> None:
        self._regions: list[_Region] = []
        self._left: list[_Left] = []
        self._missed: list[str] = []
        self._not_recorded: frozenset[str] = frozenset()
        self._importing = 0
        self._actions: set[str] = set()
        self._params: set[str] = set()
        self._action_prefixes: set[str] = set()
        for text in [workflow, *_template_texts(templates_folder)]:
            for kind, name in _NAMED.findall(text):
                (self._actions if kind == "name" else self._params).add(name)
            self._action_prefixes.update(_NAMED_BY_TAG.findall(text))
        self._version_names = _VERSION_NAMES | self._params
        # Names a prompt reads that the load found undefined, taken for actions the file
        # names by a tag; check() fails the load with the error of any that is not one.
        self._assumed: dict[str, jinja2.UndefinedError] = {}

        # Jinja leaves an environment's globals out of a template's undeclared names, so
        # names are read with one that has none, and the load's filters and tests.
        self._names_env = Environment()
        self._names_env.globals.clear()
        self.env = Environment(
            loader=_Loader(str(templates_folder), self),
            undefined=_undefined_class(self),
            extensions=[_LeaveExtension],
        )
        self.env.template_class = _ImportingTemplate
        self._names_env.filters = self.env.filters
        self._names_env.tests = self.env.tests
        extension = self.env.extensions[_LeaveExtension.identifier]
        assert isinstance(extension, _LeaveExtension)
        extension.load = self

    # ── the render ─────────────────────────────────────────────────────────

    def render(self, source: str, origin: str) -> str:
        template = self.env.from_string(self.wrap(source, origin))
        while True:
            try:
                return template.render()
            except jinja2.UndefinedError as e:
                name = self._read_by_a_prompt(e)
                if name is None:
                    raise
                # An action named by a tag, `name: {{ n }}`, is known only once the file
                # is parsed, so the prompts reading it are rendered again for the record.
                # What was left is kept: the templates/ globals hold tokens naming it.
                self._assumed[name] = e
                self._missed.clear()

    def wrap(self, source: str, origin: str) -> str:
        """*source* with each value that may render later wrapped in a leave tag."""
        source = source.replace("\r\n", "\n").replace("\r", "\n")
        tags = _scan(source)
        pieces: list[str] = []
        pos = 0

        def place(value: _Value) -> None:
            nonlocal pos
            if value.start < pos:
                return
            region = self._region(source, tags, value, origin)
            if region is None:
                for inner in value.inner:
                    place(inner)
                return
            pieces.extend([source[pos : value.start], f"{{% agac_leave {region.site} %}}"])
            pieces.extend([region.text, "{% agac_endleave %}"])
            pos = value.start + len(region.text)

        for value in _values(source, tags):
            place(value)
        pieces.append(source[pos:])
        return "".join(pieces)

    def renders_now(self, site: int, context: Context) -> bool:
        region = self._regions[site]
        unbound = {name for name in region.free if not _bound(context, name)}
        if not unbound:
            return True
        if self._importing:
            # A templates/ file's top level runs when it loads, with nothing bound yet.
            return False
        if region.is_prompt:
            return not any(self._per_record(name) for name in unbound)
        return not unbound & self._version_names

    def leave(self, site: int, context: Context) -> str:
        region = self._regions[site]
        if self._importing:
            left = _Left(region, while_importing=True)
        elif region.is_prompt:
            left = _Left(region, text=self._per_record_text(region, context))
        else:
            names = {n: _frozen(context.resolve_or_missing(n)) for n in region.free}
            left = _Left(region, names={n: v for n, v in names.items() if v is not missing})
        self._left.append(left)
        token = f"{_LEFT_OPEN}{len(self._left) - 1}{_LEFT_CLOSE}"
        # An anchor stays on the token, so an alias of the value gets it too.
        properties = _PROPERTIES.match(region.text)
        anchor = properties.group(1) if properties else ""
        return " " + anchor + token + ("\n" if region.text.endswith("\n") else "")

    # ── after the YAML is parsed ───────────────────────────────────────────

    def fill_prompts(self, data: Any) -> Any:
        """Each left prompt, as each record renders it."""

        def fill(text: str, path: str) -> str:
            left = self._whole(text, path)
            if left is None:
                return text
            if not left.region.is_prompt:
                return text
            return left.text

        return _strings(data, "", fill)

    def render_version(
        self,
        action: dict[str, Any],
        names: Mapping[str, Any],
        substitute: Callable[[str], str],
        where: str,
    ) -> dict[str, Any]:
        """*action* with each value left for its version rendered with *names*."""

        def fill(text: str, path: str) -> Any:
            left = self._whole(text, path)
            if left is None or left.region.is_prompt:
                return text
            return self._render_value(left, substitute(left.region.text), names, path)

        result: dict[str, Any] = _strings(action, where, fill)
        return result

    def fill_values(self, data: Any) -> Any:
        """Values still left read a version variable outside a versioned action."""

        def fill(text: str, path: str) -> Any:
            left = self._whole(text, path)
            if left is None or left.region.is_prompt:
                return text
            return self._render_value(left, left.region.text, {}, path)

        # A test such as `i is defined` answers truly here: no version is coming.
        self._not_recorded = self._version_names
        try:
            return _strings(data, "", fill)
        finally:
            self._not_recorded = frozenset()

    def check(self, data: Any) -> None:
        """Fail on any name the load looked up that a record or a version supplies, and on
        any it took for an action that is not one."""
        later = {"source", *FRAMEWORK_NAMESPACES} - {"version"}
        actions = data.get("actions") if isinstance(data, dict) else None
        named = set()
        for action in actions if isinstance(actions, list) else []:
            if isinstance(action, dict):
                version = action.get("_version_context")
                base = version.get("base_name") if isinstance(version, dict) else None
                named.update({action.get("name"), base})
        for name, error in self._assumed.items():
            if name not in named:
                raise error
        for action in actions if isinstance(actions, list) else []:
            if not isinstance(action, dict):
                continue
            if isinstance(action.get("name"), str):
                later.add(action["name"])
            version = action.get("_version_context")
            if isinstance(version, dict):
                # Without a versioned action, a version variable is truly never defined.
                later.update({"version", *VersionNamespaceBuilder.promoted_names(version)})
                later.add(str(version.get("base_name")))
            scope = action.get("context_scope")
            for refs in scope.values() if isinstance(scope, dict) else []:
                for ref in refs if isinstance(refs, list) else []:
                    if isinstance(ref, str):
                        later.add(ref.split(".", 1)[0])
        missed = [name for name in dict.fromkeys(self._missed) if name in later]
        if missed:
            quoted = ", ".join(repr(name) for name in missed)
            raise TemplateRenderingError(
                f"{quoted} is looked up while the workflow loads, where only a record or a "
                "version supplies it, so what it decides would be decided once for every "
                "record. Only an action's prompt renders per record, and a versioned "
                "action's other values per version: test it there",
                context={"names": missed},
            )

    def readable(self, text: str) -> str:
        """*text* with each left value's token named, on the one line the token holds, so
        a YAML error's line numbers still point into it."""

        def name(match: re.Match[str]) -> str:
            region = self._left[int(match.group(1))].region
            stage = "kept for each record" if region.is_prompt else "rendered per version"
            return f" <the value at {region.where}, {stage}>"

        return _LEFT.sub(name, text)

    def explain(self, error: Exception) -> str:
        """Why a name the load found undefined is not there yet, when it is a later one."""
        match = _UNDEFINED_NAME.search(str(error))
        if not isinstance(error, jinja2.UndefinedError) or match is None:
            return ""
        name = match.group(1)
        if name in self._assumed or not self._per_record(name):
            return ""
        return (
            f". '{name}' exists only for each record or version, and this tag renders at "
            "load: only an action's prompt renders per record, and a versioned action's "
            "other values per version, while a macro, an include, a caller() body or a "
            "captured block renders when the file loads, even when a prompt uses it. Write "
            "the tag in the prompt itself, or wrap it in {% raw %} so the prompt receives it "
            "as text"
        )

    # ── internals ─────────────────────────────────────────────────────────

    def _read(self, text: str) -> tuple[nodes.Template, frozenset[str]]:
        """*text* parsed, and the names it reads that it does not bind itself."""
        ast = self._names_env.parse(text)
        return ast, frozenset(meta.find_undeclared_variables(ast))

    def _per_record(self, name: str) -> bool:
        if name in _RECORD_NAMES or name in self._params or name in self._actions:
            return True
        if name in self._assumed:
            return True
        if any(name.startswith(f"{action}_") for action in self._actions):
            return True
        return any(name.startswith(prefix) for prefix in self._action_prefixes)

    def _read_by_a_prompt(self, error: jinja2.UndefinedError) -> str | None:
        """The name *error* found undefined, when a prompt reads it and it may be an
        action the load does not know yet."""
        match = _UNDEFINED_NAME.search(str(error))
        if match is None or self._per_record(match.group(1)):
            return None
        name = match.group(1)
        return name if any(r.is_prompt and name in r.free for r in self._regions) else None

    def _missed_name(self, name: str) -> None:
        # A file's top level runs on import only for what it exports, and as on main
        # an include partial's top level meets its includer's names undefined there.
        if not self._importing and name not in self._not_recorded:
            self._missed.append(name)

    def _whole(self, text: str, path: str) -> _Left | None:
        match = _TOKEN.search(text)
        if match is None:
            return None
        left = self._left[int(match.group(1))]
        if left.while_importing:
            raise TemplateRenderingError(
                f"{path}: the value at {left.region.where} renders per record or per version, "
                "but the template computed it at its top level as it loaded, where nothing "
                "is bound. Write it in a macro that the workflow calls",
            )
        if text.strip() != match.group(0):
            raise TemplateRenderingError(
                f"{path}: the value at {left.region.where} renders per record or per version, "
                "so it must stand alone as a value, not inside text the file builds at load",
            )
        return left

    def _region(self, source: str, tags: list[_Tag], value: _Value, origin: str) -> _Region | None:
        key, start = value.key, value.start
        for end in value.ends:
            text = source[start:end]
            try:
                ast, free = self._read(text)
            except jinja2.TemplateError:
                continue
            if not free or (key != "prompt" and not free & self._version_names):
                return None
            parts = _parts(text, [t for t in tags if start <= t.start < end], start)
            if parts is None:
                return None
            line = source.count("\n", 0, start) + 1
            region = _Region(
                site=len(self._regions),
                key=key,
                where=f"line {line} of {origin}",
                keycol=value.keycol,
                flow=value.flow,
                text=text,
                free=free,
                assigned=_assigned(ast),
                parts=parts,
                top=self._top_outputs(parts, ast),
            )
            self._regions.append(region)
            return region
        return None

    def _top_outputs(self, parts: tuple[_Part, ...], ast: nodes.Template) -> dict[int, frozenset]:
        top: dict[int, frozenset] = {}
        depth = 0
        for index, part in enumerate(parts):
            if part.kind == "{" and depth == 0:
                try:
                    top[index] = self._read(_bare(part.text))[1]
                except jinja2.TemplateError:
                    return {}
            elif part.kind == "%":
                word = _STATEMENT.match(part.text)
                name = word.group(1) if word else ""
                if name in _OPENS_BLOCK or (name == "set" and not _INLINE_SET.match(part.text)):
                    depth += 1
                elif name.startswith("end"):
                    depth -= 1
        outputs = sum(
            1
            for node in ast.body
            if isinstance(node, nodes.Output)
            for child in node.nodes
            if not isinstance(child, nodes.TemplateData)
        )
        # Counted differently from Jinja's parse, the split cannot be trusted.
        return top if outputs == len(top) else {}

    def _per_record_text(self, region: _Region, context: Context) -> str:
        """The prompt each record renders: load-time tags rendered in, load-time data set."""
        pieces: list[tuple[str, str]] = []
        kept: list[str] = []

        def hold(text: str) -> None:
            pieces.append(("held", f"{_HELD_OPEN}{len(kept)}{_HELD_CLOSE}"))
            kept.append(text)

        strip_next = False
        for index, part in enumerate(region.parts):
            if part.kind == "data":
                pieces.append(("data", part.text.lstrip() if strip_next else part.text))
                strip_next = False
                continue
            if part.kind == "raw":
                # A raw block's text is the value's text, which YAML reads; only its
                # delimiters are kept as written.
                opening = _RAW_OPEN.match(part.text)
                closing = _RAW_CLOSE.search(part.text, opening.end()) if opening else None
                if opening and closing:
                    hold(opening.group(0))
                    pieces.append(("data", part.text[opening.end() : closing.start()]))
                    hold(closing.group(0))
                else:
                    hold(part.text)
                strip_next = False
                continue
            names = region.top.get(index)
            # A tag that reads no name renders alike for every record, and rendered here
            # its output, `{{ '{{' }}` say, would be read as template text again.
            if names and not names & region.assigned and all(_bound(context, n) for n in names):
                if part.text.startswith("{{-") and pieces and pieces[-1][0] == "data":
                    pieces[-1] = ("data", pieces[-1][1].rstrip())
                rendered = self.env.from_string(_bare(part.text)).render(context.get_all())
                pieces.append(("rendered", rendered))
                strip_next = part.text.endswith("-}}")
            else:
                hold(part.text)
                strip_next = False

        later = sorted(n for n in region.free if not _bound(context, n) and self._per_record(n))
        reads = ", ".join(repr(n) for n in later)
        where = f"The prompt at {region.where} reads {reads}, so it renders for each record"
        body = _indent_tag_lines("".join(text for _, text in pieces))
        try:
            parsed = yaml.safe_load(region.document(body))
        except yaml.YAMLError as e:
            how = (
                "once its load-time tags render it is no longer valid YAML"
                if any(kind == "rendered" for kind, _ in pieces)
                else "with its tags kept for the record it is not valid YAML"
            )
            raise TemplateRenderingError(
                f"{where}, and {how}: {getattr(e, 'problem', None) or e}",
            ) from None
        value = parsed.get("k") if isinstance(parsed, dict) and list(parsed) == ["k"] else None
        if not isinstance(value, str):
            raise TemplateRenderingError(
                f"{where}, and its load-time tags turned it into more YAML"
            )
        text = _HELD.sub(lambda m: kept[int(m.group(1))], value)

        try:
            ast, free = self._read(text)
        except jinja2.TemplateError as e:
            raise TemplateRenderingError(f"{where}, and is not a valid template: {e}") from None
        if any(True for _ in ast.find_all((nodes.Include, nodes.Import, nodes.FromImport))):
            raise TemplateRenderingError(
                f"{where}, where there is no templates folder to include or import from. "
                "Write that text into the prompt, or load it with load_prompt in a "
                "{{ }} tag of its own",
            )
        preamble = []
        for name in sorted(free):
            value = context.resolve_or_missing(name)
            if not _bound(context, name) or DEFAULT_NAMESPACE.get(name, missing) is value:
                continue
            try:
                literal = _literal(value)
            except _NotData:
                raise TemplateRenderingError(
                    f"{where}, but it also uses '{name}', {_kind(value)} of the load, inside a "
                    "{% %} block or beside a per-record name, and only data reaches the "
                    f"per-record render. Use '{name}' in a {{{{ }}}} tag of its own outside "
                    "the prompt's blocks, which renders at load, or define it in the prompt",
                ) from None
            # `+%}` keeps the newline after the tag that the per-record render would trim.
            preamble.append(f"{{% set {name} = {literal} +%}}")
        return "".join(preamble) + text

    def _render_value(self, left: _Left, text: str, names: Mapping[str, Any], path: str) -> Any:
        bound = {**names, **(left.names or {})}
        try:
            rendered = self.env.from_string(text).render(bound)
        except jinja2.TemplateError as e:
            match = _UNDEFINED_NAME.search(str(e))
            hint = (
                ". A version variable exists only in a versioned action's values and in prompts"
                if match and match.group(1) in self._version_names and not names
                else ""
            )
            raise TemplateRenderingError(
                f"{path}: {e}{hint}", context={"value": text.strip()}
            ) from None
        try:
            parsed = yaml.safe_load(left.region.document(rendered))
        except yaml.YAMLError as e:
            raise TemplateRenderingError(
                f"{path}: once rendered, the value is not valid YAML: "
                f"{getattr(e, 'problem', None) or e}",
                context={"value": rendered.strip()},
            ) from None
        if not isinstance(parsed, dict) or list(parsed) != ["k"]:
            raise TemplateRenderingError(f"{path}: once rendered, the value is more than one value")
        return parsed["k"]


class _LeaveExtension(Extension):
    """`{% agac_leave N %}value{% agac_endleave %}`: render here, or leave it for later."""

    tags = {"agac_leave"}

    def __init__(self, environment: Environment) -> None:
        super().__init__(environment)
        self.load: LoadRender | None = None

    def parse(self, parser: Any) -> nodes.Node:
        lineno = next(parser.stream).lineno
        site = parser.parse_expression()
        body = parser.parse_statements(("name:agac_endleave",), drop_needle=True)
        # An If adds no scope: a value rendered at load binds what it sets, as before.
        now = self.call_method("_now", [site, nodes.DerivedContextReference()])
        later = self.call_method("_later", [site, nodes.DerivedContextReference()])
        return nodes.If(now, body, [], [nodes.Output([later])], lineno=lineno)

    def _now(self, site: int, context: Context) -> bool:
        assert self.load is not None
        return self.load.renders_now(site, context)

    def _later(self, site: int, context: Context) -> str:
        assert self.load is not None
        return self.load.leave(site, context)


class _Loader(FileSystemLoader):
    """Hands Jinja each templates/ file with its values wrapped as the workflow's are."""

    def __init__(self, searchpath: str, load: LoadRender) -> None:
        super().__init__(searchpath)
        self._load = load

    def get_source(
        self, environment: Environment, template: str
    ) -> tuple[str, str, Callable[[], bool]]:
        source, filename, uptodate = super().get_source(environment, template)
        return self._load.wrap(source, f"templates/{template}"), filename, uptodate


class _ImportingTemplate(jinja2.Template):
    """A file's top level runs as it is imported, leniently, as the load always ran it."""

    def make_module(
        self,
        vars: dict[str, Any] | None = None,
        shared: bool = False,
        locals: Mapping[str, Any] | None = None,
    ) -> TemplateModule:
        extension = self.environment.extensions[_LeaveExtension.identifier]
        load = extension.load if isinstance(extension, _LeaveExtension) else None
        if load is None:
            return super().make_module(vars, shared, locals)
        load._importing += 1
        try:
            return super().make_module(vars, shared, locals)
        finally:
            load._importing -= 1


def _undefined_class(load: LoadRender) -> type[Undefined]:
    """`StrictUndefined`, except while a template's top level is imported; records each
    name it stands for."""

    class LoadUndefined(Undefined):
        __slots__ = ()

        def __init__(
            self,
            hint: str | None = None,
            obj: Any = missing,
            name: str | None = None,
            exc: type[jinja2.TemplateRuntimeError] = jinja2.UndefinedError,
        ) -> None:
            super().__init__(hint, obj, name, exc)
            if obj is missing and name is not None:
                load._missed_name(name)

        def __str__(self) -> str:
            return "" if load._importing else self._fail_with_undefined_error()

        def __iter__(self) -> Iterator[Any]:
            return iter(()) if load._importing else self._fail_with_undefined_error()

        def __len__(self) -> int:
            return 0 if load._importing else self._fail_with_undefined_error()

        def __bool__(self) -> bool:
            return False if load._importing else self._fail_with_undefined_error()

        def __eq__(self, other: Any) -> bool:
            if load._importing:
                return type(self) is type(other)
            return self._fail_with_undefined_error()

        def __ne__(self, other: Any) -> bool:
            return not self.__eq__(other)

        def __hash__(self) -> int:
            return id(type(self)) if load._importing else self._fail_with_undefined_error()

        def __contains__(self, item: Any) -> bool:
            return False if load._importing else self._fail_with_undefined_error()

    return LoadUndefined


# ── finding the values in the file's text ────────────────────────────────────


def _scan(source: str) -> list[_Tag]:
    """Every Jinja tag, comment and raw block of *source*, in order."""
    tags = []
    pos = 0
    while (opener := _OPENER.search(source, pos)) is not None:
        start = opener.start()
        kind = source[start + 1]
        if kind == "#":
            close = source.find("#}", start + 2)
            end = len(source) if close < 0 else close + 2
        elif kind == "%" and (raw := _RAW_OPEN.match(source, start)) is not None:
            closing = _RAW_CLOSE.search(source, raw.end())
            end = len(source) if closing is None else closing.end()
            kind = "raw"
        else:
            end = _tag_end(source, start + 2, "}" if kind == "{" else "%")
        tags.append(_Tag(start, end, kind))
        pos = end
    return tags


def _tag_end(source: str, pos: int, closer: str) -> int:
    depth = 0
    quote = ""
    while pos < len(source):
        char = source[pos]
        if quote:
            if char == "\\":
                pos += 1
            elif char == quote:
                quote = ""
        elif char in "'\"":
            quote = char
        elif char in "([{":
            depth += 1
        elif char in ")]" or (char == "}" and depth):
            depth = max(depth - 1, 0)
        elif char == closer and source.startswith("}", pos + 1) and not depth:
            return pos + 2
        pos += 1
    return len(source)


def _values(source: str, tags: list[_Tag]) -> Iterable[_Value]:
    """Each `key: value` of *source*, in block or flow style."""
    starts = [tag.start for tag in tags]

    def inside(pos: int) -> _Tag | None:
        i = bisect.bisect_right(starts, pos) - 1
        return tags[i] if i >= 0 and tags[i].start < pos < tags[i].end else None

    by_start = {tag.start: tag for tag in tags}
    pos = 0
    while pos < len(source):
        line_end = _line_end(source, pos)
        if inside(pos) is not None:
            pos = line_end + 1
            continue
        key = _KEY.match(source, pos, line_end)
        if key is None:
            # A flow collection standing for a node, `- {name: a, prompt: ...}`.
            item = _ITEM.match(source, pos, line_end)
            flow = _flow(source, item.end(), by_start) if item else None
            if flow is not None:
                yield from flow[0]
                pos = _past_line(source, flow[1])
            else:
                pos = line_end + 1
            continue
        keycol = len(key.group(1)) + len(key.group(2))
        ends = _value_ends(source, key.end(), line_end, keycol, tags, inside, by_start)
        if not ends:
            pos = line_end + 1
            continue
        value = _flow_skip(source, key.end(), by_start)
        flow = _flow(source, value, by_start)
        inner = tuple(flow[0]) if flow is not None else ()
        yield _Value(key.group(3).strip("\"'"), keycol, key.end(), ends, inner=inner)
        # A flow value may go on at its key's column, past where a block value would end.
        pos = max(ends[0], _past_line(source, flow[1]) if flow is not None else 0)


def _value_ends(
    source: str,
    start: int,
    line_end: int,
    keycol: int,
    tags: list[_Tag],
    inside: Callable[[int], _Tag | None],
    by_start: Mapping[int, _Tag],
) -> list[int]:
    rest = source[start:line_end]
    first = rest.lstrip(" \t")
    below = not first or first.startswith("#")
    if below:
        # Nothing after the key: a scalar may start on a line below it, more indented.
        line = _first_value_line(source, _past_line(source, line_end), keycol, tags, inside)
        if line is None:
            return []
        line_end = _line_end(source, line)
        rest = source[line:line_end]
        first = rest.lstrip(" \t")
    if first[0] in "\"'":
        close = _closing_quote(source, line_end - len(first), first[0], by_start)
        return [] if close is None else _own_newline(source, [_past_line(source, close)])
    if first[0] in "|>" and not _BLOCK_HEADER.match(rest):
        return []

    # A block scalar, or a plain or flow value with continuation lines: the lines more
    # indented than the key, and tag-only lines between them.
    ends = [_past_line(source, line_end)]
    after: list[int] = []
    blank_after = ends[0]
    pos = ends[0]
    while pos < len(source):
        end = _line_end(source, pos)
        kind, indent = _line_kind(source, pos, end, keycol, tags, inside)
        if below and kind == "content" and first[0] not in "|>" and _KEY.match(source, pos, end):
            # A key among the lines below: they are a mapping, not a scalar.
            return []
        if kind == "content" or (kind == "tags" and indent > keycol):
            ends.append(_past_line(source, end))
            after = []
            blank_after = ends[-1]
        elif kind == "tags":
            after.append(_past_line(source, end))
        elif kind == "blank" and not after:
            blank_after = _past_line(source, end)
        elif kind == "end":
            break
        pos = _past_line(source, end)
    if first[0] in "|>" and "+" in first.split("#", 1)[0]:
        # Kept (`|+`), the blank lines after the last one are the value's too.
        ends[-1] = blank_after
    # Longest first, then a block left open closed by the tag lines after it, then shorter.
    return _own_newline(source, [ends[-1], *after, *reversed(ends[:-1])])


def _first_value_line(
    source: str,
    pos: int,
    keycol: int,
    tags: list[_Tag],
    inside: Callable[[int], _Tag | None],
) -> int | None:
    """The line the scalar written below a key starts on, if what is below it is one."""
    while pos < len(source):
        end = _line_end(source, pos)
        kind, _ = _line_kind(source, pos, end, keycol, tags, inside)
        text = source[pos:end].lstrip(" ")
        if kind in ("blank", "tags") or (kind == "content" and text.startswith("#")):
            pos = _past_line(source, end)
            continue
        if kind != "content" or inside(pos) is not None or _KEY.match(source, pos, end):
            return None
        if _OPENER.match(text) or text[0] not in "-?:,[]{}&*!%@`":
            return pos
        # `-5` is a scalar, `- a` a sequence.
        return pos if text[0] == "-" and text[1:2] not in ("", " ", "\t") else None
    return None


def _flow(source: str, pos: int, by_start: Mapping[int, _Tag]) -> tuple[list[_Value], int] | None:
    """The `key: scalar` pairs of the flow collection opening at *pos*, and where it ends;
    None when no flow collection opens there."""
    if pos >= len(source) or source[pos] not in "{[" or pos in by_start:
        return None
    closer = "}" if source[pos] == "{" else "]"
    values: list[_Value] = []
    pos += 1
    while True:
        pos = _flow_skip(source, pos, by_start)
        if pos >= len(source) or source[pos] in "]}".replace(closer, ""):
            return None
        if source[pos] == closer:
            return values, pos + 1
        if source[pos] == ",":
            pos += 1
            continue
        key = None if pos in by_start else _FLOW_KEY.match(source, pos)
        start = key.end() if key else pos
        nested = _flow(source, _flow_skip(source, start, by_start), by_start)
        if nested is not None:
            values += nested[0]
            pos = nested[1]
            continue
        end, pos = _flow_scalar_end(source, _flow_skip(source, start, by_start), by_start)
        if key is not None:
            values.append(_Value(key.group(1).strip("\"'"), 0, start, [end], flow=True))
        if source[pos : pos + 1] not in (",", closer):
            return None


def _flow_skip(source: str, pos: int, by_start: Mapping[int, _Tag]) -> int:
    """*pos* past the spaces, line breaks and comments before a flow node."""
    while pos < len(source) and pos not in by_start:
        if source[pos] in " \t\n":
            pos += 1
        elif source[pos] == "#" and source[pos - 1] in " \t\n":
            pos = _line_end(source, pos)
        else:
            break
    return pos


def _flow_scalar_end(source: str, pos: int, by_start: Mapping[int, _Tag]) -> tuple[int, int]:
    """Where the flow scalar at *pos* ends, and where the `,` or bracket after it is."""
    end = pos
    if pos < len(source) and source[pos] in "\"'" and pos not in by_start:
        close = _closing_quote(source, pos, source[pos], by_start)
        if close is None:
            return len(source), len(source)
        pos = end = close + 1
    while pos < len(source):
        tag = by_start.get(pos)
        if tag is not None:
            pos = end = tag.end
        elif source[pos] in ",[]{}":
            break
        elif source[pos] == "#" and source[pos - 1] in " \t\n":
            pos = _line_end(source, pos)
        else:
            pos += 1
            if not source[pos - 1].isspace():
                end = pos
    return end, pos


def _indent_tag_lines(body: str) -> str:
    """*body* with each line holding only kept tags indented at least as its text is.

    A tag on a line of its own may sit left of the block it is in, since the load renders
    it to nothing; kept for the record, it has to stay inside the value. The value's own
    indentation is that of its least indented text, not of its first: the body of an
    `{% if %}` may sit deeper than the tags around it.
    """
    lines = body.split("\n")
    tag_only = [not _HELD.sub("", line).strip() and bool(_HELD.search(line)) for line in lines]
    text = [i for i, line in enumerate(lines) if i and line.strip() and not tag_only[i]]
    if not text:
        return body
    indent = min(len(lines[i]) - len(lines[i].lstrip(" ")) for i in text)
    for i, line in enumerate(lines):
        if i and tag_only[i] and len(line) - len(line.lstrip(" ")) < indent:
            lines[i] = " " * indent + line.lstrip(" ")
    return "\n".join(lines)


def _own_newline(source: str, ends: list[int]) -> list[int]:
    """*ends* short of the file's last newline, which Jinja drops as it always has."""
    last = len(source) - 1 if source.endswith("\n") else len(source)
    return [min(end, last) for end in ends]


def _line_kind(
    source: str,
    pos: int,
    end: int,
    keycol: int,
    tags: list[_Tag],
    inside: Callable[[int], _Tag | None],
) -> tuple[str, int]:
    if inside(pos) is not None:
        return "content", keycol + 1
    line = source[pos:end]
    data = line
    first = bisect.bisect_left(tags, pos, key=lambda tag: tag.start)
    for tag in tags[first:]:
        if tag.start >= end:
            break
        if tag.kind in "%#":
            data = data.replace(source[tag.start : min(tag.end, end)], "", 1)
    indent = len(line) - len(line.lstrip(" "))
    if not data.strip():
        return ("tags", indent) if data != line else ("blank", indent)
    return ("content" if indent > keycol else "end"), indent


def _closing_quote(
    source: str, opening: int, quote: str, by_start: Mapping[int, _Tag]
) -> int | None:
    pos = opening + 1
    while pos < len(source):
        tag = by_start.get(pos)
        if tag is not None:
            pos = tag.end
            continue
        char = source[pos]
        if quote == '"' and char == "\\":
            pos += 2
            continue
        if char == quote:
            if quote == "'" and source.startswith("''", pos):
                pos += 2
                continue
            return pos
        pos += 1
    return None


def _line_end(source: str, pos: int) -> int:
    end = source.find("\n", pos)
    return len(source) if end < 0 else end


def _past_line(source: str, pos: int) -> int:
    end = _line_end(source, pos)
    return end + 1 if end < len(source) else end


def _parts(text: str, tags: list[_Tag], offset: int) -> tuple[_Part, ...] | None:
    parts = []
    pos = 0
    for tag in tags:
        start, end = tag.start - offset, tag.end - offset
        if end > len(text):
            return None
        if start > pos:
            parts.append(_Part(text[pos:start], "data"))
        parts.append(_Part(text[start:end], tag.kind))
        pos = end
    if pos < len(text):
        parts.append(_Part(text[pos:], "data"))
    return tuple(parts)


def _assigned(ast: nodes.Template) -> frozenset[str]:
    names = {node.name for node in ast.find_all(nodes.Name) if node.ctx in ("store", "param")}
    names.update(node.name for node in ast.find_all(nodes.Macro))
    names.update(node.target for node in ast.find_all(nodes.Import))
    for node in ast.find_all(nodes.FromImport):
        names.update(n if isinstance(n, str) else n[1] for n in node.names)
    return frozenset(names)


def _bare(tag: str) -> str:
    """A `{{ }}` tag without its whitespace control, to render on its own."""
    return "{{" + tag[2:-2].strip("-+") + "}}"


def _template_texts(folder: Path) -> Iterable[str]:
    if not folder.is_dir():
        return
    for path in sorted(folder.rglob("*")):
        if path.is_file():
            try:
                yield path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue


# ── what reaches the per-record render ───────────────────────────────────────


def _bound(context: Context, name: str) -> bool:
    value = context.resolve_or_missing(name)
    return value is not missing and not isinstance(value, jinja2.Undefined)


def _frozen(value: Any) -> Any:
    """*value* as it is now, for a render after the load has moved on."""
    if isinstance(value, Namespace):
        return Namespace(dict(object.__getattribute__(value, "_Namespace__attrs")))
    if isinstance(value, LoopContext):
        return _loop_fields(value)
    if isinstance(value, list | dict | tuple):
        try:
            return copy.deepcopy(value)
        except Exception:  # noqa: BLE001 - an uncopyable value is read as it is
            return value
    return value


def _loop_fields(loop: LoopContext) -> dict[str, Any]:
    fields = {name: getattr(loop, name) for name in _LOOP_FIELDS}
    return {k: v for k, v in fields.items() if not isinstance(v, jinja2.Undefined)}


def _literal(value: Any, depth: int = 0) -> str:
    """*value* as a Jinja literal that evaluates to it."""
    if depth > 50:
        raise _NotData
    if value is None:
        return "none"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(int(value))
    if isinstance(value, float):
        if not math.isfinite(value):
            raise _NotData
        return repr(float(value))
    if isinstance(value, str):
        return '"' + "".join(c if c in _PLAIN else _escaped(c) for c in value) + '"'
    if isinstance(value, tuple):
        items = [_literal(item, depth + 1) for item in value]
        return "(" + ", ".join(items) + ("," if len(items) == 1 else "") + ")"
    if isinstance(value, list):
        return "[" + ", ".join(_literal(item, depth + 1) for item in value) + "]"
    if isinstance(value, dict):
        pairs = (f"{_literal(k, depth + 1)}: {_literal(v, depth + 1)}" for k, v in value.items())
        return "{" + ", ".join(pairs) + "}"
    if isinstance(value, Namespace):
        return f"namespace({_literal(dict(object.__getattribute__(value, '_Namespace__attrs')))})"
    if isinstance(value, LoopContext):
        return _literal(_loop_fields(value), depth + 1)
    raise _NotData


def _escaped(char: str) -> str:
    code = ord(char)
    if code < 0x100:
        return f"\\x{code:02x}"
    return f"\\u{code:04x}" if code < 0x10000 else f"\\U{code:08x}"


def _kind(value: Any) -> str:
    if isinstance(value, Macro):
        return "a macro"
    if isinstance(value, TemplateModule):
        return "an imported template"
    if callable(value):
        return "a function"
    return f"a {type(value).__name__}"


def _strings(value: Any, path: str, fill: Callable[[str, str], Any]) -> Any:
    """*value* with each string in it replaced by `fill(string, its path)`."""
    if isinstance(value, str):
        return fill(value, path)
    if isinstance(value, dict):
        return {k: _strings(v, f"{path}.{k}" if path else str(k), fill) for k, v in value.items()}
    if isinstance(value, list):
        items = []
        for i, item in enumerate(value):
            name = item.get("name") if isinstance(item, dict) else None
            label = name if isinstance(name, str) and not _TOKEN.search(name) else i
            items.append(_strings(item, f"{path}[{label}]", fill))
        return items
    return value
