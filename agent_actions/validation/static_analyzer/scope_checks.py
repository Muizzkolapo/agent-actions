"""Context-scope checks: wildcard expansion, required scope, template and seed coverage."""

import logging
import re
from typing import Any

from jinja2.exceptions import TemplateSyntaxError

from agent_actions.input.context.normalizer import SEED_CONFIG_KEYS
from agent_actions.prompt.aliases import header_names
from agent_actions.utils.constants import SPECIAL_NAMESPACES

from .data_flow_graph import DataFlowGraph
from .errors import FieldLocation, StaticTypeError, StaticTypeWarning

# Logged under the analyzer's module name, so its records keep one logger.
logger = logging.getLogger("agent_actions.validation.static_analyzer.workflow_static_analyzer")


class ContextScopeChecksMixin:
    workflow_config: dict[str, Any]
    graph: DataFlowGraph

    # ── Wildcard expansion ────────────────────────────────────────────

    def _expand_wildcards(self) -> list[StaticTypeError]:
        """Expand ``namespace.*`` references into concrete field references.

        Treats ``namespace.*`` as syntactic sugar for listing every field in
        the namespace's output schema.  For actions with known schemas the
        wildcard is replaced in-place so downstream checks operate on concrete
        field refs.  Dynamic / schemaless schemas cannot be expanded and the
        ``*`` is left as-is (downstream checks already skip these).

        Unknown namespaces produce errors — the same treatment explicit field
        references receive.
        """
        errors: list[StaticTypeError] = []
        actions = self.workflow_config.get("actions", [])

        for action in actions:
            if not isinstance(action, dict):
                continue

            action_name = action.get("name", "unknown")
            original_scope = action.get("context_scope")
            if not original_scope or not isinstance(original_scope, dict):
                continue

            # Shallow-copy so we don't mutate the caller's config.
            context_scope = {**original_scope}
            action["context_scope"] = context_scope

            for directive in ("observe", "passthrough", "drop"):
                refs = context_scope.get(directive)
                if not isinstance(refs, list):
                    continue

                expanded: list[str] = []
                for ref in refs:
                    if not isinstance(ref, str) or "." not in ref:
                        expanded.append(ref)
                        continue

                    ns_name, field_name = ref.split(".", 1)

                    if field_name != "*":
                        expanded.append(ref)
                        continue

                    # ── Wildcard reference: namespace.* ──

                    # Special namespaces and loop vars are runtime-provided;
                    # skip static validation.
                    if ns_name in SPECIAL_NAMESPACES or ns_name == "loop":
                        expanded.append(ref)
                        continue

                    # Namespace must be a known action in the workflow.
                    dep_node = self.graph.get_node(ns_name)
                    if not dep_node:
                        errors.append(
                            StaticTypeError(
                                message=(
                                    f"Wildcard reference '{ref}' in "
                                    f"context_scope.{directive} of action "
                                    f"'{action_name}' targets unknown action "
                                    f"'{ns_name}'"
                                ),
                                location=FieldLocation(
                                    agent_name=action_name,
                                    config_field=f"context_scope.{directive}",
                                    raw_reference=ref,
                                ),
                                referenced_agent=ns_name,
                                referenced_field="*",
                                hint=(
                                    f"No action named '{ns_name}' exists in "
                                    f"this workflow. Check for typos."
                                ),
                            )
                        )
                        continue

                    output = dep_node.output_schema

                    # Dynamic — fields resolved at runtime, can't expand.
                    if output.is_dynamic:
                        expanded.append(ref)
                        continue

                    # Schemaless — no schema defined, zero fields to expand.
                    # Drop the ref: "give me everything" from nothing = nothing.
                    if output.is_schemaless:
                        continue

                    # Expand into concrete field references.
                    # Empty schemas also resolve to nothing (wildcard on zero
                    # fields = zero refs).
                    fields = (
                        output.schema_fields | output.observe_fields | output.passthrough_fields
                    )
                    expanded.extend(f"{ns_name}.{f}" for f in sorted(fields))

                context_scope[directive] = expanded

        return errors

    def _check_context_scope_required(self) -> list[StaticTypeError]:
        """Return errors for actions missing context_scope.

        Every action must declare its data dependencies via context_scope.
        Actions without context_scope have no data access — this is enforced
        at static analysis time so users get feedback before execution.
        """
        errors: list[StaticTypeError] = []
        actions = self.workflow_config.get("actions", [])
        for action in actions:
            if not isinstance(action, dict):
                continue
            name = action.get("name", "unknown")
            context_scope = action.get("context_scope")
            if not context_scope or not isinstance(context_scope, dict):
                if context_scope is None and "context_scope" in action:
                    hint = (
                        "context_scope is null. Check YAML indentation — "
                        "observe/passthrough/drop must be indented under context_scope."
                    )
                elif context_scope is not None and not isinstance(context_scope, dict):
                    hint = (
                        f"context_scope must be a mapping, got {type(context_scope).__name__}. "
                        "Example: context_scope: {{ observe: [source.*] }}"
                    )
                else:
                    hint = (
                        "Add context_scope with observe, passthrough, or drop directives. "
                        "Example: context_scope: { observe: [source.*] }"
                    )
                errors.append(
                    StaticTypeError(
                        message=(
                            f"Action '{name}' has no context_scope. "
                            "All actions must declare data dependencies via context_scope."
                        ),
                        location=FieldLocation(
                            agent_name=name,
                            config_field="context_scope",
                        ),
                        referenced_agent=name,
                        referenced_field="",
                        hint=hint,
                    )
                )
        return errors

    @staticmethod
    def _uncovered_namespace_hint(
        name: str,
        namespace: str,
        named_actions: dict[str, dict[str, Any]],
        upstream: dict[str, set[str]],
    ) -> str:
        """The whole remedy: observing an action that is not upstream is refused next."""
        hint = f"Add '{namespace}.*' to context_scope.observe."
        if (
            namespace in named_actions
            and namespace != name
            and namespace not in upstream.get(name, set())
        ):
            hint += (
                f" '{namespace}' is not upstream of '{name}' through its dependencies, so also "
                f"add '{namespace}', or an action downstream of it, to 'dependencies'."
            )
        return hint

    def _check_template_scope_coverage(self) -> list[StaticTypeError]:
        """Check that template namespace references are declared in context_scope.

        For each action, extracts namespace references from the prompt template
        and verifies they appear in context_scope.observe or passthrough.
        Framework namespaces (version, seed, workflow, loop) and source are
        always available and not checked.
        """
        from agent_actions.prompt.context.scope_application import FRAMEWORK_NAMESPACES
        from agent_actions.prompt.context.scope_parsing import (
            extract_action_names_from_template,
        )
        from agent_actions.prompt.formatter import PromptFormatter
        from agent_actions.validation.dep_observe_validator import upstream_through_dependencies

        errors: list[StaticTypeError] = []
        actions = self.workflow_config.get("actions", [])
        named_actions = {
            a["name"]: a for a in actions if isinstance(a, dict) and isinstance(a.get("name"), str)
        }
        upstream = upstream_through_dependencies(named_actions)

        for action in actions:
            if not isinstance(action, dict):
                continue

            name = action.get("name", "unknown")
            context_scope = action.get("context_scope")
            if not context_scope or not isinstance(context_scope, dict):
                continue  # Already caught by _check_context_scope_required

            # Get template text
            try:
                template = PromptFormatter.get_raw_prompt(action)
            except Exception as exc:
                logger.debug(
                    "Cannot load prompt for action '%s', skipping template scope check: %s",
                    name,
                    exc,
                )
                continue

            if not template:
                continue

            # Extract non-special namespace references from template
            # (source, version, seed, workflow, loop are already filtered)
            try:
                template_namespaces = extract_action_names_from_template(
                    template, header_names(action)
                )
            except TemplateSyntaxError:
                continue  # syntax error already recorded in _build_graph via _build_errors

            # Also filter FRAMEWORK_NAMESPACES for safety
            template_namespaces -= FRAMEWORK_NAMESPACES

            # Extract namespaces declared in context_scope observe/passthrough
            scoped_namespaces: set[str] = set()
            for directive in ("observe", "passthrough"):
                for ref in context_scope.get(directive, []):
                    if isinstance(ref, str) and "." in ref:
                        scoped_namespaces.add(ref.split(".", 1)[0])

            # Flag uncovered namespaces
            uncovered = template_namespaces - scoped_namespaces
            for ns in sorted(uncovered):
                errors.append(
                    StaticTypeError(
                        message=(
                            f"Action '{name}': template references namespace '{ns}' "
                            f"which is not declared in context_scope.observe or passthrough."
                        ),
                        location=FieldLocation(
                            agent_name=name,
                            config_field="context_scope",
                        ),
                        referenced_agent=ns,
                        referenced_field="",
                        hint=self._uncovered_namespace_hint(name, ns, named_actions, upstream),
                    )
                )

        return errors

    def _check_seed_reference_misuse(self) -> list[StaticTypeError]:
        """Catch common misuse of seed_data/seed_path in context_scope references.

        Users sometimes write ``seed_data.field`` or ``seed_path.field`` in
        observe/drop/passthrough when they should write ``seed.field``.
        """
        errors: list[StaticTypeError] = []
        actions = self.workflow_config.get("actions", [])

        for action in actions:
            if not isinstance(action, dict):
                continue

            action_name = action.get("name", "unknown")
            context_scope = action.get("context_scope", {})
            if not context_scope:
                continue

            for directive in ["observe", "drop", "passthrough"]:
                field_refs = context_scope.get(directive, [])
                if not isinstance(field_refs, list):
                    continue

                for field_ref in field_refs:
                    if not isinstance(field_ref, str) or "." not in field_ref:
                        continue

                    namespace, field_name = field_ref.split(".", 1)
                    if namespace in SEED_CONFIG_KEYS:
                        correct_ref = f"seed.{field_name}"
                        errors.append(
                            StaticTypeError(
                                message=(
                                    f"context_scope.{directive} references "
                                    f"'{field_ref}' — use '{correct_ref}' instead. "
                                    f"'{namespace}' is a config key for declaring file paths; "
                                    f"use the 'seed' namespace for runtime references."
                                ),
                                location=FieldLocation(
                                    agent_name=action_name,
                                    config_field=f"context_scope.{directive}",
                                    raw_reference=field_ref,
                                ),
                                referenced_agent=namespace,
                                referenced_field=field_name,
                                hint=f"Replace '{field_ref}' with '{correct_ref}'.",
                            )
                        )

        return errors

    _SEED_TEMPLATE_REF = re.compile(r"\bseed\.([A-Za-z_][A-Za-z0-9_]*)")

    _JINJA_SPAN = re.compile(r"\{\{.*?\}\}|\{%.*?%\}", re.S)

    def _check_seed_template_observe_overlap(self) -> list[StaticTypeWarning]:
        """Warn when a seed field is both observed and referenced in the template.

        Seed data is always available to Jinja templates. Observing the same
        field additionally injects it into the LLM context message, so the
        value reaches the model twice.
        """
        from agent_actions.prompt.formatter import PromptFormatter

        warnings: list[StaticTypeWarning] = []
        for action in self.workflow_config.get("actions", []):
            if not isinstance(action, dict):
                continue

            name = action.get("name", "unknown")
            context_scope = action.get("context_scope") or {}
            if not isinstance(context_scope, dict):
                continue
            observe = context_scope.get("observe") or []
            if not isinstance(observe, list):
                continue

            observed_seed: set[str] = set()
            seed_wildcard = False
            for ref in observe:
                if not isinstance(ref, str) or "." not in ref:
                    continue
                ns, field = ref.split(".", 1)
                if ns != "seed":
                    continue
                if field == "*":
                    seed_wildcard = True
                else:
                    observed_seed.add(field)
            if not observed_seed and not seed_wildcard:
                continue

            try:
                template = PromptFormatter.get_raw_prompt(action)
            except Exception as exc:
                logger.debug(
                    "Cannot load prompt for action '%s', skipping seed overlap check: %s",
                    name,
                    exc,
                )
                continue
            if not template:
                continue

            template_seed: set[str] = set()
            for span in self._JINJA_SPAN.findall(template):
                template_seed.update(self._SEED_TEMPLATE_REF.findall(span))

            overlap = template_seed if seed_wildcard else template_seed & observed_seed
            for field in sorted(overlap):
                warnings.append(
                    StaticTypeWarning(
                        message=(
                            f"Action '{name}': seed field '{field}' is both in "
                            f"context_scope.observe and referenced in the prompt "
                            f"template ({{{{ seed.{field} }}}}). The value is "
                            f"injected twice — once via the rendered template and "
                            f"once via the observe context message."
                        ),
                        location=FieldLocation(
                            agent_name=name,
                            config_field="context_scope.observe",
                            raw_reference=f"seed.{field}",
                        ),
                        referenced_agent="seed",
                        referenced_field=field,
                        hint=(
                            "Remove the observe entry (templates always see seed), "
                            "or drop the template reference."
                        ),
                    )
                )

        return warnings
