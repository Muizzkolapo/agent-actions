"""
Project scanner for finding workflow files and prompts.
"""

import ast
import re
from pathlib import Path
from typing import Dict, Any, List, Optional

import yaml

from agent_actions.config.defaults import DocsDefaults
from agent_actions.output.response.loader import SchemaLoader
from .parser import extract_fields_for_docs


class ProjectScanner:
    """Scan project directory for agent workflows and prompts."""

    def __init__(self, project_root: str):
        self.project_root = Path(project_root).resolve()
        self.workflows_found = []

    def scan(self) -> Dict[str, Dict[str, Any]]:
        """
        Scan project directory for workflow files.

        Looks for:
        1. artefact/rendered_workflows/*.yml (rendered workflows)
        2. */agent_config/*.yml (original workflows for plan section)

        The artefact/ directory contains all generated files including
        rendered workflows, catalog, and runs data.

        Returns:
            Dict mapping workflow names to paths:
            {
                'workflow_name': {
                    'rendered': '/path/to/rendered.yml',
                    'original': '/path/to/original.yml'
                }
            }
        """
        workflows = {}
        artefact_dir = self.project_root / "artefact"

        # First, scan for rendered workflows inside artefact/
        rendered_dir = artefact_dir / "rendered_workflows"
        if rendered_dir.exists():
            for yaml_file in rendered_dir.glob("*.yml"):
                workflow_name = yaml_file.stem
                workflows[workflow_name] = {"rendered": str(yaml_file), "original": None}

        # Then, scan for original workflows with plan sections
        # Skip the artefact directory to avoid scanning generated docs
        for agent_config_dir in self.project_root.rglob("agent_config"):
            # Skip if inside artefact directory
            if artefact_dir in agent_config_dir.parents or agent_config_dir == artefact_dir:
                continue

            for yaml_file in agent_config_dir.glob("*.yml"):
                workflow_name = yaml_file.stem
                if workflow_name in workflows:
                    workflows[workflow_name]["original"] = str(yaml_file)
                else:
                    workflows[workflow_name] = {"rendered": None, "original": str(yaml_file)}

        return workflows

    # Cap README content to prevent catalog.json bloat
    _README_MAX_BYTES = DocsDefaults.README_MAX_BYTES

    def scan_readmes(self) -> Dict[str, str]:
        """Scan for README.md files alongside agent_config directories.

        Uses last-write-wins on duplicate workflow stems, matching the
        collision policy in scan() so README content stays paired with the
        workflow metadata that catalog generation actually uses.  rglob
        ordering is filesystem-dependent.

        READMEs larger than 100 KB are truncated with a trailing notice.
        """
        readmes: Dict[str, str] = {}
        artefact_dir = self.project_root / "artefact"

        for agent_config_dir in self.project_root.rglob("agent_config"):
            if artefact_dir in agent_config_dir.parents or agent_config_dir == artefact_dir:
                continue

            readme_path = agent_config_dir.parent / "README.md"
            if not readme_path.exists():
                continue

            try:
                content = readme_path.read_text(encoding="utf-8")
            except (IOError, UnicodeDecodeError):
                continue

            encoded = content.encode("utf-8")
            if len(encoded) > self._README_MAX_BYTES:
                truncated = encoded[: self._README_MAX_BYTES].decode("utf-8", errors="ignore")
                truncated = truncated.rsplit("\n", 1)[0]
                content = truncated + "\n\n---\n*README truncated (exceeds 100 KB)*\n"

            for yaml_file in agent_config_dir.glob("*.yml"):
                readmes[yaml_file.stem] = content

        return readmes

    def scan_prompts(self) -> Dict[str, Any]:
        """
        Scan project directory for prompt files.

        Looks for prompt_store/*.md files and extracts prompts using the pattern:
        {prompt prompt_name}
        ...content...
        {end_prompt}

        Returns:
            Dict mapping prompt names to prompt data:
            {
                'prompt_name': {
                    'id': 'prompt_name',
                    'name': 'prompt_name',
                    'content': '...',
                    'source_file': '/path/to/file.md',
                    'line_start': 1,
                    'line_end': 10
                }
            }
        """
        prompts = {}
        prompt_store_dir = self.project_root / "prompt_store"

        if not prompt_store_dir.exists():
            return prompts

        # Pattern to match {prompt name} ... {end_prompt}
        prompt_pattern = re.compile(r"\{prompt\s+(\w+)\}(.*?)\{end_prompt\}", re.DOTALL)

        for md_file in prompt_store_dir.glob("*.md"):
            content = md_file.read_text()

            # Find all prompts in this file
            for match in prompt_pattern.finditer(content):
                prompt_name = match.group(1)
                prompt_content = match.group(2).strip()

                # Calculate line numbers
                content_before = content[: match.start()]
                line_start = content_before.count("\n") + 1
                line_end = line_start + prompt_content.count("\n")

                prompts[prompt_name] = {
                    "id": prompt_name,
                    "name": prompt_name,
                    "content": prompt_content,
                    "source_file": str(md_file),
                    "source_file_name": md_file.name,
                    "line_start": line_start,
                    "line_end": line_end,
                    "length": len(prompt_content),
                }

        return prompts

    def scan_schemas(self) -> Dict[str, Any]:
        """
        Scan project directory for schema files.

        Returns:
            Dict mapping schema names to schema data
        """
        schemas = {}
        schema_dir = self.project_root / "schema"

        if not schema_dir.exists():
            return schemas

        for yml_file in schema_dir.glob("*.yml"):
            schema_name = yml_file.stem

            try:
                raw_schema = SchemaLoader.load_schema(schema_name, schema_dir)
            except FileNotFoundError:
                continue

            fields = extract_fields_for_docs(raw_schema)
            schema_type = raw_schema.get("type", "object")
            if "fields" in raw_schema:
                schema_type = "object"  # Unified format

            schemas[schema_name] = {
                "id": schema_name,
                "name": raw_schema.get("name", schema_name),
                "type": schema_type,
                "source_file": str(yml_file),
                "source_file_name": yml_file.name,
                "fields": fields,
                "field_count": len(fields),
            }

        return schemas

    def scan_workflow_data(self) -> Dict[str, Any]:
        """
        Scan project for SQLite target databases and export preview data.

        Iterates agent_io/target/ directories, opens each {workflow}.db via
        SQLiteBackend, and returns storage stats + sample records per node.

        Returns:
            Dict mapping workflow names to data summaries:
            {
                'workflow_name': {
                    'db_path': '...',
                    'db_size': '56.0 KB',
                    'source_count': 1,
                    'target_count': 3,
                    'nodes': {
                        'action_name': {
                            'record_count': 10,
                            'files': ['file.json'],
                            'preview': [{ ... }]
                        }
                    }
                }
            }
        """
        from agent_actions.storage.backends.sqlite_backend import SQLiteBackend

        workflow_data = {}
        artefact_dir = self.project_root / "artefact"

        for agent_io_dir in self.project_root.rglob("agent_io"):
            if artefact_dir in agent_io_dir.parents or agent_io_dir == artefact_dir:
                continue

            target_dir = agent_io_dir / "target"
            if not target_dir.exists():
                continue

            for db_file in target_dir.glob("*.db"):
                workflow_name = db_file.stem

                try:
                    backend = SQLiteBackend(
                        db_path=str(db_file),
                        workflow_name=workflow_name,
                    )
                    stats = backend.get_storage_stats()
                except Exception:
                    continue

                nodes = {}
                node_counts = stats.get("nodes", {})
                for action_name, record_count in node_counts.items():
                    try:
                        preview_result = backend.preview_target(action_name, limit=20)
                        nodes[action_name] = {
                            "record_count": record_count,
                            "files": preview_result.get("files", []),
                            "preview": preview_result.get("records", []),
                        }
                    except Exception:
                        nodes[action_name] = {
                            "record_count": record_count,
                            "files": [],
                            "preview": [],
                        }

                workflow_data[workflow_name] = {
                    "db_path": str(db_file),
                    "db_size": stats.get("db_size_human", "0 B"),
                    "source_count": stats.get("source_count", 0),
                    "target_count": stats.get("target_count", 0),
                    "nodes": nodes,
                }

        return workflow_data

    def scan_runs(self) -> Dict[str, Any]:
        """
        Scan project directory for workflow run data.

        Looks for agent_io/target/run_results.json and events.json files
        to extract execution metrics and history.

        Returns:
            Dict mapping workflow names to run data:
            {
                'workflow_name': {
                    'latest_run': {...},
                    'run_count': N,
                    'runs': [...]
                }
            }
        """
        import json

        runs_data = {}

        # Find all agent_io directories
        for agent_io_dir in self.project_root.rglob("agent_io"):
            # Skip if inside artefact directory
            artefact_dir = self.project_root / "artefact"
            if artefact_dir in agent_io_dir.parents or agent_io_dir == artefact_dir:
                continue

            target_dir = agent_io_dir / "target"
            if not target_dir.exists():
                continue

            # Extract workflow name from path (parent of agent_io is workflow dir)
            workflow_dir = agent_io_dir.parent
            # Get the workflow name from agent_config if possible
            agent_config_dir = workflow_dir / "agent_config"
            workflow_name = None
            if agent_config_dir.exists():
                yml_files = list(agent_config_dir.glob("*.yml"))
                if yml_files:
                    workflow_name = yml_files[0].stem

            if not workflow_name:
                workflow_name = workflow_dir.name

            # Load run_results.json for latest run metadata
            run_results_path = target_dir / "run_results.json"
            latest_run = None
            if run_results_path.exists():
                try:
                    with open(run_results_path, "r", encoding="utf-8") as f:
                        latest_run = json.load(f)
                except (json.JSONDecodeError, IOError):
                    pass

            # Load events.json for detailed execution data
            events_path = target_dir / "events.json"
            action_metrics = {}
            if events_path.exists():
                try:
                    action_metrics = self._extract_action_metrics(events_path)
                except Exception:
                    pass

            # Load .manifest.json for execution plan and per-action status
            manifest_path = target_dir / ".manifest.json"
            manifest_data = None
            if manifest_path.exists():
                try:
                    with open(manifest_path, "r", encoding="utf-8") as f:
                        manifest_data = json.load(f)
                except (json.JSONDecodeError, IOError):
                    pass

            runs_data[workflow_name] = {
                "workflow_name": workflow_name,
                "latest_run": latest_run,
                "action_metrics": action_metrics,
                "manifest": manifest_data,
                "run_results_path": str(run_results_path) if run_results_path.exists() else None,
                "events_path": str(events_path) if events_path.exists() else None,
                "manifest_path": str(manifest_path) if manifest_path.exists() else None,
            }

        return runs_data

    def scan_logs(self) -> Dict[str, Any]:
        """
        Scan project directory for global logs.

        Looks for logs/events.json for CLI and validation events.

        Returns:
            Dict with log data:
            {
                'events_path': '/path/to/logs/events.json',
                'recent_invocations': [...],
                'validation_errors': [...],
                'validation_warnings': [...]
            }
        """
        import json

        logs_data = {
            "events_path": None,
            "recent_invocations": [],
            "validation_errors": [],
            "validation_warnings": [],
        }

        logs_dir = self.project_root / "logs"
        if not logs_dir.exists():
            return logs_data

        events_path = logs_dir / "events.json"
        if not events_path.exists():
            return logs_data

        logs_data["events_path"] = str(events_path)

        try:
            with open(events_path, "r", encoding="utf-8") as f:
                invocations = {}
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    event_type = event.get("event_type")
                    meta = event.get("meta", {})
                    data = event.get("data", {})

                    # Track invocations
                    invocation_id = meta.get("invocation_id")
                    if invocation_id and invocation_id not in invocations:
                        invocations[invocation_id] = {
                            "invocation_id": invocation_id,
                            "timestamp": meta.get("timestamp"),
                            "workflow_name": meta.get("workflow_name"),
                            "command": None,
                        }

                    # Extract CLI command
                    if event_type == "CLIArgumentParsingEvent":
                        if invocation_id and invocation_id in invocations:
                            invocations[invocation_id]["command"] = data.get("command")

                    # Collect validation errors
                    if event_type == "ValidationErrorEvent":
                        logs_data["validation_errors"].append(
                            {
                                "target": data.get("target"),
                                "error": data.get("error"),
                                "field": data.get("field"),
                                "timestamp": meta.get("timestamp"),
                            }
                        )

                    # Collect validation warnings
                    if event_type == "ValidationWarningEvent":
                        logs_data["validation_warnings"].append(
                            {
                                "target": data.get("target"),
                                "warning": data.get("warning"),
                                "field": data.get("field"),
                                "timestamp": meta.get("timestamp"),
                            }
                        )

                # Get recent invocations (last 10)
                logs_data["recent_invocations"] = list(invocations.values())[-10:]

        except IOError:
            pass

        return logs_data

    def _extract_action_metrics(self, events_path: Path) -> Dict[str, Any]:
        """
        Extract per-action metrics from events.json file.

        Returns:
            Dict mapping action names to metrics:
            {
                'action_name': {
                    'execution_time': 0.5,
                    'tokens': {'prompt': 100, 'completion': 50},
                    'record_count': 10,
                    'success_count': 8,
                    'failed_count': 2
                }
            }
        """
        import json

        action_metrics = {}

        try:
            with open(events_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    event_type = event.get("event_type")
                    meta = event.get("meta", {})
                    data = event.get("data", {})
                    agent_name = meta.get("agent_name") or data.get("agent_name")

                    if not agent_name:
                        continue

                    if agent_name not in action_metrics:
                        action_metrics[agent_name] = {
                            "execution_time": None,
                            "tokens": {},
                            "record_count": 0,
                            "success_count": 0,
                            "failed_count": 0,
                            "filtered_count": 0,
                            "skipped_count": 0,
                        }

                    # Extract from AgentCompleteEvent
                    if event_type == "AgentCompleteEvent":
                        action_metrics[agent_name]["execution_time"] = data.get("execution_time")
                        action_metrics[agent_name]["record_count"] = data.get("record_count", 0)
                        if data.get("tokens"):
                            action_metrics[agent_name]["tokens"] = data["tokens"]

                    # Extract from ResultCollectionCompleteEvent
                    elif event_type == "ResultCollectionCompleteEvent":
                        action_metrics[agent_name]["success_count"] = data.get("total_success", 0)
                        action_metrics[agent_name]["failed_count"] = data.get("total_failed", 0)
                        action_metrics[agent_name]["filtered_count"] = data.get("total_filtered", 0)
                        action_metrics[agent_name]["skipped_count"] = data.get("total_skipped", 0)

                    # Extract from LLMResponseEvent for token counts
                    elif event_type == "LLMResponseEvent":
                        tokens = action_metrics[agent_name]["tokens"]
                        tokens["prompt_tokens"] = tokens.get("prompt_tokens", 0) + data.get(
                            "prompt_tokens", 0
                        )
                        tokens["completion_tokens"] = tokens.get("completion_tokens", 0) + data.get(
                            "completion_tokens", 0
                        )

        except IOError:
            pass

        return action_metrics

    def scan_tool_functions(self) -> Dict[str, Any]:
        """
        Scan project directory for tool function implementations.

        Looks for Python files in user_code/ directory and extracts
        function definitions decorated with @udf_tool, including their
        input/output type schemas defined as TypedDict classes.

        Returns:
            Dict mapping function names to function data:
            {
                'function_name': {
                    'found': True,
                    'file_path': '/path/to/file.py',
                    'signature': 'def function_name(arg1, arg2):',
                    'docstring': '...',
                    'source_code': '...',
                    'is_udf': True,
                    'input_schema': {'name': 'InputType', 'fields': [...]},
                    'output_schema': {'name': 'OutputType', 'fields': [...]}
                }
            }
        """
        tool_functions = {}

        # Look for user_code directory
        user_code_dirs = [
            self.project_root / "user_code",
            self.project_root / "tools",
            self.project_root / "functions",
        ]

        for user_code_dir in user_code_dirs:
            if not user_code_dir.exists():
                continue

            # Scan all Python files
            for py_file in user_code_dir.rglob("*.py"):
                try:
                    source = py_file.read_text()
                    tree = ast.parse(source)

                    # First pass: collect all TypedDict classes in this file
                    typed_dicts = self._extract_typed_dicts(tree)

                    for node in ast.walk(tree):
                        if isinstance(node, ast.FunctionDef):
                            func_name = node.name

                            # Skip private functions
                            if func_name.startswith("_"):
                                continue

                            # Extract function details including UDF metadata
                            func_data = self._extract_function_details(
                                node, source, py_file, typed_dicts
                            )
                            if func_data:
                                tool_functions[func_name] = func_data

                except (SyntaxError, UnicodeDecodeError):
                    # Skip files that can't be parsed
                    continue

        return tool_functions

    def _extract_typed_dicts(self, tree: ast.AST) -> Dict[str, List[Dict[str, str]]]:
        """
        Extract TypedDict class definitions from AST.

        Returns:
            Dict mapping class name to list of field definitions:
            {
                'MyInputType': [
                    {'name': 'field1', 'type': 'str', 'required': True},
                    {'name': 'field2', 'type': 'List[int]', 'required': False}
                ]
            }
        """
        typed_dicts = {}

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                # Check if this class inherits from TypedDict
                is_typed_dict = any(
                    (isinstance(base, ast.Name) and base.id == "TypedDict")
                    or (
                        isinstance(base, ast.Call)
                        and isinstance(base.func, ast.Name)
                        and base.func.id == "TypedDict"
                    )
                    for base in node.bases
                )

                if not is_typed_dict:
                    continue

                # Check for total=False in class definition (all fields optional)
                all_optional = False
                for base in node.bases:
                    if isinstance(base, ast.Call):
                        for keyword in base.keywords:
                            if keyword.arg == "total" and isinstance(keyword.value, ast.Constant):
                                all_optional = not keyword.value.value

                # Extract field definitions from class body
                fields = []
                for item in node.body:
                    if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                        field_name = item.target.id
                        field_type = ast.unparse(item.annotation) if item.annotation else "Any"
                        fields.append(
                            {"name": field_name, "type": field_type, "required": not all_optional}
                        )

                typed_dicts[node.name] = fields

        return typed_dicts

    def _extract_function_details(
        self,
        node: ast.FunctionDef,
        source: str,
        file_path: Path,
        typed_dicts: Optional[Dict[str, List[Dict[str, str]]]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Extract details from a function AST node, including UDF metadata."""
        try:
            # Get source lines
            lines = source.splitlines()

            # Build signature
            args = []
            for arg in node.args.args:
                arg_str = arg.arg
                # Add type annotation if present
                if arg.annotation:
                    arg_str += f": {ast.unparse(arg.annotation)}"
                args.append(arg_str)

            # Handle *args and **kwargs
            if node.args.vararg:
                args.append(f"*{node.args.vararg.arg}")
            if node.args.kwarg:
                args.append(f"**{node.args.kwarg.arg}")

            signature = f"def {node.name}({', '.join(args)})"

            # Add return type if present
            if node.returns:
                signature += f" -> {ast.unparse(node.returns)}"

            signature += ":"

            # Get docstring
            docstring = ast.get_docstring(node) or ""

            # Get source code (from function start to end)
            start_line = node.lineno - 1
            end_line = node.end_lineno if hasattr(node, "end_lineno") else start_line + 1
            source_code = "\n".join(lines[start_line:end_line])

            result = {
                "found": True,
                "file_path": str(file_path.relative_to(self.project_root)),
                "signature": signature,
                "docstring": docstring,
                "source_code": source_code,
                "line_start": node.lineno,
                "line_end": end_line,
                "is_udf": False,
                "input_schema": None,
            }

            # Check for @udf_tool decorator
            for decorator in node.decorator_list:
                decorator_name = None
                decorator_args = {}

                if isinstance(decorator, ast.Name):
                    decorator_name = decorator.id
                elif isinstance(decorator, ast.Call):
                    if isinstance(decorator.func, ast.Name):
                        decorator_name = decorator.func.id
                    elif isinstance(decorator.func, ast.Attribute):
                        decorator_name = decorator.func.attr

                    # Extract keyword arguments from decorator
                    for keyword in decorator.keywords:
                        if keyword.arg and isinstance(keyword.value, ast.Name):
                            decorator_args[keyword.arg] = keyword.value.id

                if decorator_name in ("udf_tool", "udf"):
                    result["is_udf"] = True

                    # Resolve input_type to TypedDict fields
                    input_type_name = decorator_args.get("input_type")
                    if input_type_name and typed_dicts and input_type_name in typed_dicts:
                        result["input_schema"] = {
                            "name": input_type_name,
                            "fields": typed_dicts[input_type_name],
                        }

                    break  # Found the UDF decorator, no need to check others

            return result

        except (SyntaxError, AttributeError, TypeError, IndexError, ValueError):
            return None

    # =========================================================================
    # New scan methods: vendors, errors, events, examples, loaders, processing
    # =========================================================================

    def scan_vendors(self) -> Dict[str, Any]:
        """
        Scan for LLM vendor configurations.

        Parses agent_actions/llm/config/vendor.py using AST to extract the
        VendorType enum and per-vendor config classes.

        Returns:
            Dict mapping vendor name to vendor data:
            {
                'openai': {
                    'id': 'openai',
                    'enum_value': 'openai',
                    'config_class': 'OpenAIConfig',
                    'fields': [{'name': 'api_key_env_name', 'default': 'OPENAI_API_KEY'}, ...],
                    'docstring': '...'
                }
            }
        """
        vendors = {}
        vendor_file = self.project_root.parent / "agent_actions" / "llm" / "config" / "vendor.py"

        # Also check if we're inside agent_actions already
        if not vendor_file.exists():
            vendor_file = (
                Path(__file__).resolve().parent.parent.parent / "llm" / "config" / "vendor.py"
            )

        if not vendor_file.exists():
            return vendors

        try:
            source = vendor_file.read_text()
            tree = ast.parse(source)

            # Extract VendorType enum values and config classes
            enum_values = {}
            config_classes = {}

            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef):
                    continue

                # Check for VendorType enum
                is_enum = any(
                    (isinstance(b, ast.Name) and b.id in ("Enum", "str")) for b in node.bases
                )
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
                                        if kw.arg == "default" and isinstance(
                                            kw.value, ast.Constant
                                        ):
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

        except (SyntaxError, UnicodeDecodeError, IOError):
            pass

        return vendors

    def scan_error_types(self) -> Dict[str, Any]:
        """
        Scan for error/exception class hierarchy.

        Parses agent_actions/errors/*.py using AST to extract the exception
        class hierarchy organized by domain category.

        Returns:
            Dict mapping category to error data:
            {
                'configuration': {
                    'id': 'configuration',
                    'base_class': 'ConfigurationError',
                    'errors': [
                        {'name': 'ConfigValidationError', 'parent': 'ConfigurationError',
                         'docstring': '...', 'source_file': 'configuration.py'}
                    ]
                }
            }
        """
        error_types = {}
        errors_dir = Path(__file__).resolve().parent.parent.parent / "errors"

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

            except (SyntaxError, UnicodeDecodeError, IOError):
                continue

        return error_types

    def scan_event_types(self) -> Dict[str, Any]:
        """
        Scan for event type definitions.

        Parses agent_actions/logging/events/types.py using AST to extract
        event dataclasses and their categories.

        Returns:
            Dict mapping category to event data:
            {
                'workflow': {
                    'id': 'workflow',
                    'events': [
                        {'name': 'WorkflowStartEvent', 'code': 'W001',
                         'docstring': '...', 'fields': [...]}
                    ]
                }
            }
        """
        event_types = {}
        events_file = (
            Path(__file__).resolve().parent.parent.parent / "logging" / "events" / "types.py"
        )

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
                is_event = any(
                    (isinstance(b, ast.Name) and b.id == "BaseEvent") for b in node.bases
                )
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
                            if isinstance(stmt, ast.Return) and isinstance(
                                stmt.value, ast.Constant
                            ):
                                event_code = stmt.value.value

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
                                    category = categories_map.get(cat_key, cat_key.lower())

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

        except (SyntaxError, UnicodeDecodeError, IOError):
            pass

        return event_types

    def scan_examples(self) -> Dict[str, Any]:
        """
        Scan for example projects in the examples/ directory.

        Looks for example project directories that contain agent_actions.yml
        and scans their structure (workflows, prompts, schemas, tools).

        Returns:
            Dict mapping example name to project data:
            {
                'book_catalog_enrichment': {
                    'id': 'book_catalog_enrichment',
                    'name': 'book_catalog_enrichment',
                    'path': 'examples/book_catalog_enrichment',
                    'has_workflows': True,
                    'workflows': ['workflow_name'],
                    'has_prompts': True,
                    'has_schemas': True,
                    'has_tools': True,
                    'description': '...'
                }
            }
        """
        examples = {}
        examples_dir = self.project_root.parent / "examples"

        if not examples_dir.exists():
            # Try sibling
            examples_dir = self.project_root / "examples"
        if not examples_dir.exists():
            # Try parent's parent (common layout)
            examples_dir = self.project_root.parent.parent / "examples"
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
            except Exception:
                pass

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

    def scan_data_loaders(self) -> Dict[str, Any]:
        """
        Scan for data loader implementations.

        Parses agent_actions/input/loaders/*.py using AST to extract
        BaseLoader subclasses and their supported file types.

        Returns:
            Dict mapping loader name to loader data:
            {
                'JsonLoader': {
                    'id': 'JsonLoader',
                    'name': 'JsonLoader',
                    'source_file': 'json.py',
                    'docstring': '...',
                    'supported_types': ['.json'],
                    'base_class': 'BaseLoader'
                }
            }
        """
        loaders = {}
        loaders_dir = Path(__file__).resolve().parent.parent.parent / "input" / "loaders"

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
                        n in ("BaseLoader", "ISourceDataLoader", "IDataLoader")
                        for n in parent_names
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

            except (SyntaxError, UnicodeDecodeError, IOError):
                continue

        return loaders

    def scan_processing_states(self) -> Dict[str, Any]:
        """
        Scan for processing state/status enums and types.

        Parses agent_actions/processing/types.py using AST to extract
        ProcessingStatus, ProcessingMode enums and key dataclasses.

        Returns:
            Dict with processing type data:
            {
                'ProcessingStatus': {
                    'id': 'ProcessingStatus',
                    'type': 'enum',
                    'values': [
                        {'name': 'SUCCESS', 'value': 'success', 'docstring': '...'}
                    ]
                },
                'ProcessingMode': {...},
                'ProcessingResult': {
                    'id': 'ProcessingResult',
                    'type': 'dataclass',
                    'fields': [...],
                    'factory_methods': [...]
                }
            }
        """
        processing_types = {}
        types_file = Path(__file__).resolve().parent.parent.parent / "processing" / "types.py"

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

        except (SyntaxError, UnicodeDecodeError, IOError):
            pass

        return processing_types
