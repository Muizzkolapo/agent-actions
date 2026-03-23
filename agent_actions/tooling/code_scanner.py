"""AST-based code introspection for tool function discovery.

Shared utility used by both the static analyzer (for input schema inference)
and the docs scanner (for catalog generation). Extracted from
tooling/docs/scanner/code_scanners.py to break a circular import:
    generator.py → schema_service → static_analyzer → schema_extractor
    → docs.scanner → docs.__init__ → generator.py
"""

import ast
import logging
from pathlib import Path
from typing import Any

from agent_actions.utils.path_utils import resolve_relative_to

logger = logging.getLogger(__name__)


def scan_tool_functions(project_root: Path, tool_paths: list[str] | None = None) -> dict[str, Any]:
    """Scan project directory for @udf_tool function implementations.

    Args:
        project_root: Project root directory.
        tool_paths: Configured tool directories (from ``tool_path`` in
            project config).  Defaults to ``["tools"]`` when not provided.
    """
    tool_functions = {}

    resolved_paths = tool_paths if tool_paths is not None else ["tools"]
    tool_dirs = [resolve_relative_to(p, project_root) for p in resolved_paths]

    for user_code_dir in tool_dirs:
        if not user_code_dir.exists():
            continue

        # Scan all Python files
        for py_file in user_code_dir.rglob("*.py"):
            try:
                source = py_file.read_text()
                tree = ast.parse(source)

                # First pass: collect all TypedDict classes in this file
                typed_dicts = extract_typed_dicts(tree)

                for node in ast.walk(tree):
                    if isinstance(node, ast.FunctionDef):
                        func_name = node.name

                        # Skip private functions
                        if func_name.startswith("_"):
                            continue

                        # Extract function details including UDF metadata
                        func_data = extract_function_details(
                            node, source, py_file, typed_dicts, project_root
                        )
                        if func_data:
                            tool_functions[func_name] = func_data

            except (SyntaxError, UnicodeDecodeError) as e:
                logger.debug("Failed to parse tool file %s: %s", py_file, e)
                continue

    return tool_functions


def extract_typed_dicts(tree: ast.AST) -> dict[str, list[dict[str, Any]]]:
    """Extract TypedDict class definitions from AST."""
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


def extract_function_details(
    node: ast.FunctionDef,
    source: str,
    file_path: Path,
    typed_dicts: dict[str, list[dict[str, Any]]] | None,
    project_root: Path,
) -> dict[str, Any] | None:
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
            "file_path": str(file_path.relative_to(project_root)),
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

    except (SyntaxError, AttributeError, TypeError, IndexError, ValueError) as e:
        logger.debug("Failed to extract function details: %s", e)
        return None
