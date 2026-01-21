"""
Project scanner for finding workflow files and prompts.
"""

import ast
import re
from pathlib import Path
from typing import Dict, Any, List, Optional

from agent_actions.response_processing.schema_loader import SchemaLoader
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
