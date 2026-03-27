"""Regression tests for UDF scaffold template — B-6: no invalid input_type= kwarg."""

from pathlib import Path

TEMPLATE_PATH = (
    Path(__file__).parents[3]
    / "agent_actions"
    / "skills"
    / "agent-actions-workflow"
    / "assets"
    / "templates"
    / "udf_tool.py.template"
)


class TestUdfToolTemplate:
    """The scaffold template must not contain the invalid input_type= kwarg."""

    def test_template_exists(self):
        assert TEMPLATE_PATH.exists(), f"Template not found at {TEMPLATE_PATH}"

    def test_no_input_type_kwarg(self):
        content = TEMPLATE_PATH.read_text()
        # Check for the identifier itself (covers `input_type=` and `input_type =`)
        assert "input_type" not in content, (
            "udf_tool.py.template contains invalid 'input_type' kwarg — "
            "generated scaffolds will crash on import (B-6)"
        )

    def test_udf_tool_decorator_present(self):
        content = TEMPLATE_PATH.read_text()
        assert "@udf_tool()" in content
