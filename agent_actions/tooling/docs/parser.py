"""Workflow YAML parser for documentation generation."""

import logging
from typing import Any

import click
import yaml

from agent_actions.config.schema import version_variant_names
from agent_actions.config.schema_field import field_is_required, top_level_required_ids
from agent_actions.errors import ConfigurationError
from agent_actions.input.context.normalizer import DIRECTIVE_REGISTRY, normalize_context_scope
from agent_actions.output.response.expander_merge import deep_merge_context_scope
from agent_actions.utils.constants import DEFAULT_ACTION_KIND

logger = logging.getLogger(__name__)


def extract_fields_for_docs(raw_schema: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract normalized field list from raw schema for documentation.

    Handles unified format, array schema, and object schema formats.
    """
    fields = []

    # Format 1: Custom 'fields' array
    if "fields" in raw_schema and isinstance(raw_schema["fields"], list):
        required_by_default = raw_schema.get("required_by_default", False)
        top_level_required = top_level_required_ids(raw_schema)
        for field_def in raw_schema["fields"]:
            # Handle nested array with items.properties
            if (
                field_def.get("type") == "array"
                and "items" in field_def
                and "properties" in field_def["items"]
            ):
                items = field_def["items"]
                required_fields = items.get("required", [])
                for prop_name, prop_def in items["properties"].items():
                    fields.append(
                        {
                            "name": prop_name,
                            "type": prop_def.get("type", "unknown"),
                            "description": prop_def.get("description", ""),
                            "required": prop_name in required_fields,
                        }
                    )
            # Simple field: {id, type, description}
            elif "id" in field_def:
                fields.append(
                    {
                        "name": field_def["id"],
                        "type": field_def.get("type", "unknown"),
                        "description": field_def.get("description", ""),
                        "required": field_is_required(
                            field_def, required_by_default, top_level_required
                        ),
                    }
                )

    # Format 2: Array schema with items.properties
    elif raw_schema.get("type") == "array" and "items" in raw_schema:
        properties = raw_schema.get("items", {}).get("properties", {})
        required_fields = raw_schema.get("items", {}).get("required", [])
        for field_name, field_info in properties.items():
            fields.append(
                {
                    "name": field_name,
                    "type": field_info.get("type", "unknown"),
                    "description": field_info.get("description", ""),
                    "required": field_name in required_fields,
                }
            )

    # Format 3: Object schema with properties
    elif raw_schema.get("type") == "object" and "properties" in raw_schema:
        properties = raw_schema.get("properties", {})
        required_fields = raw_schema.get("required", [])
        for field_name, field_info in properties.items():
            fields.append(
                {
                    "name": field_name,
                    "type": field_info.get("type", "unknown"),
                    "description": field_info.get("description", ""),
                    "required": field_name in required_fields,
                }
            )

    return fields


def _normalise_known_directives(
    scope: dict[str, Any], version_base_map: dict[str, list[str]]
) -> dict[str, Any]:
    """Normalise the directives the runtime knows, and pass the rest through untouched.

    A retired spelling is the loader's error to raise on a run, so the catalog reports what it
    can rather than refusing to build. Per directive, not per block: normalising nothing when
    one key is unknown suppressed version expansion for every reference in the same workflow.
    """
    known = {k: v for k, v in scope.items() if k in DIRECTIVE_REGISTRY}
    unknown = {k: v for k, v in scope.items() if k not in DIRECTIVE_REGISTRY}
    try:
        normalised = normalize_context_scope(known, version_base_map)
    except ConfigurationError as e:
        logger.debug(
            "Context scope normalisation failed, using the raw directives: %s. "
            "Version references in this scope will not be expanded in the catalog.",
            e,
        )
        normalised = known
    return {**normalised, **unknown}


class WorkflowParser:
    """Parse and extract information from agent workflow YAML files."""

    @staticmethod
    def parse_workflow(yaml_path: str) -> dict[str, Any] | None:
        """Parse a workflow YAML file and extract all relevant information."""
        try:
            with open(yaml_path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except yaml.YAMLError as e:
            # Dual-channel: logger for log aggregation, click.echo for CLI visibility
            logger.warning("YAML parsing error in %s: %s", yaml_path, e)
            click.echo(f"  Warning: YAML parsing error in {yaml_path} - {e}")
            return None
        except Exception as e:
            logger.warning("Error reading workflow file %s: %s", yaml_path, e)
            click.echo(f"  Warning: Error reading file {yaml_path} - {e}")
            return None

        if data is None:
            logger.warning("Workflow file %s is empty or contains only comments", yaml_path)
            click.echo(f"  Warning: Workflow file {yaml_path} is empty or contains only comments")
            return None

        if not isinstance(data, dict):
            logger.warning(
                "Workflow file %s top-level value is a %s, expected a mapping",
                yaml_path,
                type(data).__name__,
            )
            click.echo(
                f"  Warning: Workflow file {yaml_path} top-level value is a "
                f"{type(data).__name__}, expected a mapping"
            )
            return None

        # Extract workflow defaults
        defaults = data.get("defaults", {})

        workflow = {
            "name": data.get("name", ""),
            "description": data.get("description", ""),
            "path": yaml_path,
            "version": data.get("version", "1.0.0"),
            "actions": {},
            "defaults": {
                "model_vendor": defaults.get("model_vendor"),
                "model_name": defaults.get("model_name"),
                "json_mode": defaults.get("json_mode"),
                "granularity": defaults.get("granularity"),
                "run_mode": defaults.get("run_mode"),
            },
        }

        # Parse actions (flat structure from rendered workflows)
        actions = data.get("actions", [])
        action_names = [a.get("name") for a in actions if a.get("name")]

        # Two shapes reach here. A source workflow still carries `versions:`. A rendered one
        # does not -- render_workflow expands it and strips the key, leaving the base name in
        # `_version_context` -- and a rendered file is what `scan_workflows` prefers whenever
        # the project has run, so a map built only from `versions:` is empty for every real
        # project. The runtime builds its own map from the same base name.
        version_base_map: dict[str, list[str]] = {}
        for action_data in actions:
            name = action_data.get("name")
            if not name:
                continue
            versions = action_data.get("versions")
            if versions:
                try:
                    version_base_map[name] = version_variant_names(name, versions)
                except ConfigurationError as e:
                    # The malformed block is the loader's to reject on a run, but `agac docs`
                    # never calls it, so without this line the catalog silently omits every
                    # version reference for the action and nothing says why.
                    logger.warning(
                        "Action '%s' has a malformed versions block, so the catalog cannot "
                        "expand its version references: %s",
                        name,
                        e,
                    )
                    continue
                continue
            version_context = action_data.get("_version_context")
            if isinstance(version_context, dict):
                base = version_context.get("base_name")
                if base:
                    version_base_map.setdefault(base, []).append(name)

        # The names inference is checked against must be the expanded ones, because the
        # scope handed to it has already been normalised to `voter_1`, `voter_2`. Built from
        # the raw list, a source workflow's `voter` is the only name present, inference
        # raises on every variant, and the fallback below quietly drops real edges --
        # measured, 2 fallbacks became 13 and four actions lost upstreams the catalog is
        # supposed to show. The runtime has no such gap: it passes expanded names.
        for variants in version_base_map.values():
            action_names.extend(name for name in variants if name not in action_names)

        for action_data in actions:
            action_name = action_data.get("name", "unnamed")

            # The runtime normalises before inferring, and says why at config/manager.py:399:
            # "so that infer_dependencies sees concrete versioned refs, not base names".
            # Inferring from the raw block reported a scope the dependency graph did not agree
            # with -- an inherited observe named an upstream the graph then omitted.
            merged_scope = _normalise_known_directives(
                deep_merge_context_scope(
                    defaults.get("context_scope"), action_data.get("context_scope")
                ),
                version_base_map,
            )
            inference_input = (
                {**action_data, "context_scope": merged_scope} if merged_scope else action_data
            )

            # Use auto-inferred dependencies for complete graph
            from agent_actions.prompt.context.scope_inference import infer_dependencies

            try:
                input_sources, context_sources = infer_dependencies(
                    inference_input, action_names, action_name
                )
                all_dependencies = list(dict.fromkeys(input_sources + context_sources))
            except Exception as e:
                logger.debug(
                    "Dependency inference failed for action %s, using explicit deps: %s",
                    action_name,
                    e,
                )
                # Fallback to explicit dependencies
                all_dependencies = action_data.get("dependencies", [])

            action = {
                "name": action_name,
                "intent": action_data.get("intent", ""),
                "dependencies": all_dependencies,
            }

            # Determine action type (llm or tool) from flat structure
            if action_data.get("kind") == "tool":
                action["type"] = "tool"
                action["provider"] = "tool"
                action["implementation"] = action_data.get("impl", "unknown")
            else:
                # Default to LLM action
                action["type"] = DEFAULT_ACTION_KIND
                action["provider"] = action_data.get("model_vendor") or defaults.get("model_vendor")
                action["model"] = action_data.get("model_name") or defaults.get("model_name")

            # Extract schema (for field-level lineage)
            if "schema" in action_data:
                action["schema"] = action_data["schema"]

            # The runtime is handed defaults merged in and version bases expanded, so a
            # panel built from the raw block reports no drop for an action the runtime
            # drops a field on, and names a namespace no action answers to.
            if merged_scope:
                action["context_scope"] = merged_scope

            # Extract additional action configuration fields
            action["granularity"] = action_data.get("granularity")  # RECORD or FILE
            action["guard"] = action_data.get("guard")  # Conditional execution
            action["policy"] = action_data.get("policy")  # Execution policy
            action["prompt"] = action_data.get("prompt")  # Prompt reference

            # Loop configuration (legacy)
            if "loop" in action_data:
                action["loop"] = action_data["loop"]  # {param, range, mode}
            if "loop_consumption" in action_data:
                action["loop_consumption"] = action_data["loop_consumption"]

            # Versions configuration (parallel execution)
            if "versions" in action_data:
                action["versions"] = action_data["versions"]  # {param, range}
            if "version_consumption" in action_data:
                action["version_consumption"] = action_data[
                    "version_consumption"
                ]  # {source, pattern}

            # Parallel merge configuration (MapReduce pattern)
            # reduce_key specifies field to correlate records from parallel branches
            if "reduce_key" in action_data:
                action["reduce_key"] = action_data["reduce_key"]

            # Execution mode configuration
            if "run_mode" in action_data:
                action["run_mode"] = action_data["run_mode"]  # batch or online
            if "json_mode" in action_data:
                action["json_mode"] = action_data["json_mode"]
            if "prompt_debug" in action_data:
                action["prompt_debug"] = action_data["prompt_debug"]

            workflow["actions"][action_name] = action

        # Expand versioned actions into concrete instances (e.g., action with
        # versions.range=[1,2,3] becomes action_1, action_2, action_3)
        version_map: dict[str, list[str]] = {}
        expanded_actions: dict[str, Any] = {}
        for name, action in workflow["actions"].items():
            versions = action.get("versions")
            expanded_names = version_base_map.get(name) if versions else None
            if expanded_names:
                # Same rule the runtime expands by: a two-element range is a start and an
                # end, inclusive. Reading `range` literally listed [2, 5] as two actions
                # where the run has four.
                version_map[name] = expanded_names
                for variant in expanded_names:
                    versioned = {**action, "name": variant}
                    versioned.pop("versions", None)
                    expanded_actions[variant] = versioned
            else:
                expanded_actions[name] = action

        if version_map:
            for action in expanded_actions.values():
                resolved_deps = []
                for dep in action.get("dependencies", []):
                    if dep in version_map:
                        resolved_deps.extend(version_map[dep])
                    else:
                        resolved_deps.append(dep)
                # Deduped after expansion, which is where the collision is: inference names
                # the base in input_sources and the variants in context_sources, so
                # expanding the base produces names the list already carries. A catalog
                # printing `draft_id_note_1` twice is wrong about the graph.
                action["dependencies"] = list(dict.fromkeys(resolved_deps))
            workflow["actions"] = expanded_actions

        return workflow

    @staticmethod
    def extract_input_fields(context_scope: dict[str, Any]) -> list[str]:
        """Extract input field names from context_scope."""
        inputs = []

        # Extract from 'observe' - fields that are read as inputs
        if "observe" in context_scope and isinstance(context_scope["observe"], list):
            inputs.extend(context_scope["observe"])

        # Extract from 'passthrough' - fields that flow through (both input and output)
        if "passthrough" in context_scope and isinstance(context_scope["passthrough"], list):
            inputs.extend(context_scope["passthrough"])

        # Remove duplicates while preserving order
        seen = set()
        unique_inputs = []
        for field in inputs:
            if field not in seen:
                seen.add(field)
                unique_inputs.append(field)

        return unique_inputs
