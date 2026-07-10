"""UDF discovery imports only udf_tool-declaring files; broken helpers must not block it."""

import sys

import pytest

from agent_actions.errors import UDFLoadError
from agent_actions.input.loaders.udf import discover_udfs
from agent_actions.processing.recovery.validation import _VALIDATION_REGISTRY
from agent_actions.utils.udf_management.registry import UDF_REGISTRY, clear_registry

_GOOD_UDF = (
    "from agent_actions import udf_tool\n"
    "\n"
    "@udf_tool()\n"
    "def normalize_text(data):\n"
    "    return data\n"
)

# Not a UDF; raises FileNotFoundError at import time.
_BROKEN_HELPER = 'with open(__file__ + ".missing.md") as fh:\n    TEMPLATE = fh.read()\n'

# Parseable, mentions the decorator name only in a comment, raises at import.
_MENTIONS_ONLY = (
    "# Formats release notes; unrelated to @udf_tool registration.\n"
    'raise RuntimeError("boom at import")\n'
)

# A real UDF whose import fails at runtime.
_BROKEN_UDF = (
    "from agent_actions import udf_tool\n"
    "import missing_dependency_zzz\n"
    "\n"
    "@udf_tool()\n"
    "def compute_metrics(data):\n"
    "    return data\n"
)

# A real UDF with a syntax error (missing colon) — unparseable but clearly UDF-intent.
_SYNTAX_UDF = (
    "from agent_actions import udf_tool\n\n@udf_tool()\ndef tag_records(data)\n    return data\n"
)

# Unparseable scratch file with no udf_tool mention at all.
_SYNTAX_HELPER = "def scratch(:\n    pass\n"

_ATTR_FORM_UDF = (
    "from agent_actions.utils.udf_management import registry\n"
    "\n"
    "@registry.udf_tool()\n"
    "def rewrite_labels(data):\n"
    "    return data\n"
)

# Registers a reprompt validator via import side effect; declares no udf_tool.
_VALIDATION_ONLY = (
    "from agent_actions import reprompt_validation\n"
    "\n"
    '@reprompt_validation("answer must cite a source")\n'
    "def check_citation(data):\n"
    "    return True\n"
)


def _evict_udf_modules():
    for name in [k for k in sys.modules if k.startswith("agent_actions._udfs.")]:
        sys.modules.pop(name, None)


@pytest.fixture(autouse=True)
def _isolated_registry():
    clear_registry()
    _VALIDATION_REGISTRY.clear()
    _evict_udf_modules()
    yield
    clear_registry()
    _VALIDATION_REGISTRY.clear()
    _evict_udf_modules()


def test_broken_non_udf_helper_does_not_block_discovery(tmp_path):
    (tmp_path / "good.py").write_text(_GOOD_UDF)
    (tmp_path / "formatting_tools.py").write_text(_BROKEN_HELPER)
    discover_udfs(tmp_path)
    assert "normalize_text" in UDF_REGISTRY


def test_decorator_mention_in_comment_does_not_make_a_helper_a_udf(tmp_path):
    (tmp_path / "good.py").write_text(_GOOD_UDF)
    (tmp_path / "release_notes.py").write_text(_MENTIONS_ONLY)
    discover_udfs(tmp_path)
    assert "normalize_text" in UDF_REGISTRY


def test_unparseable_helper_without_udf_mention_is_skipped(tmp_path):
    (tmp_path / "good.py").write_text(_GOOD_UDF)
    (tmp_path / "scratch_notes.py").write_text(_SYNTAX_HELPER)
    discover_udfs(tmp_path)
    assert "normalize_text" in UDF_REGISTRY


def test_broken_udf_file_still_raises(tmp_path):
    (tmp_path / "metrics_udf.py").write_text(_BROKEN_UDF)
    with pytest.raises(UDFLoadError) as exc_info:
        discover_udfs(tmp_path)
    assert "metrics_udf.py" in exc_info.value.context["file"]


def test_syntax_error_udf_file_still_raises(tmp_path):
    (tmp_path / "tags_udf.py").write_text(_SYNTAX_UDF)
    with pytest.raises(UDFLoadError) as exc_info:
        discover_udfs(tmp_path)
    assert "tags_udf.py" in exc_info.value.context["file"]


def test_attribute_form_decorator_is_discovered(tmp_path):
    (tmp_path / "labels_udf.py").write_text(_ATTR_FORM_UDF)
    discover_udfs(tmp_path)
    assert "rewrite_labels" in UDF_REGISTRY


def test_reprompt_validation_only_file_is_imported(tmp_path):
    (tmp_path / "citation_checks.py").write_text(_VALIDATION_ONLY)
    discover_udfs(tmp_path)
    assert "check_citation" in _VALIDATION_REGISTRY
