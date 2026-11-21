"""Render a workflow file for the editor, the way `agac` renders it, and map each action to its source line."""

import logging
import re
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import jinja2
import yaml
from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError as RuamelYAMLError

from agent_actions.errors import TemplateRenderingError
from agent_actions.prompt.deferred_values import LoadRender
from agent_actions.prompt.render_workflow import new_load_render

from .models import Location

logger = logging.getLogger(__name__)

_NAME_LINE = re.compile(r"^\s*(?:-\s+)?name:[ \t]*(?=\S)")
_MARK = re.compile(r"  # @src (\S+):(\d+):(\d+)")
_JINJA_OPENERS = ("{{", "{%", "{#")
_PAIRS = (("{{", "}}"), ("{%", "%}"), ("{#", "#}"))


class WorkflowRenderError(Exception):
    """A workflow that does not render; *line* is 0-indexed in the workflow file."""

    def __init__(self, message: str, line: int = 0) -> None:
        super().__init__(message)
        self.message = message
        self.line = line


@dataclass
class RenderedWorkflow:
    text: str
    data: dict
    action_sources: dict[str, Location]


class MarkingLoadRender(LoadRender):
    """Tags each `name:` line with the file and line it came from, as a YAML comment."""

    def wrap(self, source: str, origin: str) -> str:
        source = source.replace("\r\n", "\n").replace("\r", "\n")
        lines = source.split("\n")
        for i, line in enumerate(lines):
            match = _NAME_LINE.match(line)
            # A mark inside a tag that spans lines would be Jinja, not a YAML comment.
            if match and all(line.count(a) == line.count(b) for a, b in _PAIRS):
                column = match.end() + (line[match.end()] in "'\"")
                lines[i] = f"{line.rstrip()}  # @src {origin}:{i}:{column}"
        return super().wrap("\n".join(lines), origin)


def render_workflow_source(yaml_file: Path, project_root: Path) -> RenderedWorkflow:
    """Render *yaml_file* with the load step of `agac` only: no prompt fill, no versions, no writes."""
    source = yaml_file.read_text(encoding="utf-8")
    text = _render(LoadRender, source, yaml_file, project_root)
    try:
        data = YAML(typ="safe").load(text)
    except RuamelYAMLError as e:
        raise _yaml_error(e, source) from e
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise WorkflowRenderError("Workflow is not a mapping", 0)
    try:
        marked = _render(MarkingLoadRender, source, yaml_file, project_root)
    except WorkflowRenderError as e:
        # The plain render passed, so only a mark broke this one; locations fall back.
        logger.warning("Could not map actions of %s to source lines: %s", yaml_file, e.message)
        return RenderedWorkflow(text=text, data=data, action_sources={})
    sources = _action_sources(text, marked, yaml_file, project_root)
    return RenderedWorkflow(text=text, data=data, action_sources=sources)


def _render(load_class: type[LoadRender], source: str, yaml_file: Path, project_root: Path) -> str:
    try:
        load = new_load_render(source, project_root / "templates", project_root, load_class)
    except TemplateRenderingError as e:
        context = getattr(e, "context", None) or {}
        detail = context.get("message") or str(e)
        where = context.get("template_file")
        raise WorkflowRenderError(f"{detail} (templates/{where})" if where else detail, 0) from e
    try:
        return textwrap.dedent(load.render(source, yaml_file.name))
    except jinja2.TemplateSyntaxError as e:
        if e.name is None and e.lineno:
            raise WorkflowRenderError(e.message or str(e), e.lineno - 1) from e
        raise WorkflowRenderError(f"{e.message} (templates/{e.name} line {e.lineno})", 0) from e
    except jinja2.TemplateError as e:
        raise WorkflowRenderError(f"{e}{load.explain(e)}", 0) from e


def _yaml_error(error: RuamelYAMLError, source: str) -> WorkflowRenderError:
    mark = getattr(error, "problem_mark", None)
    problem = getattr(error, "problem", None) or str(error)
    if mark is None:
        return WorkflowRenderError(problem, 0)
    if any(opener in source for opener in _JINJA_OPENERS):
        # Rendered lines do not match the file once a tag has rendered.
        return WorkflowRenderError(f"{problem} (line {mark.line + 1} of the rendered workflow)", 0)
    return WorkflowRenderError(problem, mark.line)


def _action_sources(
    text: str, marked: str, yaml_file: Path, project_root: Path
) -> dict[str, Location]:
    """Each action's mark, read on the rendered line that holds its `name:` key."""
    marked_lines = marked.split("\n")
    sources: dict[str, Location] = {}
    seen_on_line: dict[int, int] = {}
    for line_no, name in _action_name_lines(text):
        marks = _MARK.findall(marked_lines[line_no]) if line_no < len(marked_lines) else []
        nth = seen_on_line.get(line_no, 0)
        seen_on_line[line_no] = nth + 1
        if nth >= len(marks) or name in sources:
            continue
        origin, src_line, column = marks[nth]
        file_path = project_root / origin if origin.startswith("templates/") else yaml_file
        line, col = int(src_line), int(column)
        sources[name] = Location(
            file_path=file_path, line=line, column=col, end_line=line, end_column=col + len(name)
        )
    return sources


def _action_name_lines(text: str) -> list[tuple[int, str]]:
    loader: Any = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
    root = yaml.compose(text, Loader=loader)
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
