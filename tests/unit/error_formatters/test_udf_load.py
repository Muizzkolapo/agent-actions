"""Tests for UDFLoadErrorFormatter."""

import pytest

from agent_actions.errors import UDFLoadError
from agent_actions.logging.errors.formatters.udf_load import (
    UDFLoadErrorFormatter,
    _first_non_none,
)
from agent_actions.logging.errors.translator import ErrorTranslator


@pytest.fixture
def formatter():
    return UDFLoadErrorFormatter()


@pytest.fixture
def udf_import_error():
    cause = ModuleNotFoundError("No module named 'markdown2'")
    cause.name = "markdown2"
    return UDFLoadError(
        module="run_thinkific_gen.apply_html_text",
        file="/proj/tools/run_thinkific_gen/apply_html_text.py",
        error="No module named 'markdown2'",
        cause=cause,
    )


def _context_for(exc: UDFLoadError) -> dict:
    """Approximate the per-exception slice of ErrorTranslator's merged context.

    Only the exception's own ``.context`` dict is copied — the full
    ``ErrorContextService.merge_exception_context`` also walks the chain and
    pulls allowed typed attributes off the outer exception. For these tests the
    UDFLoadError is the outer exception, so the simpler shape is sufficient.
    """
    return dict(exc.context or {})


class TestCanHandle:
    def test_claims_udf_load_error(self, formatter, udf_import_error):
        assert formatter.can_handle(udf_import_error, udf_import_error, str(udf_import_error))

    def test_claims_when_wrapped_as_root_cause(self, formatter, udf_import_error):
        wrapped = RuntimeError("workflow load failed")
        assert formatter.can_handle(wrapped, udf_import_error, str(udf_import_error))

    def test_claims_subclass_via_isinstance(self, formatter):
        class CustomUDFLoadError(UDFLoadError):
            pass

        exc = CustomUDFLoadError(module="x", file="/x.py", error="boom")
        assert formatter.can_handle(exc, exc, str(exc))

    def test_rejects_unrelated_error(self, formatter):
        exc = ValueError("something else")
        assert not formatter.can_handle(exc, exc, str(exc))


class TestImportFailureFormatting:
    def test_names_module_in_title(self, formatter, udf_import_error):
        result = formatter.format(
            udf_import_error,
            udf_import_error,
            str(udf_import_error),
            _context_for(udf_import_error),
        )
        assert result.title == "Failed to load UDF module 'run_thinkific_gen.apply_html_text'"

    def test_details_include_underlying_import_error(self, formatter, udf_import_error):
        result = formatter.format(
            udf_import_error,
            udf_import_error,
            str(udf_import_error),
            _context_for(udf_import_error),
        )
        assert (
            "Python could not import the UDF module: No module named 'markdown2'" in result.details
        )

    def test_file_path_surfaces_in_context(self, formatter, udf_import_error):
        result = formatter.format(
            udf_import_error,
            udf_import_error,
            str(udf_import_error),
            _context_for(udf_import_error),
        )
        assert result.context["file_path"] == "/proj/tools/run_thinkific_gen/apply_html_text.py"

    def test_module_key_omitted_from_context(self, formatter, udf_import_error):
        # Two layers of defense: (1) the formatter does not put 'module' into
        # ctx, and (2) UserError._SKIP_FIELDS lists 'module' so even if a
        # future change forgets layer 1, it still won't render.
        from agent_actions.logging.errors.user_error import _SKIP_FIELDS

        result = formatter.format(
            udf_import_error,
            udf_import_error,
            str(udf_import_error),
            _context_for(udf_import_error),
        )
        assert "module" not in (result.context or {})  # layer 1
        assert "module" in _SKIP_FIELDS  # layer 2

    def test_fix_names_missing_module_and_install_command(self, formatter, udf_import_error):
        result = formatter.format(
            udf_import_error,
            udf_import_error,
            str(udf_import_error),
            _context_for(udf_import_error),
        )
        assert "Python could not find the module 'markdown2'" in result.fix
        assert "uv add" in result.fix
        assert "pip install" in result.fix

    def test_fix_warns_about_pypi_import_name_mismatch(self, formatter, udf_import_error):
        # Real footgun: yaml→PyYAML, cv2→opencv-python — must not blindly suggest the import name.
        result = formatter.format(
            udf_import_error,
            udf_import_error,
            str(udf_import_error),
            _context_for(udf_import_error),
        )
        assert "PyPI" in result.fix or "package name may differ" in result.fix

    def test_fix_explains_blast_radius(self, formatter, udf_import_error):
        result = formatter.format(
            udf_import_error,
            udf_import_error,
            str(udf_import_error),
            _context_for(udf_import_error),
        )
        assert "single broken file blocks" in result.fix

    def test_dotted_submodule_preserved_in_missing_module_hint(self, formatter):
        cause = ModuleNotFoundError("No module named 'google.cloud.storage'")
        cause.name = "google.cloud.storage"
        exc = UDFLoadError(
            module="proj.tools.bad",
            file="/proj/tools/bad.py",
            error="No module named 'google.cloud.storage'",
            cause=cause,
        )
        result = formatter.format(exc, exc, str(exc), _context_for(exc))
        # Must NOT collapse to 'google' — real PyPI package is 'google-cloud-storage'.
        assert "'google.cloud.storage'" in result.fix
        assert "'google'" not in result.fix

    def test_does_not_extract_unrelated_module_from_root(self, formatter):
        """`root` (from extract_root_cause) may have fallen through
        __context__ and picked up an unrelated ModuleNotFoundError. The
        formatter must walk only the UDFLoadError's own __cause__ chain —
        never `root` — so the user isn't told to `pip install <unrelated>`."""
        udf_cause = ModuleNotFoundError("No module named 'markdown2'")
        udf_cause.name = "markdown2"
        udf_exc = UDFLoadError(
            module="proj.bad",
            file="/proj/bad.py",
            error="No module named 'markdown2'",
            cause=udf_cause,
        )
        unrelated = ModuleNotFoundError("No module named 'somewhere_else'")
        unrelated.name = "somewhere_else"
        # Simulate the translator handing in `unrelated` as the root (would
        # happen if extract_root_cause walked __context__ past the UDF chain).
        result = formatter.format(udf_exc, unrelated, str(udf_exc), _context_for(udf_exc))
        # The UDF's own cause must win.
        assert "Python could not find the module 'markdown2'" in result.fix
        assert "somewhere_else" not in result.fix

    def test_does_not_extract_module_reachable_only_via_root_context(self, formatter):
        """Stronger version of the previous test: a UDFLoadError with NO
        __cause__ chain (only message text) plus a `root` carrying a typed
        ModuleNotFoundError must NOT inherit the root's module name. Without
        the no-root guard, the regex fallback would still kick in on the
        message text — but if the UDFLoadError's error string doesn't mention
        the module name, root walking would be the only way for it to leak."""
        # UDFLoadError where the error message has no quoted module hint.
        udf_exc = UDFLoadError(
            module="proj.bad",
            file="/proj/bad.py",
            error="some non-import failure: invalid state",
        )
        # extract_root_cause might surface this from elsewhere in the call
        # stack via __context__ — must NOT be consulted.
        sneaky_root = ModuleNotFoundError("No module named 'pwned'")
        sneaky_root.name = "pwned"
        result = formatter.format(udf_exc, sneaky_root, str(udf_exc), _context_for(udf_exc))
        # No install hint; generic fix path.
        assert "Python could not find the module" not in result.fix
        assert "pwned" not in result.fix
        assert "Fix the import error" in result.fix

    def test_prefers_typed_name_attribute_over_message_regex(self, formatter):
        # Localized / reworded ModuleNotFoundError messages still surface the missing name.
        cause = ModuleNotFoundError("kein Modul namens 'markdown2' (translated message)")
        cause.name = "markdown2"
        exc = UDFLoadError(
            module="proj.tools.bad",
            file="/proj/tools/bad.py",
            error="kein Modul namens 'markdown2' (translated message)",
            cause=cause,
        )
        result = formatter.format(exc, exc, str(exc), _context_for(exc))
        assert "Python could not find the module 'markdown2'" in result.fix

    def test_non_import_error_gets_generic_fix(self, formatter):
        exc = UDFLoadError(
            module="proj.tools.bad",
            file="/proj/tools/bad.py",
            error="invalid syntax (bad.py, line 12)",
            cause=SyntaxError("invalid syntax"),
        )
        result = formatter.format(exc, exc, str(exc), _context_for(exc))
        assert "Fix the import error" in result.fix
        assert "Python could not find the module" not in result.fix

    def test_format_for_cli_lays_out_problem_file_and_fix(self, formatter, udf_import_error):
        result = formatter.format(
            udf_import_error,
            udf_import_error,
            str(udf_import_error),
            _context_for(udf_import_error),
        )
        rendered = result.format_for_cli()
        assert "Configuration Error: Failed to load UDF module" in rendered
        assert "Problem: Python could not import the UDF module" in rendered
        assert "File: /proj/tools/run_thinkific_gen/apply_html_text.py" in rendered
        assert "Fix: Python could not find the module 'markdown2'" in rendered


class TestDiscoveryFailureFormatting:
    """The <discovery> sentinel signals a directory problem, not an import failure."""

    def test_directory_not_found_uses_discovery_title(self, formatter):
        exc = UDFLoadError(
            module=UDFLoadError.DISCOVERY_SENTINEL,
            file="/no/such/dir",
            error="User code directory not found",
        )
        result = formatter.format(exc, exc, str(exc), _context_for(exc))
        assert result.title == "UDF discovery failed"
        # Sentinel must not leak into the title.
        assert UDFLoadError.DISCOVERY_SENTINEL not in result.title

    def test_directory_not_found_details_are_the_underlying_reason(self, formatter):
        exc = UDFLoadError(
            module=UDFLoadError.DISCOVERY_SENTINEL,
            file="/no/such/dir",
            error="User code directory not found",
        )
        result = formatter.format(exc, exc, str(exc), _context_for(exc))
        assert result.details == "User code directory not found"
        # Must not say "Python could not import" — there was nothing to import.
        assert "import" not in result.details.lower()

    def test_directory_not_found_suggests_fixing_path_not_imports(self, formatter):
        exc = UDFLoadError(
            module=UDFLoadError.DISCOVERY_SENTINEL,
            file="/no/such/dir",
            error="User code directory not found",
        )
        result = formatter.format(exc, exc, str(exc), _context_for(exc))
        assert "user-code directory" in result.fix or "tool_path" in result.fix
        assert "Fix the import error" not in result.fix
        assert "not installed" not in result.fix

    def test_directory_not_found_surfaces_path_in_context(self, formatter):
        exc = UDFLoadError(
            module=UDFLoadError.DISCOVERY_SENTINEL,
            file="/no/such/dir",
            error="User code directory not found",
        )
        result = formatter.format(exc, exc, str(exc), _context_for(exc))
        assert result.context["file_path"] == "/no/such/dir"


class TestFirstNonNone:
    """Direct coverage for the explicit-None coalescing helper.

    The formatter uses this instead of `or` so an empty-string `module`/`file`
    isn't silently swallowed (which would mask an upstream bug). These tests
    document and lock in those edge cases."""

    def test_returns_first_non_none(self):
        assert _first_non_none(None, "x", "y") == "x"

    def test_all_none_returns_none(self):
        assert _first_non_none(None, None, None) is None

    def test_no_args_returns_none(self):
        assert _first_non_none() is None

    def test_empty_string_is_returned_not_skipped(self):
        # Differs from `None or ""` (returns ""), `"" or "fallback"` (returns "fallback").
        assert _first_non_none(None, "", "fallback") == ""

    def test_zero_is_returned_not_skipped(self):
        assert _first_non_none(None, 0, "fallback") == 0

    def test_false_is_returned_not_skipped(self):
        assert _first_non_none(None, False, "fallback") is False


class TestRegistrationInTranslatorChain:
    def test_translator_uses_udf_load_formatter(self, udf_import_error):
        translator = ErrorTranslator()
        result = translator.translate(udf_import_error)
        assert result.title == "Failed to load UDF module 'run_thinkific_gen.apply_html_text'"
        # Sanity: the install-hint surfaced (i.e. function/config formatters did not steal it).
        assert "Python could not find the module 'markdown2'" in result.fix

    def test_translator_routes_discovery_sentinel_through_udf_formatter(self):
        # Full pipeline: ErrorContextService merges exc.context into the dict
        # passed to format(), and the chain ordering puts UDFLoadErrorFormatter
        # ahead of ConfigurationErrorFormatter (which would otherwise claim it).
        exc = UDFLoadError(
            module=UDFLoadError.DISCOVERY_SENTINEL,
            file="/no/such/dir",
            error="User code directory not found",
        )
        translator = ErrorTranslator()
        result = translator.translate(exc)
        assert result.title == "UDF discovery failed"
        assert UDFLoadError.DISCOVERY_SENTINEL not in result.title
        assert "user-code directory" in result.fix or "tool_path" in result.fix

    def test_translator_walks_cause_chain_for_missing_module_name(self):
        # End-to-end: UDFLoadError wraps ModuleNotFoundError via __cause__.
        # The formatter must pull `name` off the cause through the chain, not
        # rely on the message-text regex.
        cause = ModuleNotFoundError("kein Modul namens 'PyYAML' (localized)")
        cause.name = "PyYAML"
        exc = UDFLoadError(
            module="proj.tools.uses_yaml",
            file="/proj/tools/uses_yaml.py",
            error="kein Modul namens 'PyYAML' (localized)",
            cause=cause,
        )
        translator = ErrorTranslator()
        result = translator.translate(exc)
        assert result.title == "Failed to load UDF module 'proj.tools.uses_yaml'"
        assert "Python could not find the module 'PyYAML'" in result.fix

    def test_translator_routes_udf_with_yaml_cause_through_udf_formatter(self):
        """A UDF that loads malformed YAML at import time raises
        UDFLoadError(cause=yaml.YAMLError). The chain must render the UDF
        formatter (with module/file context), not the YAML formatter (which
        would strip that context)."""
        import yaml

        yaml_err = None
        try:
            yaml.safe_load("a:\n  b: : :")  # malformed
        except yaml.YAMLError as e:
            yaml_err = e
        assert yaml_err is not None

        exc = UDFLoadError(
            module="proj.uses_yaml",
            file="/proj/tools/uses_yaml.py",
            error=str(yaml_err),
            cause=yaml_err,
        )
        translator = ErrorTranslator()
        result = translator.translate(exc)
        assert result.title == "Failed to load UDF module 'proj.uses_yaml'"
        assert result.category == "Configuration Error"
        assert "YAML syntax error" not in result.title

    def test_translator_renders_pipeline_enrichment_keys(self):
        # config_pipeline enriches with search_path / requested_path; those
        # must surface in the CLI rendering, not just the merged-context dict.
        from agent_actions.errors import enrich_exception_context

        exc = UDFLoadError(module="proj.bad", file="bad.py", error="boom")
        enrich_exception_context(
            exc,
            pipeline_stage="discover_udfs",
            search_path="/abs/proj/tools",
            requested_path="tools",
        )
        translator = ErrorTranslator()
        result = translator.translate(exc)
        rendered = result.format_for_cli()
        assert "search_path: /abs/proj/tools" in rendered
        assert "requested_path: tools" in rendered
