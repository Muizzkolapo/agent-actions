"""Render a workflow file for the editor, the way `agac` renders it, and map each action to its source line."""

import bisect
import logging
import re
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import jinja2
import yaml

from agent_actions.errors import ConfigurationError, TemplateRenderingError
from agent_actions.prompt.deferred_values import _INLINE_SET, LoadRender, _scan
from agent_actions.prompt.render_workflow import _load_yaml_content, new_load_render

from .models import Location

logger = logging.getLogger(__name__)

_NAME_LINE = re.compile(r"^\s*(?:-\s+)?name:[ \t]*(?=\S)")
_NAME_MARK = re.compile(r"  # @src (\S+?):(\d+):(\d+)")
_ANY_MARK = re.compile(r"  # @(?:src|at) (\S+?):(\d+)")
_MARK_TEXT = re.compile(r"  # @(?:src|at) \S+?:\d+(?::\d+)?")
# The line breaks PyYAML counts in a node's line number.
_LINE_BREAK = re.compile(r"\r\n|[\r\n\x85\u2028\u2029]")
# A tag that strips the whitespace after it would strip nothing once a mark follows it.
_STRIPS_AFTER = ("-}}", "-%}", "-#}")
_CONTROL_OPENERS = ("{%", "{#")
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
    holds the workflow-file lines whose text reached the render; it is None when no tag
    can remove a line. Both are None when the marked render could not be read.
    """

    text: str
    data: dict
    action_sources: dict[str, Location]
    action_lines: frozenset[int] | None = None
    live_lines: frozenset[int] | None = None


class MarkingLoadRender(LoadRender):
    """Tags source lines with the file and line they came from, as YAML comments.

    Each `name:` line gets `# @src <origin>:<line>:<column>`; each other line of the
    workflow file that is output where it is written gets `# @at <origin>:<line>`, so a
    line that a tag removes is the line whose mark is missing from the output.
    """

    def __init__(self, templates_folder: Path, workflow: str) -> None:
        super().__init__(templates_folder, workflow)
        # Lines of the workflow file left unmarked but still output as written.
        self.unmarked_output: set[int] = set()
        # The body lines of each `filter` block, and the line that closes it: the body is
        # output where the closing line is output.
        self.filter_bodies: list[tuple[range, int]] = []

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
        if in_workflow:
            for body_start, close_start, kind in values:
                if kind == "filter":
                    self.filter_bodies.append(
                        (
                            range(
                                _line_of(line_starts, body_start),
                                _line_of(line_starts, close_start),
                            ),
                            _line_of(line_starts, close_start),
                        )
                    )
        for i, line in enumerate(lines):
            end = line_starts[i] + len(line)
            tag = _tag_holding(tags, starts, end)
            if tag is not None and tag.kind != "raw":
                # A mark inside a tag would be Jinja, not a YAML comment. The text of a raw
                # block is output as written, so a mark in it is a comment.
                continue
            if not line.strip() or line.rstrip().endswith(_STRIPS_AFTER):
                if in_workflow:
                    self.unmarked_output.add(i)
                continue
            if any(start <= end < stop for start, stop, _ in values):
                continue
            match = _NAME_LINE.match(line)
            if match:
                column = match.end() + (line[match.end()] in "'\"")
                lines[i] = f"{line.rstrip()}  # @src {origin}:{i}:{column}"
            elif in_workflow and not any(start <= end < stop for start, stop, _ in macros):
                # A macro body is output where the macro is called, not where it is
                # written, so it gets no line mark and is not live.
                lines[i] = f"{line.rstrip()}  # @at {origin}:{i}"
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


def _line_of(line_starts: list[int], pos: int) -> int:
    return bisect.bisect_right(line_starts, pos) - 1


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
    data, name_lines = _parse(text, source)
    if source != raw:
        # The workflow is a prompt store entry; its lines are not the lines of this file.
        return RenderedWorkflow(text=text, data=data, action_sources={})
    try:
        marked, load = _render(MarkingLoadRender, source, yaml_file, project_root)
    except WorkflowRenderError as e:
        # The plain render passed, so only a mark broke this one; locations fall back.
        logger.warning("Could not map actions of %s to source lines: %s", yaml_file, e.message)
        return RenderedWorkflow(text=text, data=data, action_sources={})
    marked_lines = _LINE_BREAK.split(marked)
    if not _same_text(marked_lines, _LINE_BREAK.split(text)):
        # A mark changed what the render output, so no mark can be trusted.
        logger.warning("Could not map actions of %s to source lines: the renders differ", yaml_file)
        return RenderedWorkflow(text=text, data=data, action_sources={})

    assert isinstance(load, MarkingLoadRender)
    sources, action_lines = _action_sources(name_lines, marked_lines, yaml_file, project_root)
    live_lines = None
    if any(opener in source for opener in _CONTROL_OPENERS):
        live = {
            int(line)
            for marked_line in marked_lines
            for origin, line in _ANY_MARK.findall(marked_line)
            if origin == yaml_file.name
        }
        source_lines = source.split("\n")
        for body, close_line in load.filter_bodies:
            if close_line in live:
                live.update(body)
                # A name line in the body gets no mark, but it defines its action in place.
                action_lines.update(i for i in body if _NAME_LINE.match(source_lines[i]))
        live_lines = frozenset(live | load.unmarked_output)
    return RenderedWorkflow(
        text=text,
        data=data,
        action_sources=sources,
        action_lines=frozenset(action_lines),
        live_lines=live_lines,
    )


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


def _parse(text: str, source: str) -> tuple[dict, list[tuple[int, str]]]:
    """The data of *text*, read with the loader `agac` uses, and each action's name line."""
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
    return data, _action_name_lines(root)


def _yaml_error(error: yaml.YAMLError, source: str) -> WorkflowRenderError:
    mark = getattr(error, "problem_mark", None)
    problem = getattr(error, "problem", None) or str(error)
    if mark is None:
        return WorkflowRenderError(problem, 0)
    if any(opener in source for opener in ("{{", *_CONTROL_OPENERS)):
        # Rendered lines do not match the file once a tag has rendered.
        return WorkflowRenderError(f"{problem} (line {mark.line + 1} of the rendered workflow)", 0)
    return WorkflowRenderError(problem, mark.line)


def _action_sources(
    name_lines: list[tuple[int, str]],
    marked_lines: list[str],
    yaml_file: Path,
    project_root: Path,
) -> tuple[dict[str, Location], set[int]]:
    """Each action's mark, read on the rendered line that holds its `name:` key."""
    sources: dict[str, Location] = {}
    action_lines: set[int] = set()
    seen_on_line: dict[int, int] = {}
    for line_no, name in name_lines:
        marks = _NAME_MARK.findall(marked_lines[line_no])
        nth = seen_on_line.get(line_no, 0)
        seen_on_line[line_no] = nth + 1
        if nth >= len(marks):
            continue
        origin, src_line, column = marks[nth]
        line, col = int(src_line), int(column)
        in_workflow = not origin.startswith("templates/")
        if in_workflow:
            action_lines.add(line)
        if name in sources:
            continue
        file_path = yaml_file if in_workflow else project_root / origin
        sources[name] = Location(
            file_path=file_path, line=line, column=col, end_line=line, end_column=col + len(name)
        )
    return sources, action_lines


def _action_name_lines(root: Any) -> list[tuple[int, str]]:
    actions = _value(root, "actions")
    if not isinstance(actions, yaml.SequenceNode):
        return []
    found = []
    for item in actions.value:
        if not isinstance(item, yaml.MappingNode):
            continue
        for key, value in item.value:
            if key.value == "name" and isinstance(value, yaml.ScalarNode) and value.value:
                found.append((key.start_mark.line, str(value.value)))
                break
    return found


def _value(node: Any, key: str) -> Any:
    if not isinstance(node, yaml.MappingNode):
        return None
    for k, v in node.value:
        if isinstance(k, yaml.ScalarNode) and k.value == key:
            return v
    return None
