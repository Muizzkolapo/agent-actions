"""Extract field references from action configurations."""

import logging
import re
from typing import Any

from jinja2 import Environment, nodes
from jinja2.exceptions import TemplateSyntaxError

logger = logging.getLogger(__name__)

from agent_actions.utils.constants import RESERVED_NAMES_NO_RECORD_HAS, SPECIAL_NAMESPACES
from agent_actions.utils.template_escape import escape_jinja_in_inline_code

from .data_flow_graph import InputRequirement

# A call such as `ns.items()` or `ns.get('x', 'd')` reaches the method of the mapping
# behind `ns`, not a field of that name (see `prompt/jinja_env.py`).
_MAPPING_METHODS = frozenset(name for name in dir(dict) if not name.startswith("_"))


class ReferenceExtractor:
    """Extracts field references from action prompts, guards, and directives.

    A reference is reported under the name it is written with. `action.producer.field`
    reads a name called `action`, which no record carries, so it is reported as
    `action` for the type checker to refuse, not as `producer.field`.
    """

    # Matches {action.action_name.field} or {action_name.field} (simple brace style)
    SIMPLE_ACTION_PATTERN = re.compile(r"\{action\.([a-zA-Z_][a-zA-Z0-9_]*)\.([a-zA-Z0-9_.]+)\}")
    SIMPLE_DIRECT_PATTERN = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\.([a-zA-Z0-9_.]+)\}")

    # Matches dot notation in guards: producer.field
    DOT_PATTERN = re.compile(r"\b([a-zA-Z_][a-zA-Z0-9_]*)\.([a-zA-Z0-9_.]+)")

    # Jinja2 builtins to skip — includes ``loop`` (the implicit loop variable
    # available inside ``{% for %}`` blocks) so that ``{{ loop.index }}`` is
    # not misinterpreted as a reference to an action named "loop".
    JINJA_BUILTINS = frozenset(
        {
            "loop",
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

    def _parse(self, template: str) -> nodes.Template:
        """Parse template after escaping Jinja syntax in inline code spans."""
        return self._env.parse(escape_jinja_in_inline_code(template))

    def extract_from_agent(self, agent_config: dict[str, Any]) -> list[InputRequirement]:
        """Extract all field references from an action configuration."""
        requirements: list[InputRequirement] = []
        agent_name = agent_config.get("name", "unknown")

        prompt = agent_config.get("prompt", "")
        if prompt:
            requirements.extend(
                self._extract_from_template(
                    prompt, agent_name, "prompt", self._promoted_reserved_names(agent_config)
                )
            )

        guard = agent_config.get("guard")
        if guard:
            requirements.extend(self._extract_from_guard_clause(guard, agent_config))
            if isinstance(guard, dict):
                requirements.extend(self._extract_from_guard(guard, agent_name))

        # By shape, not falsiness: `context_scope:` null and a scalar are the same user
        # error, and `or {}` left the second one raising. The graph builder coerces this
        # too; here it is the contract of a public entry point (#1193).
        context_scope = agent_config.get("context_scope")
        if not isinstance(context_scope, dict):
            context_scope = {}
        for directive, refs in context_scope.items():
            if isinstance(refs, list):
                requirements.extend(
                    self._extract_from_context_scope(refs, agent_name, f"context_scope.{directive}")
                )

        conditional = agent_config.get("conditional_clause", "")
        if conditional:
            requirements.extend(
                self._extract_from_guard(conditional, agent_name, "conditional_clause")
            )

        return requirements

    @staticmethod
    def _promoted_reserved_names(agent_config: dict[str, Any]) -> set[str]:
        """Reserved names a version param puts on the record (`versions: {param: schema}`)."""
        # Imported here: scope_builder pulls in the runtime's logging and record stack.
        from agent_actions.prompt.context.scope_builder import VersionNamespaceBuilder

        version_context = agent_config.get("_version_context")
        if not isinstance(version_context, dict):
            return set()
        return (
            VersionNamespaceBuilder.promoted_names(version_context) & RESERVED_NAMES_NO_RECORD_HAS
        )

    def _extract_from_template(
        self,
        template: str,
        _agent_name: str,
        location: str,
        on_the_record: set[str] | None = None,
    ) -> list[InputRequirement]:
        """Extract references from Jinja2 template using AST parsing."""
        requirements: list[InputRequirement] = []
        seen: set[str] = set()

        jinja_refs = self._extract_jinja_references(template, on_the_record or set())
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
            # Single braces are literal text: `{schema.x}` reads nothing.
            if ref_key not in seen and source not in RESERVED_NAMES_NO_RECORD_HAS:
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

    def _extract_jinja_references(
        self, template: str, on_the_record: set[str] | None = None
    ) -> list[tuple]:
        """Extract variable references from Jinja2 template using AST."""
        references: list[tuple] = []

        try:
            ast = self._parse(template)
        except TemplateSyntaxError as e:
            logger.warning(
                "Jinja2 syntax error in template (line %s): %s — Template snippet: %.200s",
                e.lineno,
                e.message,
                template,
            )
            raise

        self._walk_ast(ast, references, local_vars=set(on_the_record or ()))
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

        if (
            isinstance(node, nodes.Call)
            and isinstance(node.node, nodes.Getattr)
            and node.node.attr in _MAPPING_METHODS
        ):
            self._walk_method_call(node, node.node, references, local_vars)
            return

        if isinstance(node, nodes.Getattr):
            ref = self._extract_getattr_chain(node)
            if ref:
                source, field_path = ref
                if source not in local_vars and source not in self.JINJA_BUILTINS:
                    raw_ref = f"{{{{ {source}.{field_path} }}}}"
                    references.append((source, field_path, raw_ref))
            return

        # A name no record carries, read whole (`{{ action }}`, `action['x']`): any other
        # bare name is left alone here, as before.
        if (
            isinstance(node, nodes.Name)
            and node.ctx == "load"
            and node.name in RESERVED_NAMES_NO_RECORD_HAS
            and node.name not in local_vars
        ):
            references.append((node.name, "", f"{{{{ {node.name} }}}}"))
            return

        for child in node.iter_child_nodes():
            self._walk_ast(child, references, local_vars)

    def _walk_method_call(
        self,
        call: nodes.Call,
        method: nodes.Getattr,
        references: list[tuple],
        local_vars: set[str],
    ) -> None:
        """Read `x.items()` as a use of `x`, not of a field named `items`.

        A namespace called directly is referenced whole (`*`): the action must exist
        and be upstream, but no field is named, except by `x.get('field', ...)`, which
        reads that field.
        """
        receiver = method.node
        if isinstance(receiver, nodes.Name):
            root = namespace = receiver.name
        elif (
            isinstance(receiver, nodes.Getattr)
            and isinstance(receiver.node, nodes.Name)
            and receiver.node.name in RESERVED_NAMES_NO_RECORD_HAS
        ):
            root, namespace = receiver.node.name, receiver.attr
        else:
            root = namespace = ""
        if not namespace:
            self._walk_ast(receiver, references, local_vars)
        elif root not in local_vars and root not in self.JINJA_BUILTINS:
            key = call.args[0] if method.attr == "get" and call.args else None
            written = namespace if root == namespace else f"{root}.{namespace}"
            if isinstance(key, nodes.Const) and isinstance(key.value, str):
                raw = f"{{{{ {written}.get({key.value!r}) }}}}"
                field = key.value
            else:
                raw = f"{{{{ {written}.{method.attr}() }}}}"
                field = "*"
            if root != namespace:
                # `action.producer.items()`: the read is through `action`, of `producer`.
                references.append((root, namespace, raw))
            else:
                references.append((namespace, field, raw))
        for arg in (*call.args, *call.kwargs, call.dyn_args, call.dyn_kwargs):
            if arg is not None:
                self._walk_ast(arg, references, local_vars)

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

    @staticmethod
    def _guard_names_not_actions(agent_config: dict[str, Any]) -> set[str]:
        """Top-level names a guard can read that are not action namespaces.

        The guard context promotes these (see `guards/bare_reference.py`). A read through
        a reserved name no record has is still reported, for the type checker to refuse,
        unless a version param of that name puts it on the record.
        """
        from agent_actions.guards.bare_reference import (
            PROMOTED_RECORD_FIELDS,
            PROMOTED_VERSION_KEYS,
        )
        from agent_actions.prompt.context.scope_builder import VersionNamespaceBuilder

        version_context = agent_config.get("_version_context")
        promoted = VersionNamespaceBuilder.promoted_names(
            version_context if isinstance(version_context, dict) else None
        )
        return set(PROMOTED_RECORD_FIELDS) | set(PROMOTED_VERSION_KEYS) | promoted

    def _extract_from_guard_clause(
        self, guard: Any, agent_config: dict[str, Any]
    ) -> list[InputRequirement]:
        """The `namespace.field` paths a SQL guard clause reads.

        Read from the parsed clause, so a dot inside a quoted literal is not a reference.
        An expanded config carries the clause under `clause`, a raw one under
        `condition`. A UDF guard, or a clause that does not parse, yields nothing: the
        guard check reports the parse failure.
        """
        if isinstance(guard, str):
            clause: Any = guard
        elif isinstance(guard, dict):
            clause = guard.get("clause") or guard.get("condition")
        else:
            return []
        if not isinstance(clause, str) or not clause.strip():
            return []
        if clause.strip().lower().startswith("udf:"):
            return []

        from agent_actions.expectations.expression import referenced_field_paths
        from agent_actions.input.preprocessing.parsing.parser import WhereClauseParser

        parsed = WhereClauseParser().parse_cached(clause)
        if not parsed.success or parsed.ast is None:
            return []
        not_actions = self._guard_names_not_actions(agent_config)
        requirements: list[InputRequirement] = []
        for path in referenced_field_paths(parsed.ast.root):
            source, _, field = path.partition(".")
            if not field or source in not_actions:
                continue
            requirements.append(
                InputRequirement(
                    source_agent=source,
                    field_path=field,
                    raw_reference=path,
                    location="guard",
                )
            )
        return requirements

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
            for match in self.DOT_PATTERN.finditer(guard):
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
