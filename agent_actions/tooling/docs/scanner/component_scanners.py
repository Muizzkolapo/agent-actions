"""Component scan functions: vendors, errors, events, examples, loaders, processing states."""

import ast
import logging
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# Root of the agent_actions package — used by functions that locate sibling
# packages via filesystem traversal rather than project_root.
_PACKAGE_ROOT = Path(__file__).resolve().parent.parent.parent.parent


def scan_vendors(project_root: Path) -> dict[str, Any]:
    """Scan for LLM vendor configurations via AST parsing."""
    vendors: dict[str, Any] = {}
    vendor_file = project_root.parent / "agent_actions" / "llm" / "config" / "vendor.py"

    # Also check if we're inside agent_actions already
    if not vendor_file.exists():
        vendor_file = _PACKAGE_ROOT / "llm" / "config" / "vendor.py"

    if not vendor_file.exists():
        return vendors

    try:
        source = vendor_file.read_text()
        tree = ast.parse(source)

        # Extract VendorType enum values and config classes
        enum_values: dict[str, Any] = {}
        config_classes: dict[str, Any] = {}

        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue

            # Check for VendorType enum
            is_enum = any((isinstance(b, ast.Name) and b.id in ("Enum", "str")) for b in node.bases)
            if node.name == "VendorType" and is_enum:
                for item in node.body:
                    if isinstance(item, ast.Assign):
                        for target in item.targets:
                            if isinstance(target, ast.Name) and isinstance(
                                item.value, ast.Constant
                            ):
                                enum_values[target.id] = item.value.value

            # Check for *Config classes inheriting from BaseVendorConfig
            is_config = any(
                (isinstance(b, ast.Name) and b.id == "BaseVendorConfig") for b in node.bases
            )
            if is_config:
                docstring = ast.get_docstring(node) or ""
                fields = []
                for item in node.body:
                    if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                        field_name = item.target.id
                        default_val = None
                        if item.value:
                            # Try to get the constant default
                            if isinstance(item.value, ast.Constant):
                                default_val = item.value.value
                            elif isinstance(item.value, ast.Call):
                                # Field(...) - extract default keyword
                                for kw in item.value.keywords:
                                    if kw.arg == "default" and isinstance(kw.value, ast.Constant):
                                        default_val = kw.value.value
                        fields.append({"name": field_name, "default": default_val})
                config_classes[node.name] = {
                    "fields": fields,
                    "docstring": docstring,
                }

        # Map enum values to config classes by matching vendor_type
        config_map = {
            "OPENAI": "OpenAIConfig",
            "ANTHROPIC": "AnthropicConfig",
            "GOOGLE": "GoogleConfig",
            "GEMINI": "GoogleConfig",
            "GROQ": "GroqConfig",
            "COHERE": "CohereConfig",
            "MISTRAL": "MistralConfig",
            "OLLAMA": "OllamaConfig",
            "TOOL": "ToolVendorConfig",
            "AGAC_PROVIDER": "AgacProviderConfig",
        }

        for enum_name, enum_val in enum_values.items():
            config_cls_name = config_map.get(enum_name, "")
            config_info = config_classes.get(config_cls_name, {})
            vendors[enum_val] = {
                "id": enum_val,
                "enum_name": enum_name,
                "enum_value": enum_val,
                "config_class": config_cls_name,
                "fields": config_info.get("fields", []),
                "docstring": config_info.get("docstring", ""),
            }

    except (OSError, SyntaxError, UnicodeDecodeError) as e:
        logger.debug("Could not scan vendors from %s: %s", vendor_file, e)

    return vendors


def scan_error_types() -> dict[str, Any]:
    """Scan for error/exception class hierarchy via AST parsing."""
    error_types: dict[str, Any] = {}
    errors_dir = _PACKAGE_ROOT / "errors"

    if not errors_dir.exists():
        return error_types

    # Category mapping based on file names
    category_map = {
        "base.py": "base",
        "common.py": "common",
        "configuration.py": "configuration",
        "validation.py": "validation",
        "processing.py": "processing",
        "external_services.py": "external_services",
        "filesystem.py": "filesystem",
        "resources.py": "resources",
        "operations.py": "operations",
        "preflight.py": "preflight",
    }

    for py_file in errors_dir.glob("*.py"):
        if py_file.name == "__init__.py":
            continue

        category = category_map.get(py_file.name, py_file.stem)
        errors_list = []
        base_class = None

        try:
            source = py_file.read_text()
            tree = ast.parse(source)

            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef):
                    continue

                # Get parent class name
                parent_name = None
                for base in node.bases:
                    if isinstance(base, ast.Name):
                        parent_name = base.id
                        break

                docstring = ast.get_docstring(node) or ""

                error_info = {
                    "name": node.name,
                    "parent": parent_name,
                    "docstring": docstring,
                    "source_file": py_file.name,
                    "line": node.lineno,
                }
                errors_list.append(error_info)

                # First class in non-base files is the category's base class
                if base_class is None and category != "base":
                    base_class = node.name

            if errors_list:
                error_types[category] = {
                    "id": category,
                    "base_class": base_class or errors_list[0]["name"],
                    "source_file": py_file.name,
                    "errors": errors_list,
                    "error_count": len(errors_list),
                }

        except (OSError, SyntaxError, UnicodeDecodeError) as e:
            logger.debug("Could not scan error types from %s: %s", py_file, e)
            continue

    return error_types


def scan_event_types() -> dict[str, Any]:
    """Scan for event type definitions via AST parsing."""
    event_types: dict[str, Any] = {}
    events_file = _PACKAGE_ROOT / "logging" / "events" / "types.py"

    if not events_file.exists():
        return event_types

    try:
        source = events_file.read_text()
        tree = ast.parse(source)

        # First extract EventCategories class values
        categories_map = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == "EventCategories":
                for item in node.body:
                    if isinstance(item, ast.Assign):
                        for target in item.targets:
                            if isinstance(target, ast.Name) and isinstance(
                                item.value, ast.Constant
                            ):
                                categories_map[target.id] = item.value.value

        # Then extract event dataclasses
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue

            # Check if it inherits from BaseEvent
            is_event = any((isinstance(b, ast.Name) and b.id == "BaseEvent") for b in node.bases)
            if not is_event:
                continue

            docstring = ast.get_docstring(node) or ""

            # Extract fields (annotations on the class body)
            fields = []
            for item in node.body:
                if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                    field_name = item.target.id
                    field_type = ast.unparse(item.annotation) if item.annotation else "Any"
                    fields.append({"name": field_name, "type": field_type})

            # Extract event code from the code property
            event_code = ""
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == "code":
                    for stmt in ast.walk(item):
                        if isinstance(stmt, ast.Return) and isinstance(stmt.value, ast.Constant):
                            event_code = str(stmt.value.value)

            # Determine category from __post_init__ body
            category = "unknown"
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == "__post_init__":
                    for stmt in ast.walk(item):
                        if (
                            isinstance(stmt, ast.Assign)
                            and len(stmt.targets) == 1
                            and isinstance(stmt.targets[0], ast.Attribute)
                            and stmt.targets[0].attr == "category"
                        ):
                            # EventCategories.WORKFLOW → "workflow"
                            if isinstance(stmt.value, ast.Attribute):
                                cat_key = stmt.value.attr
                                category = str(categories_map.get(cat_key, cat_key.lower()))

            event_info = {
                "name": node.name,
                "code": event_code,
                "docstring": docstring,
                "fields": fields,
                "line": node.lineno,
            }

            if category not in event_types:
                event_types[category] = {
                    "id": category,
                    "events": [],
                }
            event_types[category]["events"].append(event_info)

        # Add counts
        for cat_data in event_types.values():
            cat_data["event_count"] = len(cat_data["events"])

    except (OSError, SyntaxError, UnicodeDecodeError) as e:
        logger.debug("Could not scan event types from %s: %s", events_file, e)

    return event_types


def scan_examples(project_root: Path) -> dict[str, Any]:
    """Scan for example projects in the examples/ directory."""
    examples: dict[str, Any] = {}
    examples_dir = project_root.parent / "examples"

    if not examples_dir.exists():
        # Try sibling
        examples_dir = project_root / "examples"
    if not examples_dir.exists():
        # Try parent's parent (common layout)
        examples_dir = project_root.parent.parent / "examples"
    if not examples_dir.exists():
        return examples

    for example_dir in sorted(examples_dir.iterdir()):
        if not example_dir.is_dir():
            continue

        # Must have agent_actions.yml to be a valid example
        config_file = example_dir / "agent_actions.yml"
        if not config_file.exists():
            continue

        example_name = example_dir.name

        # Parse agent_actions.yml for description
        description = ""
        try:
            config_content = yaml.safe_load(config_file.read_text())
            if isinstance(config_content, dict):
                description = config_content.get("description", "")
        except Exception as e:
            logger.debug(
                "Failed to parse YAML config for example %s: %s", example_name, e, exc_info=True
            )

        # Scan for workflows
        workflow_dir = example_dir / "agent_workflow"
        workflows = []
        if workflow_dir.exists():
            for wf_dir in workflow_dir.iterdir():
                if wf_dir.is_dir():
                    workflows.append(wf_dir.name)

        # Check for other artifacts
        has_prompts = (example_dir / "prompt_store").exists()
        has_schemas = (example_dir / "schema").exists()
        has_tools = (example_dir / "tools").exists()

        # Count schemas and prompts
        schema_count = 0
        if has_schemas:
            schema_count = len(list((example_dir / "schema").glob("*.yml")))

        prompt_count = 0
        if has_prompts:
            prompt_count = len(list((example_dir / "prompt_store").glob("*.md")))

        tool_count = 0
        if has_tools:
            tool_count = len(list((example_dir / "tools").glob("*.py")))

        examples[example_name] = {
            "id": example_name,
            "name": example_name,
            "path": str(example_dir.relative_to(examples_dir.parent)),
            "description": description,
            "has_workflows": bool(workflows),
            "workflows": workflows,
            "workflow_count": len(workflows),
            "has_prompts": has_prompts,
            "prompt_count": prompt_count,
            "has_schemas": has_schemas,
            "schema_count": schema_count,
            "has_tools": has_tools,
            "tool_count": tool_count,
        }

    return examples


def scan_data_loaders() -> dict[str, Any]:
    """Scan for data loader implementations via AST parsing."""
    loaders: dict[str, Any] = {}
    loaders_dir = _PACKAGE_ROOT / "input" / "loaders"

    if not loaders_dir.exists():
        return loaders

    for py_file in loaders_dir.glob("*.py"):
        if py_file.name == "__init__.py":
            continue

        try:
            source = py_file.read_text()
            tree = ast.parse(source)

            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef):
                    continue

                # Check if it has BaseLoader, ISourceDataLoader, or ABC parent
                parent_names = []
                for base in node.bases:
                    if isinstance(base, ast.Name):
                        parent_names.append(base.id)
                    elif isinstance(base, ast.Subscript):
                        # BaseLoader[T] pattern
                        if isinstance(base.value, ast.Name):
                            parent_names.append(base.value.id)

                is_loader = any(
                    n in ("BaseLoader", "ISourceDataLoader", "IDataLoader") for n in parent_names
                )
                if not is_loader:
                    continue

                docstring = ast.get_docstring(node) or ""

                # Try to extract supported file types from supports_filetype method
                supported_types = []
                for item in node.body:
                    if isinstance(item, ast.FunctionDef) and item.name == "supports_filetype":
                        for stmt in ast.walk(item):
                            if isinstance(stmt, ast.Constant) and isinstance(stmt.value, str):
                                val = stmt.value
                                if val.startswith(".") or val in (
                                    "json",
                                    "csv",
                                    "tsv",
                                    "xml",
                                    "txt",
                                    "yaml",
                                    "yml",
                                ):
                                    supported_types.append(val)

                # Extract methods
                methods = []
                for item in node.body:
                    if isinstance(item, ast.FunctionDef) and not item.name.startswith("_"):
                        methods.append(item.name)

                loaders[node.name] = {
                    "id": node.name,
                    "name": node.name,
                    "source_file": py_file.name,
                    "docstring": docstring,
                    "supported_types": supported_types,
                    "base_class": parent_names[0] if parent_names else "",
                    "methods": methods,
                    "line": node.lineno,
                }

        except (OSError, SyntaxError, UnicodeDecodeError) as e:
            logger.debug("Could not scan data loaders from %s: %s", py_file, e)
            continue

    return loaders


def scan_processing_states() -> dict[str, Any]:
    """Scan for processing state/status enums and dataclasses."""
    processing_types: dict[str, Any] = {}
    types_file = _PACKAGE_ROOT / "processing" / "types.py"

    if not types_file.exists():
        return processing_types

    try:
        source = types_file.read_text()
        tree = ast.parse(source)

        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue

            docstring = ast.get_docstring(node) or ""

            # Check if Enum
            is_enum = any((isinstance(b, ast.Name) and b.id == "Enum") for b in node.bases)

            if is_enum:
                values = []
                for item in node.body:
                    if isinstance(item, ast.Assign):
                        for target in item.targets:
                            if isinstance(target, ast.Name):
                                val = None
                                comment = ""
                                if isinstance(item.value, ast.Constant):
                                    val = item.value.value
                                # Extract inline comment from source
                                if hasattr(item, "end_lineno"):
                                    line = source.splitlines()[item.lineno - 1]
                                    if "#" in line:
                                        comment = line.split("#", 1)[1].strip()
                                values.append(
                                    {
                                        "name": target.id,
                                        "value": val,
                                        "description": comment,
                                    }
                                )

                processing_types[node.name] = {
                    "id": node.name,
                    "type": "enum",
                    "docstring": docstring,
                    "values": values,
                    "value_count": len(values),
                }
                continue

            # Check if dataclass (has @dataclass decorator)
            is_dataclass = any(
                (isinstance(d, ast.Name) and d.id == "dataclass") for d in node.decorator_list
            )

            if is_dataclass:
                fields = []
                factory_methods = []

                for item in node.body:
                    if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                        field_name = item.target.id
                        field_type = ast.unparse(item.annotation) if item.annotation else "Any"
                        fields.append({"name": field_name, "type": field_type})

                    elif isinstance(item, ast.FunctionDef):
                        # Collect classmethod factories
                        is_classmethod = any(
                            (isinstance(d, ast.Name) and d.id == "classmethod")
                            for d in item.decorator_list
                        )
                        if is_classmethod:
                            method_doc = ast.get_docstring(item) or ""
                            factory_methods.append(
                                {
                                    "name": item.name,
                                    "docstring": method_doc,
                                }
                            )

                processing_types[node.name] = {
                    "id": node.name,
                    "type": "dataclass",
                    "docstring": docstring,
                    "fields": fields,
                    "field_count": len(fields),
                    "factory_methods": factory_methods,
                }

    except (OSError, SyntaxError, UnicodeDecodeError) as e:
        logger.debug("Could not scan processing states from %s: %s", types_file, e)

    return processing_types
