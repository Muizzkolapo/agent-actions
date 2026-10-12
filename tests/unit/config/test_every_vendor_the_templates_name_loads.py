"""Each `model_vendor` a shipped template names is a vendor the loader accepts.

The templates are what a new project is started from. Two named vendors no provider
exists for, so a project begun from the multi-vendor workflow failed to load.
"""

import re
from pathlib import Path

import pytest

from agent_actions.errors import ConfigValidationError
from agent_actions.output.response.expander_validation import validate_vendor_exists

TEMPLATES = Path(__file__).resolve().parents[3] / "docs.agent-actions" / "templates"

# `model_vendor: x`, commented or not, and the "Supported vendors: a, b, c" line.
_WRITTEN = re.compile(r"""model_vendor:[ \t]*["']?([A-Za-z0-9_-]+)""")
_LISTED = re.compile(r"supported vendors:[ \t]*([^\n]+)", re.IGNORECASE)


def _names() -> list[tuple[str, str]]:
    found = []
    for path in sorted(p for p in TEMPLATES.rglob("*") if p.is_file()):
        text = path.read_text()
        for name in _WRITTEN.findall(text):
            found.append((str(path.relative_to(TEMPLATES)), name))
        for line in _LISTED.findall(text):
            found.extend(
                (str(path.relative_to(TEMPLATES)), n.strip().strip("\"'")) for n in line.split(",")
            )
    return found


@pytest.fixture(scope="module")
def names():
    if not TEMPLATES.exists():
        pytest.skip("docs not present")
    return _names()


def test_the_scan_finds_the_vendors_the_templates_name(names):
    """Control: the scan is not vacuous."""
    assert {"openai", "anthropic", "gemini", "groq"} <= {name for _, name in names}


@pytest.mark.parametrize(
    "text, expected",
    [
        ('model_vendor: "deepseek"', ["deepseek"]),
        ("{name: x, model_vendor: perplexity}", ["perplexity"]),
        ("# Example: model_vendor: deepseek", ["deepseek"]),
        ("# Supported Vendors: openai, 'deepseek'", ["openai", "deepseek"]),
    ],
)
def test_the_scan_reads_the_spellings_a_template_could_use(text, expected, tmp_path):
    """Each spelling a bad vendor could hide in must be found, or the test below passes
    over it."""
    found = _WRITTEN.findall(text)
    for line in _LISTED.findall(text):
        found.extend(n.strip().strip("\"'") for n in line.split(","))

    assert found == expected


def test_every_named_vendor_is_accepted(names):
    refused = []
    for where, name in names:
        try:
            validate_vendor_exists(name, "template")
        except ConfigValidationError:
            refused.append(f"{where}: {name}")

    assert sorted(set(refused)) == []
