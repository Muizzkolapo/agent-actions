"""Custom YAML loader for handling template syntax in old workflow files."""
# too-few-public-methods: This is a utility class with a single responsibility
# too-many-locals: Complex template processing requires multiple local variables

import logging
import re
from typing import Any, Dict, List

import yaml

logger = logging.getLogger(__name__)


class TemplateYamlLoader:
    """Custom YAML loader that can handle template syntax."""

    def __init__(self):
        self.template_pattern = re.compile(r"\{\{\s*(\w+)\((.*?)\)\s*\}\}", re.DOTALL)

    def load_template_yaml(self, file_path: str) -> Dict[str, Any]:
        """Load YAML file with template syntax preprocessing."""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
        except FileNotFoundError:
            logger.exception("Template YAML file not found: %s", file_path)
            raise
        except PermissionError:
            logger.exception("Permission denied reading template YAML: %s", file_path)
            raise
        except (UnicodeDecodeError, IOError):
            logger.exception("Error reading template YAML: %s", file_path)
            raise

        # Preprocess the content to handle templates
        try:
            processed_content = self._preprocess_templates(content)
        except Exception as e:
            logger.exception(
                "Error preprocessing template syntax in %s: %s",
                file_path,
                e,
                extra={"file_path": file_path},
            )
            raise

        # Load as standard YAML
        try:
            return yaml.safe_load(processed_content)
        except yaml.YAMLError as e:
            logger.exception(
                "YAML parsing error in %s after template preprocessing: %s",
                file_path,
                e,
                extra={"file_path": file_path},
            )
            raise

    def _preprocess_templates(self, content: str) -> str:
        """Preprocess content to convert templates to parseable YAML."""
        # Handle multi-line templates
        processed_content = self._handle_multiline_templates(content)
        return processed_content

    def _handle_multiline_templates(self, content: str) -> str:
        """Handle templates that span multiple lines."""
        # Find all template blocks
        result = []
        lines = content.split("\n")
        i = 0

        while i < len(lines):
            line = lines[i]

            # Check if line starts a template
            if "{{" in line and "}}" not in line:
                # Multi-line template
                template_lines = [line]
                i += 1

                # Collect until we find the closing }}
                while i < len(lines) and "}}" not in lines[i]:
                    template_lines.append(lines[i])
                    i += 1

                if i < len(lines):
                    template_lines.append(lines[i])  # Include closing line

                # Process the complete template
                template_block = "\n".join(template_lines)
                processed_template = self._process_multiline_template(template_block)
                result.append(processed_template)

            elif "{{" in line and "}}" in line:
                # Single-line template
                processed_line = self._process_template_line(line)
                result.append(processed_line)
            else:
                result.append(line)

            i += 1

        return "\n".join(result)

    def _process_multiline_template(self, template_block: str) -> str:
        """Process a multi-line template block."""
        # Find the indentation from the first line
        first_line = template_block.split("\n")[0]
        indent = len(first_line) - len(first_line.lstrip())

        # Check if this is a list item (starts with -)
        is_list_item = first_line.strip().startswith("- {{")

        if is_list_item:
            # For list items, preserve the - marker
            base_indent = " " * indent
            item_indent = " " * (indent + 2)  # Content indent for list item
        else:
            base_indent = " " * indent
            item_indent = base_indent

        # Extract the complete template content
        template_content = template_block.strip()

        # Use regex to extract template type and parameters
        match = re.search(r"\{\{\s*(\w+)\((.*?)\)\s*\}\}", template_content, re.DOTALL)

        if not match:
            return template_block  # Return original if can't parse

        template_type, params = match.groups()

        # Parse parameters
        param_dict = self._parse_template_params(params)

        # Create YAML representation
        if is_list_item:
            yaml_lines = [f"{base_indent}- template_type: {template_type}"]
        else:
            yaml_lines = [f"{base_indent}template_type: {template_type}"]

        for key, value in param_dict.items():
            if isinstance(value, str):
                yaml_lines.append(f'{item_indent}{key}: "{value}"')
            elif isinstance(value, list):
                yaml_lines.append(f"{item_indent}{key}:")
                for item in value:
                    yaml_lines.append(f'{item_indent}  - "{item}"')
            else:
                yaml_lines.append(f"{item_indent}{key}: {value}")

        return "\n".join(yaml_lines)

    def _process_template_line(self, line: str) -> str:
        """Process a line containing template syntax."""
        # Find the indentation
        indent = len(line) - len(line.lstrip())
        indent_str = " " * indent

        # Extract template calls
        matches = self.template_pattern.findall(line)

        if not matches:
            return line

        template_type, params = matches[0]

        # Convert template to a regular YAML mapping
        param_dict = self._parse_template_params(params)

        # Create YAML representation
        yaml_lines = [f"{indent_str}template_type: {template_type}"]

        for key, value in param_dict.items():
            if isinstance(value, str):
                yaml_lines.append(f'{indent_str}{key}: "{value}"')
            elif isinstance(value, list):
                yaml_lines.append(f"{indent_str}{key}:")
                for item in value:
                    yaml_lines.append(f'{indent_str}  - "{item}"')
            else:
                yaml_lines.append(f"{indent_str}{key}: {value}")

        return "\n".join(yaml_lines)

    def _strip_quotes(self, value: str) -> str:
        """Strip surrounding quotes from a value."""
        if len(value) >= 2:
            if (value.startswith('"') and value.endswith('"')) or (
                value.startswith("'") and value.endswith("'")
            ):
                return value[1:-1]
        return value

    def _parse_boolean(self, value: str) -> Any:
        """Parse boolean string values. Returns original if not boolean."""
        if value.lower() == "true":
            return True
        if value.lower() == "false":
            return False
        return None

    def _parse_list_value(self, value: str) -> List[str]:
        """Parse a list value from bracketed string."""
        list_content = value[1:-1]
        if not list_content.strip():
            return []
        items = [item.strip().strip("\"'") for item in list_content.split(",")]
        return [item for item in items if item]

    def _parse_param_value(self, value: str) -> Any:
        """Parse a single parameter value, handling type conversions."""
        value = self._strip_quotes(value)

        # Check for boolean
        bool_result = self._parse_boolean(value)
        if bool_result is not None:
            return bool_result

        # Check for list
        if value.startswith("[") and value.endswith("]"):
            return self._parse_list_value(value)

        # Dict values are skipped (return None to signal skip)
        if value.startswith("{") and value.endswith("}"):
            return None

        return value

    def _parse_template_params(self, params_str: str) -> Dict[str, Any]:
        """Parse template parameters from string."""
        param_dict = {}
        params = self._smart_split_params(params_str)

        for param in params:
            param = param.strip()
            if "=" not in param:
                continue

            key, value = param.split("=", 1)
            key = key.strip()
            value = value.strip()

            parsed_value = self._parse_param_value(value)
            if parsed_value is not None:
                param_dict[key] = parsed_value

        return param_dict

    def _smart_split_params(self, params_str: str) -> List[str]:
        """Split parameters by comma, respecting nested brackets."""
        params = []
        current_param = ""
        bracket_depth = 0
        in_quotes = False
        quote_char = None

        for char in params_str:
            if char in ('"', "'") and not in_quotes:
                in_quotes = True
                quote_char = char
            elif char == quote_char and in_quotes:
                in_quotes = False
                quote_char = None
            elif not in_quotes:
                if char in ("[", "{"):
                    bracket_depth += 1
                elif char in ("]", "}"):
                    bracket_depth -= 1
                elif char == "," and bracket_depth == 0:
                    params.append(current_param.strip())
                    current_param = ""
                    continue

            current_param += char

        if current_param.strip():
            params.append(current_param.strip())

        return params


__all__ = ["TemplateYamlLoader"]
