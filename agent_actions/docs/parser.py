"""
Workflow YAML parser for documentation generation.
"""

from typing import Dict, List, Any, Optional

import yaml


def extract_fields_for_docs(raw_schema: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Extract normalized field list from raw schema for documentation.

    Handles 3 schema formats:
    1. Unified format: {fields: [{id, type, ...}]}
    2. Array schema: {type: 'array', items: {properties: {...}}}
    3. Object schema: {type: 'object', properties: {...}}

    Args:
        raw_schema: Raw YAML schema data from SchemaLoader.load_schema()

    Returns:
        List of field dicts with {name, type, description, required}
    """
    fields = []

    # Format 1: Custom 'fields' array
    if "fields" in raw_schema and isinstance(raw_schema["fields"], list):
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
                        "required": field_def.get("required", False),
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
    def parse_workflow(yaml_path: str) -> Optional[Dict[str, Any]]:
        """Parse a workflow YAML file and extract all relevant information."""
        try:
            with open(yaml_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except yaml.YAMLError as e:
            print(f"  ⚠ Warning: YAML parsing error - {e}")
            return None
        except Exception as e:
            print(f"  ⚠ Warning: Error reading file - {e}")
            return None

        workflow = {
            "name": data.get("name", ""),
            "description": data.get("description", ""),
            "path": yaml_path,
            "version": data.get("version", "1.0.0"),
            "actions": {},
        }

        # Parse actions (flat structure from rendered workflows)
        actions = data.get("actions", [])
        for action_data in actions:
            action_name = action_data.get("name", "unnamed")

            action = {
                "name": action_name,
                "intent": action_data.get("intent", ""),
                "dependencies": action_data.get("dependencies", []),
            }

            # Determine action type (llm or tool) from flat structure
            if action_data.get("kind") == "tool":
                action["type"] = "tool"
                action["provider"] = "tool"
                action["implementation"] = action_data.get("impl", "unknown")
            else:
                # Default to LLM action
                action["type"] = "llm"
                action["provider"] = action_data.get("model_vendor", "unknown")
                action["model"] = action_data.get("model_name", "unknown")

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
            action["few_shot"] = action_data.get("few_shot")  # Few-shot example count
            action["prompt"] = action_data.get("prompt")  # Prompt reference
            action["idempotency_key"] = action_data.get("idempotency_key")

            # Loop configuration
            if "loop" in action_data:
                action["loop"] = action_data["loop"]  # {param, range, mode}
            if "loop_consumption" in action_data:
                action["loop_consumption"] = action_data["loop_consumption"]

            # Parallel merge configuration (MapReduce pattern)
            # reduce_key specifies field to correlate records from parallel branches
            if "reduce_key" in action_data:
                action["reduce_key"] = action_data["reduce_key"]

            workflow["actions"][action_name] = action

        return workflow

    @staticmethod
    def extract_input_fields(context_scope: Dict[str, Any]) -> List[str]:
        """
        Extract input field names from context_scope.

        Args:
            context_scope: The context_scope dict from action definition

        Returns:
            List of input field names (e.g., ['source.page_content', 'seed.exam_syllabus'])
        """
        inputs = []

        # Extract from 'observe' - fields that are read as inputs
        if "observe" in context_scope and isinstance(context_scope["observe"], list):
            inputs.extend(context_scope["observe"])

        # Extract from 'passthrough' - fields that flow through (both input and output)
        if "passthrough" in context_scope and isinstance(context_scope["passthrough"], list):
            inputs.extend(context_scope["passthrough"])

        # Extract from 'keep' (legacy/alternative pattern)
        if "keep" in context_scope and isinstance(context_scope["keep"], list):
            inputs.extend(context_scope["keep"])

        # Remove duplicates while preserving order
        seen = set()
        unique_inputs = []
        for field in inputs:
            if field not in seen:
                seen.add(field)
                unique_inputs.append(field)

        return unique_inputs
