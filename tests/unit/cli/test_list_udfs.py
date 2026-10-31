"""Tests for ListUDFsCommand.

Locks in the UDFLoadError enrichment introduced so the formatter renders the
same search_path / requested_path keys regardless of which CLI entry point
(workflow init, validate-udfs, or list-udfs) surfaced the failure.
"""

from unittest.mock import patch

import pytest

from agent_actions.cli.list_udfs import ListUDFsCommand
from agent_actions.errors import UDFLoadError
from agent_actions.utils.udf_management.registry import clear_registry


@pytest.fixture(autouse=True)
def _isolated_registry():
    """ListUDFsCommand.execute() calls clear_registry(); keep tests
    independent of any UDFs registered by sibling modules."""
    clear_registry()
    yield
    clear_registry()


class TestListUDFsCommandEnrichment:
    def test_udf_load_error_is_enriched_with_pipeline_context(self, tmp_path):
        user_code = tmp_path / "tools"
        user_code.mkdir()
        raised = UDFLoadError(module="proj.bad", file="bad.py", error="boom")

        cmd = ListUDFsCommand(str(user_code), json_output=True, verbose=False)
        with patch("agent_actions.cli.list_udfs.discover_udfs", side_effect=raised):
            with pytest.raises(UDFLoadError) as exc_info:
                cmd.execute()

        # Original identity is preserved.
        assert exc_info.value.context["module"] == "proj.bad"
        # Enrichment matches the keys validate_udfs / config_pipeline add, so
        # UDFLoadErrorFormatter renders consistently across entry points.
        assert exc_info.value.context["pipeline_stage"] == "list_udfs"
        assert exc_info.value.context["search_path"] == str(user_code.resolve())
        assert exc_info.value.context["requested_path"] == str(user_code)

    def test_discovery_sentinel_error_propagates_with_enrichment(self, tmp_path):
        user_code = tmp_path / "tools"
        user_code.mkdir()
        raised = UDFLoadError(
            module=UDFLoadError.DISCOVERY_SENTINEL,
            file=str(user_code),
            error="User code directory not found",
        )

        cmd = ListUDFsCommand(str(user_code), json_output=True, verbose=False)
        with patch("agent_actions.cli.list_udfs.discover_udfs", side_effect=raised):
            with pytest.raises(UDFLoadError) as exc_info:
                cmd.execute()

        assert exc_info.value.context["module"] == UDFLoadError.DISCOVERY_SENTINEL
        assert exc_info.value.context["pipeline_stage"] == "list_udfs"
        assert exc_info.value.context["search_path"] == str(user_code.resolve())
