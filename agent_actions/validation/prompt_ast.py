"""Jinja2 AST-based prompt template analysis."""

import logging
from dataclasses import dataclass
from typing import Any

from jinja2 import Environment, TemplateSyntaxError, nodes

logger = logging.getLogger(__name__)


@dataclass
class FieldUsage:
    """Information about how a field is used in the template."""

    variable_name: str  # Full variable path: 'seed.exam_syllabus.platform_name'
    used_in_context: str  # Where it's used: 'variable', 'filter', 'test', 'block'
    line_number: int | None = None


class PromptASTAnalyzer:
    """Analyzes Jinja2 templates via AST parsing to extract variable paths."""

    def __init__(self):
        """Initialize Jinja2 environment for AST parsing."""
        self.env = Environment()

    def _build_path_from_node(self, node: nodes.Node) -> str:
        """Build full attribute path by walking the AST node chain.

        Returns the full path string, or empty string if the path is rooted
        in an unsupported node (e.g., a literal).
        """
        if isinstance(node, nodes.Name):
            return str(node.name)
        elif isinstance(node, nodes.Getattr):
            parent_path = self._build_path_from_node(node.node)
            if not parent_path:
                # Parent is unsupported (e.g., literal) - skip entire path
                return ""
            return f"{parent_path}.{node.attr}"
        elif isinstance(node, nodes.Getitem):
            parent_path = self._build_path_from_node(node.node)
            if not parent_path:
                # Parent is unsupported (e.g., literal) - skip entire path
                return ""
            # Handle constant keys (strings/ints)
            if isinstance(node.arg, nodes.Const):
                key = node.arg.value
                if isinstance(key, str):
                    return f'{parent_path}["{key}"]'
                return f"{parent_path}[{key}]"
            # Dynamic key - can't resolve at parse time
            return f"{parent_path}[*]"
        else:
            # Unsupported node type (Const, Call, etc.) - return empty to skip
            return ""

    def _extract_full_paths(self, template_ast: nodes.Template) -> set[str]:
        """Extract full attribute paths from parsed AST, excluding declared variables."""
        paths: set[str] = set()

        # NOTE: We use id() to track node identity. This is safe because all AST
        # nodes remain alive for the duration of this method. Do not refactor to
        # process nodes lazily or across multiple calls without changing this.
        names_in_chains: set[int] = set()
        intermediate_nodes: set[int] = set()

        # Track declared variable names (loop vars, set assignments)
        # These have 'store' context and should be excluded from required references
        declared_names: set[str] = set()
        for node in template_ast.find_all(nodes.Name):
            if node.ctx == "store":
                declared_names.add(node.name)

        # First pass: identify chain structure
        for node in template_ast.find_all((nodes.Getattr, nodes.Getitem)):  # type: ignore[assignment]
            # Mark child nodes as intermediate (not outermost)
            if isinstance(node.node, nodes.Getattr | nodes.Getitem):  # type: ignore[attr-defined]
                intermediate_nodes.add(id(node.node))  # type: ignore[attr-defined]
            # Mark root Name nodes as part of chains
            current = node
            while isinstance(current, nodes.Getattr | nodes.Getitem):  # type: ignore[unreachable]
                current = current.node  # type: ignore[unreachable]
            if isinstance(current, nodes.Name):
                names_in_chains.add(id(current))

        # Second pass: build paths from OUTERMOST Getattr/Getitem nodes only
        # Skip intermediate nodes to avoid duplicates like seed.exam AND seed.exam.field
        for node in template_ast.find_all((nodes.Getattr, nodes.Getitem)):  # type: ignore[assignment]
            if id(node) in intermediate_nodes:
                continue  # Skip intermediate nodes
            path = self._build_path_from_node(node)
            if path:
                root_name = path.split(".")[0].split("[")[0]
                if root_name not in declared_names:
                    paths.add(path)

        # Third pass: add standalone Name nodes (not part of chains)
        # Only include 'load' context nodes that aren't declared
        for node in template_ast.find_all(nodes.Name):
            if id(node) not in names_in_chains:
                if node.ctx == "load" and node.name not in declared_names:
                    paths.add(node.name)

        return paths

    def extract_variables(self, template_source: str) -> set[str]:
        """Extract all variable references from a Jinja2 template using AST.

        Raises:
            ValueError: If the template has Jinja2 syntax errors.

        Examples:
            >>> analyzer = PromptASTAnalyzer()
            >>> template = '''
            ... Extract facts about {{ seed.exam_syllabus.platform_name }}
            ... {% if source.url %}
            ... Source: {{ source.url }}
            ... {% endif %}
            ... '''
            >>> vars = analyzer.extract_variables(template)
            >>> print(sorted(vars))
            ['seed.exam_syllabus.platform_name', 'source.url']
        """
        try:
            ast = self.env.parse(template_source)
            return self._extract_full_paths(ast)

        except TemplateSyntaxError as e:
            logger.error("Jinja2 syntax error in template: %s", e)
            raise ValueError(f"Template syntax error: {e}") from e

    def extract_referenced_variables(self, template_source: str) -> tuple[set[str], set[str]]:
        """Return (root_variables, full_paths) from a Jinja2 template.

        Examples:
            >>> analyzer = PromptASTAnalyzer()
            >>> template = "Facts: {{ seed.exam_syllabus }} and {{ source.content }}"
            >>> roots, paths = analyzer.extract_referenced_variables(template)
            >>> print(sorted(roots))
            ['seed', 'source']
            >>> print(sorted(paths))
            ['seed.exam_syllabus', 'source.content']
        """
        try:
            ast = self.env.parse(template_source)

            # Get all referenced variables (with full paths)
            full_paths = self._extract_full_paths(ast)

            # Extract root variables (before first dot or bracket)
            root_vars = set()
            for var in full_paths:
                # Handle both 'seed.field' and 'data["key"]' formats
                root_var = var.split(".")[0].split("[")[0]
                root_vars.add(root_var)

            return root_vars, full_paths

        except TemplateSyntaxError as e:
            raise ValueError(f"Template syntax error: {e}") from e

    def validate_template_syntax(self, template_source: str) -> tuple[bool, str | None]:
        """Return (is_valid, error_message) for Jinja2 template syntax.

        Examples:
            >>> analyzer = PromptASTAnalyzer()
            >>> valid, error = analyzer.validate_template_syntax("{{ field }}")
            >>> print(valid)
            True

            >>> valid, error = analyzer.validate_template_syntax("{{ field")
            >>> print(valid)
            False
            >>> print(error)
            unexpected end of template...
        """
        try:
            self.env.parse(template_source)
            return (True, None)
        except TemplateSyntaxError as e:
            return (False, str(e))

    def analyze_field_requirements(
        self, template_source: str, available_context: dict[str, set[str]]
    ) -> dict[str, Any]:
        """Analyze required fields and validate against available context.

        Examples:
            >>> analyzer = PromptASTAnalyzer()
            >>> template = "{{ seed.exam_syllabus }} and {{ missing.field }}"
            >>> context = {'seed': {'exam_syllabus'}}
            >>> results = analyzer.analyze_field_requirements(template, context)
            >>> print(results['missing_references'])
            ['missing']
        """
        root_vars, full_paths = self.extract_referenced_variables(template_source)

        missing_references = [
            root_var for root_var in root_vars if root_var not in available_context
        ]

        missing_fields = []
        for var_path in full_paths:
            parts = var_path.split(".")
            root_var = parts[0]

            if root_var in available_context and len(parts) > 1:
                first_field = parts[1]
                if first_field not in available_context[root_var]:
                    missing_fields.append(
                        {
                            "reference": root_var,
                            "field": first_field,
                            "full_path": var_path,
                            "available": sorted(available_context[root_var]),
                        }
                    )

        return {
            "required_roots": sorted(root_vars),
            "required_paths": sorted(full_paths),
            "missing_references": missing_references,
            "missing_fields": missing_fields,
            "is_valid": len(missing_references) == 0 and len(missing_fields) == 0,
        }

    def get_detailed_field_usage(self, template_source: str) -> list[dict[str, Any]]:
        """Return root variable names with line numbers and context.

        For full attribute paths, use extract_variables() instead.

        Examples:
            >>> analyzer = PromptASTAnalyzer()
            >>> template = '''
            ... {{ seed.exam_syllabus }}
            ... {{ source.content|upper }}
            ... {% if target.ready %}ready{% endif %}
            ... '''
            >>> usage = analyzer.get_detailed_field_usage(template)
            >>> len(usage)
            3
            >>> usage[0]['name']  # Returns 'seed', not 'seed.exam_syllabus'
            'seed'
        """
        template_ast = self.env.parse(template_source)
        usage_list = []

        for node in template_ast.find_all(nodes.Name):
            usage_list.append(
                {
                    "name": node.name,
                    "type": node.__class__.__name__,
                    "line": node.lineno,
                    "context": node.ctx,  # 'load', 'store', etc.
                }
            )

        return usage_list


def scan_prompt_fields_ast(template_str: str) -> set[str]:
    """Extract field references from a Jinja2 template using AST.

    Examples:
        >>> fields = scan_prompt_fields_ast("{{ seed.exam }} and {{ source.data }}")
        >>> print(sorted(fields))
        ['seed.exam', 'source.data']
    """
    prompt_analyzer = PromptASTAnalyzer()
    return prompt_analyzer.extract_variables(template_str)


def validate_prompt_fields_ast(
    template_str: str, available_context: dict[str, set[str]]
) -> tuple[bool, list[str]]:
    """Validate prompt fields against available context using AST parsing.

    Examples:
        >>> template = "{{ seed.exam }} and {{ source.content }}"
        >>> context = {'seed': {'exam'}, 'source': {'content'}}
        >>> valid, errors = validate_prompt_fields_ast(template, context)
        >>> print(valid)
        True

        >>> context = {'seed': {'exam'}}  # Missing 'source'
        >>> valid, errors = validate_prompt_fields_ast(template, context)
        >>> print(valid)
        False
        >>> print(errors[0])
        Missing reference: 'source'
    """
    prompt_analyzer = PromptASTAnalyzer()
    analysis_results = prompt_analyzer.analyze_field_requirements(template_str, available_context)

    errors = []

    for missing_ref in analysis_results["missing_references"]:
        errors.append(
            f"Missing reference: '{missing_ref}' (Available: {', '.join(available_context.keys())})"
        )

    for missing_field in analysis_results["missing_fields"]:
        errors.append(
            f"Missing field: '{missing_field['field']}' in "
            f"'{missing_field['reference']}' "
            f"(Available: {', '.join(missing_field['available'])})"
        )

    return (len(errors) == 0, errors)
