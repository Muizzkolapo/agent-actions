"""FILE-granularity checks: first-stage FILE actions and flat observed-key collisions."""

from typing import Any

from agent_actions.output.response.expander_validation import routing_kind

from .errors import FieldLocation, StaticTypeError, StaticTypeWarning
from .schema_extractor import SchemaExtractor


class FileModeChecksMixin:
    workflow_config: dict[str, Any]
    schema_extractor: SchemaExtractor
    schema_loader: Any | None

    def _check_first_stage_file_granularity(self) -> list[StaticTypeError]:
        """Return errors for FILE-granularity actions that depend on nothing.

        The first stage runs its own pipeline, which selects a strategy by neither
        granularity nor kind, so such an action is processed per record and a tool's
        ``FileUDFResult`` reaches the output writer unconverted.
        """
        errors: list[StaticTypeError] = []
        for action in self.workflow_config.get("actions", []):
            if not isinstance(action, dict):
                continue
            if action.get("dependencies") or not self._is_file_mode_bus_action(action):
                continue
            name = action.get("name", "workflow")
            errors.append(
                StaticTypeError(
                    message=(
                        f"Action '{name}' reads at FILE granularity but declares no "
                        f"'dependencies'. A first action reads the staged input and is "
                        f"always processed one record at a time."
                    ),
                    location=FieldLocation(agent_name=name, config_field="dependencies"),
                    referenced_agent=name,
                    referenced_field="",
                    hint=(
                        "Put a RECORD action in front and depend on it, so this one "
                        "receives a file of its output."
                    ),
                )
            )
        return errors

    def _is_file_mode_bus_action(self, action: dict[str, Any]) -> bool:
        """Whether an action reads its input as FILE-mode flat observed keys.

        Resolves granularity the way the config expander does: HITL defaults to
        file, everything else falls back to the workflow's own defaults block.
        """
        kind = routing_kind(action)
        is_hitl = kind == "hitl"
        if kind == "llm":
            return False

        granularity = action.get("granularity")
        if granularity is None and not is_hitl:
            defaults = self.workflow_config.get("defaults")
            if isinstance(defaults, dict):
                granularity = defaults.get("granularity")
        if granularity is None:
            return is_hitl
        return isinstance(granularity, str) and granularity.lower() == "file"

    @staticmethod
    def _observed_namespace_fields(
        observe_refs: list[str], schemas: dict[str, Any]
    ) -> dict[str, dict[str, Any]]:
        """Build the namespace→fields shape the runtime would enrich against.

        Declared output schemas stand in for the record's namespaces so wildcard
        refs can be expanded here the way runtime expands them against real
        content. A namespace whose schema is dynamic or schemaless contributes
        only its explicitly observed fields — its wildcard expansion is not
        knowable before the run.
        """
        shape: dict[str, dict[str, Any]] = {}
        for ref in observe_refs:
            if not isinstance(ref, str) or "." not in ref:
                continue
            ns, field = ref.split(".", 1)
            fields = shape.setdefault(ns, {})
            schema = schemas.get(ns)
            if field == "*":
                # The action's own output only: a field it forwards by passthrough
                # lands in that field's own namespace at run time, never in this one,
                # so a wildcard here never yields it.
                if schema and not (schema.is_dynamic or schema.is_schemaless):
                    fields.update(dict.fromkeys(schema.schema_fields))
            else:
                fields[field] = None
        return shape

    def _check_file_tool_observe_collision(self) -> list[StaticTypeWarning]:
        """Warn when FILE-mode observed fields collide on their flat key.

        Plans the keys through the runtime planner, over the declared schemas, so the
        two cannot drift and a schemaless namespace claims nothing. Reports only what
        the payload will see: qualification applied purely to protect a namespace
        would send the user to a key their action never gets.
        """
        from agent_actions.prompt.context.scope_application import (
            _resolve_observe_refs_for_flat_keys,
            plan_flat_observed_keys,
        )

        actions = [a for a in self.workflow_config.get("actions", []) if isinstance(a, dict)]
        if not any(self._is_file_mode_bus_action(a) for a in actions):
            return []

        schemas = self.schema_extractor.extract_from_workflow(
            self.workflow_config, self.schema_loader
        )

        warnings: list[StaticTypeWarning] = []
        for action in actions:
            if not self._is_file_mode_bus_action(action):
                continue
            context_scope = action.get("context_scope")
            if not isinstance(context_scope, dict):
                continue
            observe_refs = context_scope.get("observe")
            if not isinstance(observe_refs, list):
                continue

            resolved, qualify_wildcards = _resolve_observe_refs_for_flat_keys(
                observe_refs, emit_diagnostics=False
            )
            # Bare names declared in two namespaces are qualified by the resolver;
            # wildcards are qualified only when 2+ distinct namespaces use one
            # (qualify_wildcards) — not when the same namespace is observed twice.
            qualified = {out for _, field, out in resolved if field != "*" and out != field}
            if qualify_wildcards:
                qualified |= {f"{ns}.*" for ns, field, _ in resolved if field == "*"}
            # What the declared refs alone can't show: a field shadowing a
            # namespace, or a wildcard field whose name a named ref owns.
            _, shadowed = plan_flat_observed_keys(
                self._observed_namespace_fields(observe_refs, schemas),
                resolved,
                qualify_wildcards,
            )
            qualified |= shadowed
            if not qualified:
                continue

            name = action.get("name", "unknown")
            kind_label = "HITL action" if action.get("kind") == "hitl" else "FILE tool"
            warnings.append(
                StaticTypeWarning(
                    message=(
                        f"{kind_label} '{name}' observes colliding field names; input "
                        f"keys are delivered namespace-qualified "
                        f"({', '.join(sorted(qualified))})."
                    ),
                    location=FieldLocation(
                        agent_name=name,
                        config_field="context_scope.observe",
                        raw_reference=", ".join(r for r in observe_refs if isinstance(r, str)),
                    ),
                    referenced_agent="",
                    referenced_field="",
                    hint="Read the namespace-qualified keys in the action, or observe "
                    "non-colliding fields.",
                )
            )
        return warnings
