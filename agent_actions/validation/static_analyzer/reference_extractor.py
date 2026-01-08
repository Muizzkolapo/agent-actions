"""
Extract field references from agent configurations.
"""

import re
from typing import Any, Dict, List, Optional, Set

from jinja2 import Environment, nodes
from jinja2.exceptions import TemplateSyntaxError

from .data_flow_graph import InputRequirement


class ReferenceExtractor:
    """Extracts field references from agent prompts, guards, and directives.

    Uses Jinja2's AST parser to properly handle:
    - Variable references: {{ agent.field }}
    - Loop variables: {% for item in items %} - automatically excluded
    - Nested expressions and filters

    Also supports:
    - Simple brace style: {agent.field}
    - Guard expressions: agent.field > 5
    - Context scope directives: agent.field

    Example:
        extractor = ReferenceExtractor()

        requirements = extractor.extract_from_agent({
            'name': 'summarizer',
            'prompt': 'Summarize: {{ action.extractor.summary }}',
            'guard': 'extractor.count > 0',
            'context_scope': {'observe': ['extractor.facts']}
        })

        for req in requirements:
            print(f"{req.source_agent}.{req.field_path}")
        # extractor.summary
        # extractor.count
        # extractor.facts
    """

    # Matches {action.agent.field} or {agent.field} (simple brace style)
    SIMPLE_ACTION_PATTERN = re.compile(r"\{action\.([a-zA-Z_][a-zA-Z0-9_]*)\.([a-zA-Z0-9_.]+)\}")
    SIMPLE_DIRECT_PATTERN = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\.([a-zA-Z0-9_.]+)\}")

    # Matches dot notation in guards: agent.field
    DOT_PATTERN = re.compile(r"\b([a-zA-Z_][a-zA-Z0-9_]*)\.([a-zA-Z0-9_.]+)")

    # Special namespaces that don't require dependency declaration
    SPECIAL_NAMESPACES = frozenset({"source", "loop", "workflow", "seed", "action"})

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

    def extract_from_agent(self, agent_config: Dict[str, Any]) -> List[InputRequirement]:
        """Extract all field references from an agent configuration.

        Args:
            agent_config: Agent configuration dictionary

        Returns:
            List of InputRequirement objects
        """
        requirements: List[InputRequirement] = []
        agent_name = agent_config.get("name", "unknown")

        # Extract from prompt
        prompt = agent_config.get("prompt", "")
        if prompt:
            requirements.extend(self._extract_from_template(prompt, agent_name, "prompt"))

        # Extract from guard
        guard = agent_config.get("guard")
        if guard:
            requirements.extend(self._extract_from_guard(guard, agent_name))

        # Extract from context_scope directives
        context_scope = agent_config.get("context_scope", {})
        for directive, refs in context_scope.items():
            if isinstance(refs, list):
                requirements.extend(
                    self._extract_from_context_scope(refs, agent_name, f"context_scope.{directive}")
                )

        # Extract from loop items_from
        loop = agent_config.get("loop", {})
        items_from = loop.get("items_from", "")
        if items_from:
            requirements.extend(
                self._extract_from_template(str(items_from), agent_name, "loop.items_from")
            )

        # Extract from conditional_clause
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
    ) -> List[InputRequirement]:
        """Extract references from Jinja2 template using AST parsing.

        Uses Jinja2's AST to properly handle loop variables and nested expressions.
        Falls back to simple brace pattern matching for non-Jinja syntax.
        """
        requirements: List[InputRequirement] = []
        seen: Set[str] = set()

        # Parse with Jinja2 AST to extract references properly
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

        # Also check simple brace patterns: {action.agent.field} or {agent.field}
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

    def _extract_jinja_references(self, template: str) -> List[tuple]:
        """Extract variable references from Jinja2 template using AST.

        Walks the AST to find all Getattr nodes (dot notation access)
        and properly excludes loop variables defined in for-loops.

        Returns:
            List of (source, field, raw_reference) tuples
        """
        references: List[tuple] = []

        try:
            ast = self._env.parse(template)
        except TemplateSyntaxError:
            # If template has syntax errors, fall back to empty (simple patterns will catch it)
            return references

        # Walk AST to find variable references
        self._walk_ast(ast, references, local_vars=set())
        return references

    def _walk_ast(
        self,
        node: nodes.Node,
        references: List[tuple],
        local_vars: Set[str],
    ) -> None:
        """Recursively walk AST to extract variable references.

        Args:
            node: Current AST node
            references: List to append (source, field, raw_ref) tuples
            local_vars: Set of locally-defined variable names (loop vars, etc.)
        """
        # Handle For loops - add loop variable to local_vars
        if isinstance(node, nodes.For):
            new_locals = local_vars.copy()
            # Extract loop variable name(s)
            target = node.target
            if isinstance(target, nodes.Name):
                new_locals.add(target.name)
            elif isinstance(target, nodes.Tuple):
                for item in target.items:
                    if isinstance(item, nodes.Name):
                        new_locals.add(item.name)

            # Walk child nodes with updated local_vars
            for child in node.iter_child_nodes():
                self._walk_ast(child, references, new_locals)
            return

        # Handle Getattr (dot notation): {{ agent.field }}
        if isinstance(node, nodes.Getattr):
            ref = self._extract_getattr_chain(node)
            if ref:
                source, field_path = ref
                # Skip if source is a local variable, builtin, or "action" prefix
                if source not in local_vars and source not in self.JINJA_BUILTINS:
                    # Handle action.agent.field -> (agent, field)
                    if source == "action" and "." in field_path:
                        parts = field_path.split(".", 1)
                        source = parts[0]
                        field_path = parts[1]
                    raw_ref = f"{{{{ {source}.{field_path} }}}}"
                    references.append((source, field_path, raw_ref))
            # Don't recurse into Getattr children - we already extracted the full chain
            return

        # Recurse into child nodes
        for child in node.iter_child_nodes():
            self._walk_ast(child, references, local_vars)

    def _extract_getattr_chain(self, node: nodes.Getattr) -> Optional[tuple]:
        """Extract the full attribute chain from a Getattr node.

        Handles chains like: agent.field.subfield -> ('agent', 'field.subfield')

        Returns:
            (root_name, attribute_path) tuple or None if not a simple chain
        """
        attrs = [node.attr]
        current = node.node

        # Walk up the chain collecting attributes
        while isinstance(current, nodes.Getattr):
            attrs.append(current.attr)
            current = current.node

        # Root should be a Name node
        if isinstance(current, nodes.Name):
            root = current.name
            # Reverse attrs to get correct order (we collected bottom-up)
            attrs.reverse()
            return (root, ".".join(attrs))

        return None

    def _extract_from_guard(
        self,
        guard: Any,
        _agent_name: str,
        location: str = "guard",
    ) -> List[InputRequirement]:
        """Extract references from guard expression."""
        requirements: List[InputRequirement] = []

        if isinstance(guard, str):
            # String guard - extract dot notation references
            seen: Set[str] = set()
            for match in self.DOT_PATTERN.finditer(guard):
                source = match.group(1)
                field = match.group(2)
                ref_key = f"{source}.{field}"

                # Skip Python keywords and operators
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
            # Dict guard - check field references
            field = guard.get("field", "")
            if "." in str(field):
                parts = str(field).split(".", 1)
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
        references: List[str],
        _agent_name: str,
        location: str,
    ) -> List[InputRequirement]:
        """Extract from context_scope directive (observe, drop, passthrough)."""
        requirements: List[InputRequirement] = []

        for ref in references:
            if not isinstance(ref, str):
                continue

            if "." in ref:
                parts = ref.split(".", 1)
                if len(parts) >= 2:
                    source = parts[0]
                    field = parts[1]

                    # Handle nested paths
                    if "." in field:
                        field = field.split(".")[0]

                    requirements.append(
                        InputRequirement(
                            source_agent=source,
                            field_path=field,
                            raw_reference=ref,
                            location=location,
                        )
                    )

        return requirements

    def get_referenced_agents(self, requirements: List[InputRequirement]) -> Set[str]:
        """Get set of all agents referenced (excluding special namespaces).

        Args:
            requirements: List of input requirements

        Returns:
            Set of agent names that are referenced
        """
        agents: Set[str] = set()
        for req in requirements:
            if req.source_agent not in self.SPECIAL_NAMESPACES:
                agents.add(req.source_agent)
        return agents

    def extract_from_workflow(
        self,
        workflow_config: Dict[str, Any],
    ) -> Dict[str, List[InputRequirement]]:
        """Extract references from all agents in a workflow.

        Args:
            workflow_config: Full workflow configuration

        Returns:
            Dict mapping agent names to their input requirements
        """
        requirements: Dict[str, List[InputRequirement]] = {}

        actions = workflow_config.get("actions", [])
        for action in actions:
            name = action.get("name", "unknown")
            requirements[name] = self.extract_from_agent(action)

        return requirements
