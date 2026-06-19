"""Tests for loader contract fixes (P1 #2).

Verifies that CSV and XML loaders can process files via file_path,
and that XLSX FileReader output (list[dict]) is usable directly.
"""

import csv
import logging

import pytest

from agent_actions.input.loaders.tabular import TabularLoader
from agent_actions.input.loaders.xml import XmlLoader


@pytest.fixture
def _enable_log_propagation():
    """Re-enable propagation so caplog captures agent_actions logger output.

    LoggingBridgeHandler sets ``agent_actions.propagate = False`` at import time;
    caplog hooks the root logger and would otherwise see nothing.
    """
    aa_logger = logging.getLogger("agent_actions")
    orig = aa_logger.propagate
    aa_logger.propagate = True
    yield
    aa_logger.propagate = orig


@pytest.fixture
def csv_file(tmp_path):
    """Create a sample CSV file."""
    p = tmp_path / "sample.csv"
    with open(p, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["name", "age"])
        writer.writeheader()
        writer.writerow({"name": "Alice", "age": "30"})
        writer.writerow({"name": "Bob", "age": "25"})
    return str(p)


@pytest.fixture
def xml_file(tmp_path):
    """Create a sample XML file."""
    p = tmp_path / "sample.xml"
    p.write_text("<root><item>hello</item><item>world</item></root>")
    return str(p)


class TestTabularLoaderWithFilePath:
    def test_process_csv_via_file_path(self, csv_file):
        loader = TabularLoader({}, "test_agent")
        result = loader.process(content=None, file_path=csv_file)

        assert isinstance(result, list)
        assert len(result) == 2
        assert all(isinstance(row, dict) for row in result)
        assert result[0]["name"] == "Alice"
        assert result[1]["age"] == "25"


@pytest.mark.usefixtures("_enable_log_propagation")
class TestTabularLoaderEmptyCsvWarning:
    """Empty or header-only CSV must surface a warning, not silently no-op."""

    def test_header_only_csv_logs_warning(self, tmp_path, caplog):
        """Header-only CSV: 0 rows, warning emitted with file path context."""
        p = tmp_path / "header_only.csv"
        with open(p, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["name", "age"])
            writer.writeheader()

        loader = TabularLoader({}, "test_agent")
        with caplog.at_level("WARNING", logger="agent_actions.input.loaders.tabular"):
            result = loader.process(content=None, file_path=str(p))

        assert result == []
        assert any(
            "0 records" in rec.message and str(p) in rec.message for rec in caplog.records
        ), f"Expected empty-CSV warning mentioning {p}, got: {[r.message for r in caplog.records]}"

    def test_zero_byte_csv_logs_warning(self, tmp_path, caplog):
        """Zero-byte CSV: 0 rows, warning emitted."""
        p = tmp_path / "empty.csv"
        p.write_text("")

        loader = TabularLoader({}, "test_agent")
        with caplog.at_level("WARNING", logger="agent_actions.input.loaders.tabular"):
            result = loader.process(content=None, file_path=str(p))

        assert result == []
        assert any("0 records" in rec.message for rec in caplog.records)

    def test_inline_empty_content_logs_warning(self, caplog):
        """Inline empty content: warning still emitted, with '<inline content>' marker."""
        loader = TabularLoader({}, "test_agent")
        with caplog.at_level("WARNING", logger="agent_actions.input.loaders.tabular"):
            result = loader.process(content="name,age\n", file_path=None)

        assert result == []
        assert any("<inline content>" in rec.message for rec in caplog.records), (
            f"Expected inline-content warning, got: {[r.message for r in caplog.records]}"
        )

    def test_non_empty_csv_does_not_log_warning(self, csv_file, caplog):
        """Healthy CSV must not log the empty-input warning."""
        loader = TabularLoader({}, "test_agent")
        with caplog.at_level("WARNING", logger="agent_actions.input.loaders.tabular"):
            result = loader.process(content=None, file_path=csv_file)

        assert len(result) == 2
        assert not any("0 records" in rec.message for rec in caplog.records)


class TestXmlLoaderWithFilePath:
    def test_process_xml_via_file_path(self, xml_file):
        loader = XmlLoader({}, "test_agent")
        result = loader.process(content=None, file_path=xml_file)

        # XmlLoader.process returns an ET.Element (root)
        assert result.tag == "root"
        items = list(result)
        assert len(items) == 2
        assert items[0].text == "hello"


class TestXlsxDirectUsage:
    def test_xlsx_content_flows_through_add_batch_metadata(self):
        """XLSX list[dict] from FileReader feeds directly into _add_batch_metadata."""
        from agent_actions.input.preprocessing.staging.initial_pipeline import (
            _add_batch_metadata,
        )

        # Simulate what FileReader._read_xlsx() returns (list[dict] from pandas)
        xlsx_output = [
            {"name": "Alice", "age": 30},
            {"name": "Bob", "age": 25},
        ]
        result = _add_batch_metadata(xlsx_output, "batch_test", "node_0")

        assert len(result) == 2
        assert result[0]["name"] == "Alice"
        assert result[0]["batch_id"] == "batch_test"
        assert "source_guid" in result[0]
        assert result[1]["age"] == 25
