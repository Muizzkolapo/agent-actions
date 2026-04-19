"""Extract field references from action configurations."""

import re
from typing import Any

from jinja2 import Environment, nodes
from jinja2.exceptions import TemplateSyntaxError

from agent_actions.utils.constants import SPECIAL_NAMESPACES

from .data_flow_graph import InputRequirement


class ReferenceExtractor:
    """Extracts field references from action prompts, guards, and directives."""

    # Matches {action.action_name.field} or {action_name.field} (simple brace style)
    SIMPLE_ACTION_PATTERN = re.compile(r"\{action\.([a-zA-Z_][a-zA-Z0-9_]*)\.([a-zA-Z0-9_.]+)\}")
    SIMPLE_DIRECT_PATTERN = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\.([a-zA-Z0-9_.]+)\}")

    # Matches dot notation in guards: action.field
    DOT_PATTERN = re.compile(r"\b([a-zA-Z_][a-zA-Z0-9_]*)\.([a-zA-Z0-9_.]+)")
    ACTION_DOT_PATTERN = re.compile(r"\baction\.([a-zA-Z_][a-zA-Z0-9_]*)\.([a-zA-Z0-9_.]+)")

    # Jinja2 builtins to skip
    JINJA_BUILTINS = frozenset(
        {
            "range",
            "dict",
            "lipsum",
            "cycler",
            "joiner",
            "namespace",
            "true",
            "false",
            "none",
        }
    )

    def __init__(self) -> None:
        """Initialize with a Jinja2 environment for AST parsing."""
        self._env = Environment()

    def extract_from_agent(self, agent_config: dict[str, Any]) -> list[InputRequirement]:
        """Extract all field references from an action configuration."""
        requirements: list[InputRequirement] = []
        agent_name = agent_config.get("name", "unknown")

        prompt = agent_config.get("prompt", "")
        if prompt:
            requirements.extend(self._extract_from_template(prompt, agent_name, "prompt"))

        guard = agent_config.get("guard")
        if guard:
            requirements.extend(self._extract_from_guard(guard, agent_name))

        context_scope = agent_config.get("context_scope", {})
        for directive, refs in context_scope.items():
            if isinstance(refs, list):
                requirements.extend(
                    self._extract_from_context_scope(refs, agent_name, f"context_scope.{directive}")
                )

        versions = agent_config.get("versions", {})
        items_from = versions.get("items_from", "")
        if items_from:
            requirements.extend(
                self._extract_from_template(str(items_from), agent_name, "versions.items_from")
            )

        conditional = agent_config.get("conditional_clause", "")
        if conditional:
            requirements.extend(
                self._extract_from_guard(conditional, agent_name, "conditional_clause")
            )

        return requirements

    def _extract_from_template(
        self,
        template: str,
        _agent_name: str,
        location: str,
    ) -> list[InputRequirement]:
        """Extract references from Jinja2 template using AST parsing."""
        requirements: list[InputRequirement] = []
        seen: set[str] = set()

        jinja_refs = self._extract_jinja_references(template)
        for source, field, raw_ref in jinja_refs:
            ref_key = f"{source}.{field}"
            if ref_key not in seen:
                seen.add(ref_key)
                requirements.append(
                    InputRequirement(
                        source_agent=source,
                        field_path=field,
                        raw_reference=raw_ref,
                        location=location,
                    )
                )

        for match in self.SIMPLE_ACTION_PATTERN.finditer(template):
            source = match.group(1)
            field = match.group(2)
            ref_key = f"{source}.{field}"
            if ref_key not in seen:
                seen.add(ref_key)
                requirements.append(
                    InputRequirement(
                        source_agent=source,
                        field_path=field,
                        raw_reference=match.group(0),
                        location=location,
                    )
                )

        for match in self.SIMPLE_DIRECT_PATTERN.finditer(template):
            source = match.group(1)
            field = match.group(2)
            ref_key = f"{source}.{field}"
            if ref_key not in seen and source != "action":
                seen.add(ref_key)
                requirements.append(
                    InputRequirement(
                        source_agent=source,
                        field_path=field,
                        raw_reference=match.group(0),
                        location=location,
                    )
                )

        return requirements

    def _extract_jinja_references(self, template: str) -> list[tuple]:
        """Extract variable references from Jinja2 template using AST."""
        references: list[tuple] = []

        try:
            ast = self._env.parse(template)
        except TemplateSyntaxError:
            # If template has syntax errors, fall back to empty (simple patterns will catch it)
            return references

        self._walk_ast(ast, references, local_vars=set())
        return references

    def _walk_ast(
        self,
        node: nodes.Node,
        references: list[tuple],
        local_vars: set[str],
    ) -> None:
        """Recursively walk AST to extract variable references."""
        if isinstance(node, nodes.For):
            new_locals = local_vars.copy()
            target = node.target
            if isinstance(target, nodes.Name):
                new_locals.add(target.name)
            elif isinstance(target, nodes.Tuple):
                for item in target.items:
                    if isinstance(item, nodes.Name):
                        new_locals.add(item.name)

            for child in node.iter_child_nodes():
                self._walk_ast(child, references, new_locals)
            return

        # {% set %} introduces a name at the current scope level — mutate in place
        # so subsequent siblings (processed by the parent's loop) see it
        if isinstance(node, nodes.Assign):
            if isinstance(node.target, nodes.Name):
                local_vars.add(node.target.name)
            for child in node.iter_child_nodes():
                self._walk_ast(child, references, local_vars)
            return

        if isinstance(node, nodes.Macro):
            new_locals = local_vars.copy()
            for arg in node.args:
                if isinstance(arg, nodes.Name):
                    new_locals.add(arg.name)
            for child in node.iter_child_nodes():
                self._walk_ast(child, references, new_locals)
            return

        if isinstance(node, nodes.Getattr):
            ref = self._extract_getattr_chain(node)
            if ref:
                source, field_path = ref
                if source not in local_vars and source not in self.JINJA_BUILTINS:
                    if source == "action" and "." in field_path:
                        parts = field_path.split(".", 1)
                        source = parts[0]
                        field_path = parts[1]
                    raw_ref = f"{{{{ {source}.{field_path} }}}}"
                    references.append((source, field_path, raw_ref))
            return

        for child in node.iter_child_nodes():
            self._walk_ast(child, references, local_vars)

    def _extract_getattr_chain(self, node: nodes.Getattr) -> tuple | None:
        """Extract the full attribute chain from a Getattr node."""
        attrs = [node.attr]
        current = node.node

        while isinstance(current, nodes.Getattr):
            attrs.append(current.attr)
            current = current.node

        if isinstance(current, nodes.Name):
            root = current.name
            attrs.reverse()
            return (root, ".".join(attrs))

        return None

    def _extract_from_guard(
        self,
        guard: Any,
        _agent_name: str,
        location: str = "guard",
    ) -> list[InputRequirement]:
        """Extract references from guard expression."""
        requirements: list[InputRequirement] = []

        if isinstance(guard, str):
            seen: set[str] = set()
            action_spans = []
            for match in self.ACTION_DOT_PATTERN.finditer(guard):
                source = match.group(1)
                field = match.group(2)
                ref_key = f"{source}.{field}"
                if ref_key not in seen:
                    seen.add(ref_key)
                    requirements.append(
                        InputRequirement(
                            source_agent=source,
                            field_path=field,
                            raw_reference=match.group(0),
                            location=location,
                        )
                    )
                action_spans.append(match.span())

            for match in self.DOT_PATTERN.finditer(guard):
                if any(start <= match.start() < end for start, end in action_spans):
                    continue
                source = match.group(1)
                field = match.group(2)
                ref_key = f"{source}.{field}"

                if source in {"and", "or", "not", "in", "is", "True", "False", "None"}:
                    continue

                if ref_key not in seen:
                    seen.add(ref_key)
                    requirements.append(
                        InputRequirement(
                            source_agent=source,
                            field_path=field,
                            raw_reference=f"{source}.{field}",
                            location=location,
                        )
                    )
        elif isinstance(guard, dict):
            field = guard.get("field", "")
            field_value = str(field)
            if field_value.startswith("action."):
                field_value = field_value[len("action.") :]
            if "." in field_value:
                parts = field_value.split(".", 1)
                if len(parts) >= 2:
                    requirements.append(
                        InputRequirement(
                            source_agent=parts[0],
                            field_path=parts[1],
                            raw_reference=str(field),
                            location=f"{location}.field",
                        )
                    )

        return requirements

    def _extract_from_context_scope(
        self,
        references: list[str],
        _agent_name: str,
        location: str,
    ) -> list[InputRequirement]:
        """Extract from context_scope directive (observe, drop, passthrough)."""
        requirements: list[InputRequirement] = []

        for ref in references:
            if not isinstance(ref, str):
                continue  # type: ignore[unreachable]

            if "." in ref:
                original_ref = ref
                if ref.startswith("action."):
                    ref = ref[len("action.") :]
                parts = ref.split(".", 1)
                if len(parts) >= 2:
                    source = parts[0]
                    field = parts[1]

                    requirements.append(
                        InputRequirement(
                            source_agent=source,
                            field_path=field,
                            raw_reference=original_ref,
                            location=location,
                        )
                    )

        return requirements

    def get_referenced_agents(self, requirements: list[InputRequirement]) -> set[str]:
        """Get set of all actions referenced (excluding special namespaces)."""
        agents: set[str] = set()
        for req in requirements:
            if req.source_agent not in SPECIAL_NAMESPACES:
                agents.add(req.source_agent)
        return agents

    def extract_from_workflow(
        self,
        workflow_config: dict[str, Any],
    ) -> dict[str, list[InputRequirement]]:
        """Extract references from all actions in a workflow."""
        requirements: dict[str, list[InputRequirement]] = {}

        actions = workflow_config.get("actions", [])
        for action in actions:
            name = action.get("name", "unknown")
            requirements[name] = self.extract_from_agent(action)

        return requirements
