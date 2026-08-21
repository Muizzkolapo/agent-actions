"""UDF discovery imports only udf_tool-declaring files; broken helpers must not block it."""

import logging
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


# ── Source encoding: discovery must decode like the import machinery ──

# PEP 263 cookie with a non-UTF-8 body. Python imports this fine.
_LATIN1_UDF = (
    "# -*- coding: latin-1 -*-\n"
    "from agent_actions import udf_tool\n"
    "\n"
    "# R\xe9duit les accents.\n"
    "@udf_tool()\n"
    "def strip_accents(data):\n"
    "    return data\n"
)

# Same, but registering the OTHER decorator the gate admits.
_LATIN1_VALIDATION = (
    "# -*- coding: latin-1 -*-\n"
    "from agent_actions import reprompt_validation\n"
    "\n"
    "# V\xe9rifie la citation.\n"
    '@reprompt_validation("answer must cite a source")\n'
    "def check_accent_citation(data):\n"
    "    return True\n"
)

_BOM_UDF = (
    "from agent_actions import udf_tool\n\n@udf_tool()\ndef tag_bom(data):\n    return data\n"
)


def test_udf_with_encoding_cookie_is_discovered(tmp_path):
    """A PEP 263 non-UTF-8 UDF registers — it must not be dropped at the decode step."""
    (tmp_path / "good.py").write_text(_GOOD_UDF)
    (tmp_path / "accent_tools.py").write_bytes(_LATIN1_UDF.encode("latin-1"))
    discover_udfs(tmp_path)
    assert "normalize_text" in UDF_REGISTRY
    assert "strip_accents" in UDF_REGISTRY


def test_validation_only_file_with_encoding_cookie_is_discovered(tmp_path):
    """The reprompt_validation side effect survives the same path as udf_tool.

    The gate admits two registering decorators; a decode fix that only covered
    one of them would leave the other silently unregistered.
    """
    (tmp_path / "good.py").write_text(_GOOD_UDF)
    (tmp_path / "accent_checks.py").write_bytes(_LATIN1_VALIDATION.encode("latin-1"))
    discover_udfs(tmp_path)
    assert "normalize_text" in UDF_REGISTRY
    assert "check_accent_citation" in _VALIDATION_REGISTRY


def test_udf_with_utf8_bom_is_discovered(tmp_path):
    """A BOM-prefixed UDF registers."""
    (tmp_path / "good.py").write_text(_GOOD_UDF)
    (tmp_path / "bom_tools.py").write_bytes(b"\xef\xbb\xbf" + _BOM_UDF.encode("utf-8"))
    discover_udfs(tmp_path)
    assert "normalize_text" in UDF_REGISTRY
    assert "tag_bom" in UDF_REGISTRY


def test_undecodable_file_is_skipped_loudly_without_aborting_discovery(tmp_path, caplog):
    """An undecodable file is skipped, warns, and does not abort the sweep.

    tokenize.open raises SyntaxError (not ValueError) for a bad encoding
    declaration, so the handler must cover it or discovery crashes outright.
    """
    (tmp_path / "good.py").write_text(_GOOD_UDF)
    (tmp_path / "bad_cookie.py").write_bytes(b"# -*- coding: not-a-real-codec -*-\nx = 1\n")
    with caplog.at_level(logging.WARNING):
        discover_udfs(tmp_path)
    assert "normalize_text" in UDF_REGISTRY
    assert any("bad_cookie" in r.getMessage() for r in caplog.records)
