"""Extract field references from agent configurations.

Parses templates, guards, and context_scope directives to extract
all field references that an agent requires from upstream agents.
"""

import re
from typing import Any, Dict, List, Set

from .data_flow_graph import InputRequirement


class ReferenceExtractor:
    """Extracts field references from agent prompts, guards, and directives.

    Recognizes multiple reference styles:
    - Jinja2 style: {{ action.field }} or {{ action.extractor.summary }}
    - Simple style: {action.field} or {extractor.summary}
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

    # Patterns for different reference styles
    # Matches {{ action.agent.field }} or {{ agent.field }}
    JINJA_ACTION_PATTERN = re.compile(
        r"\{\{\s*action\.([a-zA-Z_][a-zA-Z0-9_]*)\.([a-zA-Z0-9_.]+)\s*\}\}"
    )
    JINJA_DIRECT_PATTERN = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\.([a-zA-Z0-9_.]+)\s*\}\}")

    # Matches {action.agent.field} or {agent.field}
    SIMPLE_ACTION_PATTERN = re.compile(r"\{action\.([a-zA-Z_][a-zA-Z0-9_]*)\.([a-zA-Z0-9_.]+)\}")
    SIMPLE_DIRECT_PATTERN = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\.([a-zA-Z0-9_.]+)\}")

    # Matches dot notation in guards: agent.field
    DOT_PATTERN = re.compile(r"\b([a-zA-Z_][a-zA-Z0-9_]*)\.([a-zA-Z0-9_.]+)")

    # Special namespaces that don't require dependency declaration
    SPECIAL_NAMESPACES = frozenset({"source", "loop", "workflow", "seed", "action"})

    # Jinja2 control keywords to skip
    JINJA_KEYWORDS = frozenset(
        {"if", "else", "elif", "endif", "for", "endfor", "set", "block", "endblock", "macro"}
    )

    # Pattern to extract loop variables from {% for VAR in ... %}
    JINJA_FOR_LOOP_PATTERN = re.compile(r"\{%\s*for\s+(\w+)\s+in\s+")

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

    def _extract_loop_variables(self, template: str) -> Set[str]:
        """Extract loop variable names from Jinja for-loops.

        Finds variables defined in {% for VAR in ... %} statements.
        These are local variables, not external references.
        """
        loop_vars: Set[str] = set()
        for match in self.JINJA_FOR_LOOP_PATTERN.finditer(template):
            loop_vars.add(match.group(1))
        return loop_vars

    def _extract_from_template(
        self,
        template: str,
        _agent_name: str,
        location: str,
    ) -> List[InputRequirement]:
        """Extract references from Jinja2/simple template."""
        requirements: List[InputRequirement] = []
        seen: Set[str] = set()

        # Extract loop variables - these are local, not external references
        loop_variables = self._extract_loop_variables(template)

        # Try Jinja2 action pattern: {{ action.agent.field }}
        for match in self.JINJA_ACTION_PATTERN.finditer(template):
            source = match.group(1)
            field = match.group(2)
            ref_key = f"{source}.{field}"
            # Skip loop variables and Jinja keywords
            if (
                ref_key not in seen
                and source not in self.JINJA_KEYWORDS
                and source not in loop_variables
            ):
                seen.add(ref_key)
                requirements.append(
                    InputRequirement(
                        source_agent=source,
                        field_path=field,
                        raw_reference=match.group(0),
                        location=location,
                    )
                )

        # Try Jinja2 direct pattern: {{ agent.field }}
        for match in self.JINJA_DIRECT_PATTERN.finditer(template):
            source = match.group(1)
            field = match.group(2)
            ref_key = f"{source}.{field}"
            # Skip loop variables, Jinja keywords, and 'action' (handled above)
            if (
                ref_key not in seen
                and source not in self.JINJA_KEYWORDS
                and source not in loop_variables
            ):
                if source != "action":
                    seen.add(ref_key)
                    requirements.append(
                        InputRequirement(
                            source_agent=source,
                            field_path=field,
                            raw_reference=match.group(0),
                            location=location,
                        )
                    )

        # Try simple action pattern: {action.agent.field}
        for match in self.SIMPLE_ACTION_PATTERN.finditer(template):
            source = match.group(1)
            field = match.group(2)
            ref_key = f"{source}.{field}"
            # Skip loop variables
            if ref_key not in seen and source not in loop_variables:
                seen.add(ref_key)
                requirements.append(
                    InputRequirement(
                        source_agent=source,
                        field_path=field,
                        raw_reference=match.group(0),
                        location=location,
                    )
                )

        # Try simple direct pattern: {agent.field}
        for match in self.SIMPLE_DIRECT_PATTERN.finditer(template):
            source = match.group(1)
            field = match.group(2)
            ref_key = f"{source}.{field}"
            # Skip loop variables and 'action'
            if ref_key not in seen and source != "action" and source not in loop_variables:
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
