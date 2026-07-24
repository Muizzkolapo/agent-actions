"""Workflow YAML parser for documentation generation."""

import logging
from typing import Any

import click
import yaml

from agent_actions.config.schema_field import field_is_required, top_level_required_ids
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

        for action_data in actions:
            action_name = action_data.get("name", "unnamed")

            # Use auto-inferred dependencies for complete graph
            from agent_actions.prompt.context.scope_inference import infer_dependencies

            try:
                input_sources, context_sources = infer_dependencies(
                    action_data, action_names, action_name
                )
                all_dependencies = input_sources + context_sources
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

            # Extract context_scope (for input fields)
            if "context_scope" in action_data:
                action["context_scope"] = action_data["context_scope"]

            # Extract additional action configuration fields
            action["granularity"] = action_data.get("granularity")  # RECORD or FILE
            action["guard"] = action_data.get("guard")  # Conditional execution
            action["drops"] = action_data.get("drops", [])  # Fields excluded from prompt
            action["observe"] = action_data.get("observe", [])  # Pass-through fields
            action["policy"] = action_data.get("policy")  # Execution policy
            action["prompt"] = action_data.get("prompt")  # Prompt reference
            action["idempotency_key"] = action_data.get("idempotency_key")

            # Loop configuration (legacy)
            if "loop" in action_data:
                action["loop"] = action_data["loop"]  # {param, range, mode}
            if "loop_consumption" in action_data:
                action["loop_consumption"] = action_data["loop_consumption"]

            # Versions configuration (parallel execution)
            if "versions" in action_data:
                action["versions"] = action_data["versions"]  # {param, range, mode}
            if "version_consumption" in action_data:
                action["version_consumption"] = action_data[
                    "version_consumption"
                ]  # {source, pattern}

            # Parallel merge configuration (MapReduce pattern)
            # reduce_key specifies field to correlate records from parallel branches
            if "reduce_key" in action_data:
                action["reduce_key"] = action_data["reduce_key"]

            # Reprompt/retry configuration
            if "reprompt" in action_data:
                action["reprompt"] = action_data[
                    "reprompt"
                ]  # {validation, max_attempts, on_exhausted}

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
            if versions and isinstance(versions.get("range"), list):
                version_range = versions["range"]
                expanded_names = [f"{name}_{v}" for v in version_range]
                version_map[name] = expanded_names
                for v in version_range:
                    versioned = {**action, "name": f"{name}_{v}"}
                    versioned.pop("versions", None)
                    expanded_actions[f"{name}_{v}"] = versioned
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
                action["dependencies"] = resolved_deps
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
