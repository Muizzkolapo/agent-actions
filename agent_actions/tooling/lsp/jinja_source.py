"""Render a workflow file for the editor, the way `agac` renders it, and map each action to its source line."""

import bisect
import logging
import re
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NamedTuple

import jinja2
import yaml

from agent_actions.errors import ConfigurationError, TemplateRenderingError
from agent_actions.prompt.deferred_values import _INLINE_SET, LoadRender, _scan
from agent_actions.prompt.render_workflow import _load_yaml_content, new_load_render

from .models import Location

logger = logging.getLogger(__name__)

_NAME_LINE = re.compile(r"^\s*(?:-\s+)?name:[ \t]*(?=\S)")
_NAME_MARK = re.compile(r"  # @src (\S+?):(\d+):(\d+)")
_LINE_MARK = re.compile(r"  # @(?:src|at) (\S+?):(\d+)")
# The name a `name:` line writes, when it writes one with no tag.
_LITERAL_NAME = re.compile(r"^\s*(?:-\s+)?name:\s*['\"]?([^'\"#{}]+?)['\"]?\s*$")
_MARK_TEXT = re.compile(r"  # @(?:src|at) \S+?:\d+(?::\d+)?")
# The line breaks PyYAML counts in a node's line number.
_LINE_BREAK = re.compile(r"\r\n|[\r\n\x85\u2028\u2029]")
# A tag that strips the whitespace after it would strip nothing once a mark follows it.
_STRIPS_AFTER = ("-}}", "-%}", "-#}")
_CONTROL_OPENERS = ("{%", "{#")
# A file with none of these renders each line as written.
_JINJA_OPENERS = ("{{", *_CONTROL_OPENERS)
_BLOCK_TAG = re.compile(r"\{%[-+]?\s*(end)?(set|filter|macro)\b")
# A `set` block holds its body as a value; a `filter` block changes its body before output.
# A mark in either body would change the text, so neither body gets a mark.
_VALUE_BLOCKS = ("set", "filter")


class WorkflowRenderError(Exception):
    """A workflow that does not render; *line* is 0-indexed in the workflow file."""

    def __init__(self, message: str, line: int = 0) -> None:
        super().__init__(message)
        self.message = message
        self.line = line


@dataclass
class RenderedWorkflow:
    """The render of a workflow file.

    `action_lines` holds the workflow-file lines that define a parsed action. `live_lines`
    holds the workflow-file lines that the render output as written; it is None for a file
    with no Jinja tag. When the marks cannot be trusted, both are empty for a file with a
    Jinja tag, so nothing is read from its lines. `line_owners` maps a
    workflow-file line to the action whose text it became, or None when it became text of
    no action or of more than one.
    """

    text: str
    data: dict
    action_sources: dict[str, Location]
    action_lines: frozenset[int] | None = None
    live_lines: frozenset[int] | None = None
    line_owners: dict[int, str | None] | None = None


class _ActionNode(NamedTuple):
    name: str
    name_line: int
    start_line: int
    end_line: int
    end_column: int


class MarkingLoadRender(LoadRender):
    """Tags source lines with the file and line they came from, as YAML comments.

    Each `name:` line gets `# @src <origin>:<line>:<column>`; each other line of the
    workflow file that is output where it is written gets `# @at <origin>:<line>`, so a
    line that a tag removes is the line whose mark is missing from the output.
    """

    def wrap(self, source: str, origin: str) -> str:
        source = source.replace("\r\n", "\n").replace("\r", "\n")
        in_workflow = not origin.startswith("templates/")
        tags = _scan(source)
        starts = [tag.start for tag in tags]
        values = _block_spans(source, tags, _VALUE_BLOCKS)
        macros = _block_spans(source, tags, ("macro",))
        lines = source.split("\n")
        line_starts = []
        offset = 0
        for line in lines:
            line_starts.append(offset)
            offset += len(line) + 1
        # A name written as a `{{ }}` tag over more than one line: its mark goes after the
        # tag, on the line where the tag ends, which renders onto the name line.
        pending: str | None = None
        for i, line in enumerate(lines):
            end = line_starts[i] + len(line)
            tag = _tag_holding(tags, starts, end)
            held = any(start <= end < stop for start, stop, _ in values)
            match = _NAME_LINE.match(line)
            if tag is not None and tag.kind != "raw":
                # A mark inside a tag would be Jinja, not a YAML comment. The text of a raw
                # block is output as written, so a mark in it is a comment.
                if match and tag.kind == "{" and not held and line_starts[i] < tag.start:
                    column = match.end() + (line[match.end()] in "'\"")
                    pending = f"  # @src {origin}:{i}:{column}"
                continue
            name_mark, pending = pending or "", None
            if not line.strip() or line.rstrip().endswith(_STRIPS_AFTER):
                continue
            if held:
                continue
            if match:
                column = match.end() + (line[match.end()] in "'\"")
                lines[i] = f"{line.rstrip()}  # @src {origin}:{i}:{column}"
            elif in_workflow and not any(start <= end < stop for start, stop, _ in macros):
                # A macro body is output where the macro is called, not where it is
                # written, so it gets no line mark and is not live.
                lines[i] = f"{line.rstrip()}{name_mark}  # @at {origin}:{i}"
            elif name_mark:
                lines[i] = f"{line.rstrip()}{name_mark}"
        return super().wrap("\n".join(lines), origin)


def _block_spans(
    source: str, tags: list[Any], kinds: tuple[str, ...]
) -> list[tuple[int, int, str]]:
    """The body of each outermost block of one of *kinds*, by offset, and its kind."""
    spans: list[tuple[int, int, str]] = []
    stack: list[tuple[str, int]] = []
    for tag in tags:
        if tag.kind != "%":
            continue
        text = source[tag.start : tag.end]
        block = _BLOCK_TAG.match(text)
        if block is None or block.group(2) not in kinds:
            continue
        kind = block.group(2)
        if block.group(1) is None:
            # `{% set a, (b, c) = ... %}` assigns and holds no body.
            if kind != "set" or not _INLINE_SET.match(text):
                stack.append((kind, tag.end))
        elif stack and stack[-1][0] == kind:
            _, body_start = stack.pop()
            if not stack:
                spans.append((body_start, tag.start, kind))
    return spans


def _tag_holding(tags: list[Any], starts: list[int], pos: int) -> Any:
    """The tag whose span holds the line end at *pos*, if any."""
    index = bisect.bisect_right(starts, pos) - 1
    if index >= 0 and tags[index].start < pos < tags[index].end:
        return tags[index]
    return None


def render_workflow_source(yaml_file: Path, project_root: Path) -> RenderedWorkflow:
    """Render *yaml_file* with the load step of `agac` only: no prompt fill, no versions, no writes."""
    raw = yaml_file.read_text(encoding="utf-8")
    try:
        source = _load_yaml_content(yaml_file, project_root=project_root)
    except ConfigurationError as e:
        raise WorkflowRenderError(f"{e} ({raw.strip()})", 0) from e
    text, _ = _render(LoadRender, source, yaml_file, project_root)
    data, nodes = _parse(text, source)
    if source != raw:
        # The workflow is a prompt store entry; its lines are not the lines of this file.
        return RenderedWorkflow(text=text, data=data, action_sources={})
    try:
        marked, load = _render(MarkingLoadRender, source, yaml_file, project_root)
    except WorkflowRenderError as e:
        # The plain render passed, so only a mark broke this one.
        logger.warning("Could not map actions of %s to source lines: %s", yaml_file, e.message)
        return _unmapped(text, data, source)
    marked_lines = _LINE_BREAK.split(marked)
    if not _same_text(marked_lines, _LINE_BREAK.split(text)):
        # A mark changed what the render output, so no mark can be trusted.
        logger.warning("Could not map actions of %s to source lines: the renders differ", yaml_file)
        return _unmapped(text, data, source)

    source_lines = source.split("\n")
    sources, action_lines = _action_sources(
        nodes, marked_lines, yaml_file, project_root, source_lines
    )
    written = _lines_as_written(marked_lines, source_lines, yaml_file.name)
    live_lines = None
    if any(opener in source for opener in _JINJA_OPENERS):
        live_lines = frozenset({line for _, line in written} | action_lines)
    return RenderedWorkflow(
        text=text,
        data=data,
        action_sources=sources,
        action_lines=frozenset(action_lines),
        live_lines=live_lines,
        line_owners=_line_owners(nodes, written),
    )


def _unmapped(text: str, data: dict, source: str) -> RenderedWorkflow:
    """The render with no source map; no line is read where a tag can change one."""
    if any(opener in source for opener in _JINJA_OPENERS):
        return RenderedWorkflow(text, data, {}, action_lines=frozenset(), live_lines=frozenset())
    return RenderedWorkflow(text, data, {})


def _lines_as_written(
    marked_lines: list[str], source_lines: list[str], origin: str
) -> list[tuple[int, int]]:
    """Each (rendered line, workflow line) where the render output the workflow line as written.

    A filter, a `caller()` filter or a tag on the line can change the text around a mark;
    such a line is not read, because its words are not what the render made of it.
    """
    found = []
    for rendered_line, marked in enumerate(marked_lines):
        text = _MARK_TEXT.sub("", marked).rstrip()
        for mark_origin, line in _LINE_MARK.findall(marked):
            i = int(line)
            if mark_origin == origin and i < len(source_lines) and source_lines[i].rstrip() == text:
                found.append((rendered_line, i))
    return found


def _line_owners(nodes: list[_ActionNode], written: list[tuple[int, int]]) -> dict[int, str | None]:
    """Each workflow line output as written, and the action whose text it is in the render."""
    owners: dict[int, str | None] = {}
    starts = [node.start_line for node in nodes]
    for rendered_line, line in written:
        index = bisect.bisect_right(starts, rendered_line) - 1
        node = nodes[index] if index >= 0 else None
        owner = None
        if node is not None and (
            rendered_line < node.end_line
            or (rendered_line == node.end_line and node.end_column > 0)
        ):
            owner = node.name
        owners[line] = owner if owners.get(line, owner) == owner else None
    return owners


def _same_text(marked_lines: list[str], lines: list[str]) -> bool:
    """True when the marked render, without its marks, is the plain render."""
    return len(marked_lines) == len(lines) and all(
        _MARK_TEXT.sub("", marked).rstrip() == line.rstrip()
        for marked, line in zip(marked_lines, lines, strict=True)
    )


def _render(
    load_class: type[LoadRender], source: str, yaml_file: Path, project_root: Path
) -> tuple[str, LoadRender]:
    try:
        load = new_load_render(source, project_root / "templates", project_root, load_class)
    except TemplateRenderingError as e:
        context = getattr(e, "context", None) or {}
        detail = context.get("message") or str(e)
        where = context.get("template_file")
        raise WorkflowRenderError(f"{detail} (templates/{where})" if where else detail, 0) from e
    try:
        return textwrap.dedent(load.render(source, yaml_file.name)), load
    except jinja2.TemplateSyntaxError as e:
        if e.name is None and e.lineno:
            raise WorkflowRenderError(e.message or str(e), e.lineno - 1) from e
        raise WorkflowRenderError(f"{e.message} (templates/{e.name} line {e.lineno})", 0) from e
    except jinja2.TemplateError as e:
        raise WorkflowRenderError(f"{e}{load.explain(e)}", 0) from e
    except Exception as e:
        # agac fails the load on any error the render raises: a missing prompt file, a
        # type error in an expression. The editor reports it the same way.
        raise WorkflowRenderError(f"{type(e).__name__}: {e}", 0) from e


def _parse(text: str, source: str) -> tuple[dict, list[_ActionNode]]:
    """The data of *text*, read with the loader `agac` uses, and where each action sits in it."""
    loader = yaml.SafeLoader(text)
    try:
        root = loader.get_single_node()
        data = loader.construct_document(root) if root is not None else None
    except yaml.YAMLError as e:
        raise _yaml_error(e, source) from e
    finally:
        loader.dispose()
    if data is None:
        return {}, []
    if not isinstance(data, dict):
        raise WorkflowRenderError("Workflow is not a mapping", 0)
    return data, _action_nodes(root)


def _yaml_error(error: yaml.YAMLError, source: str) -> WorkflowRenderError:
    mark = getattr(error, "problem_mark", None)
    problem = getattr(error, "problem", None) or str(error)
    if mark is None:
        return WorkflowRenderError(problem, 0)
    if any(opener in source for opener in _JINJA_OPENERS):
        # Rendered lines do not match the file once a tag has rendered.
        return WorkflowRenderError(f"{problem} (line {mark.line + 1} of the rendered workflow)", 0)
    return WorkflowRenderError(problem, mark.line)


def _action_sources(
    nodes: list[_ActionNode],
    marked_lines: list[str],
    yaml_file: Path,
    project_root: Path,
    source_lines: list[str],
) -> tuple[dict[str, Location], set[int]]:
    """Each action's mark, read on the rendered line that holds its `name:` key.

    A filter can change the text of a mark, so a mark counts only when it names the
    workflow file or a template that exists, at a `name:` line.
    """
    sources: dict[str, Location] = {}
    action_lines: set[int] = set()
    seen_on_line: dict[int, int] = {}
    file_lines: dict[str, list[str] | None] = {yaml_file.name: source_lines}

    def names_action(origin: str, line: int, name: str) -> bool:
        if origin not in file_lines:
            path = project_root / origin
            file_lines[origin] = (
                path.read_text(encoding="utf-8").split("\n")
                if origin.startswith("templates/") and path.is_file()
                else None
            )
        lines = file_lines[origin]
        if lines is None or line >= len(lines) or not _NAME_LINE.match(lines[line]):
            return False
        literal = _LITERAL_NAME.match(lines[line])
        return literal is None or literal.group(1) == name

    for node in nodes:
        name, line_no = node.name, node.name_line
        marked = marked_lines[line_no]
        marks = list(_NAME_MARK.finditer(marked))
        nth = seen_on_line.get(line_no, 0)
        seen_on_line[line_no] = nth + 1
        if nth >= len(marks):
            continue
        origin, src_line, column = marks[nth].groups()
        line, col = int(src_line), int(column)
        if _MARK_TEXT.sub("", marked[marks[nth].end() :]).strip():
            # A tag pulled the next line up after the mark, so the name went on past it.
            continue
        if not names_action(origin, line, name):
            continue
        in_workflow = origin == yaml_file.name
        if in_workflow:
            action_lines.add(line)
        if name in sources:
            continue
        file_path = yaml_file if in_workflow else project_root / origin
        sources[name] = Location(
            file_path=file_path, line=line, column=col, end_line=line, end_column=col + len(name)
        )
    return sources, action_lines


def _action_nodes(root: Any) -> list[_ActionNode]:
    actions = _value(root, "actions")
    if not isinstance(actions, yaml.SequenceNode):
        return []
    found = []
    for item in actions.value:
        if not isinstance(item, yaml.MappingNode):
            continue
        for key, value in item.value:
            if key.value == "name" and isinstance(value, yaml.ScalarNode) and value.value:
                found.append(
                    _ActionNode(
                        name=str(value.value),
                        name_line=key.start_mark.line,
                        start_line=item.start_mark.line,
                        end_line=item.end_mark.line,
                        end_column=item.end_mark.column,
                    )
                )
                break
    return found


def _value(node: Any, key: str) -> Any:
    if not isinstance(node, yaml.MappingNode):
        return None
    for k, v in node.value:
        if isinstance(k, yaml.ScalarNode) and k.value == key:
            return v
    return None
