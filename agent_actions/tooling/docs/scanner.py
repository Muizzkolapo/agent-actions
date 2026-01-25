"""
Project scanner for finding workflow files and prompts.
"""

import ast
import re
from pathlib import Path
from typing import Dict, Any, List, Optional

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
                        logs_data["validation_errors"].append({
                            "target": data.get("target"),
                            "error": data.get("error"),
                            "field": data.get("field"),
                            "timestamp": meta.get("timestamp"),
                        })

                    # Collect validation warnings
                    if event_type == "ValidationWarningEvent":
                        logs_data["validation_warnings"].append({
                            "target": data.get("target"),
                            "warning": data.get("warning"),
                            "field": data.get("field"),
                            "timestamp": meta.get("timestamp"),
                        })

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
                "output_schema": None,
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

                    # Resolve output_type to TypedDict fields
                    output_type_name = decorator_args.get("output_type")
                    if output_type_name and typed_dicts and output_type_name in typed_dicts:
                        result["output_schema"] = {
                            "name": output_type_name,
                            "fields": typed_dicts[output_type_name],
                        }

                    break  # Found the UDF decorator, no need to check others

            return result

        except (SyntaxError, AttributeError, TypeError, IndexError, ValueError):
            return None
