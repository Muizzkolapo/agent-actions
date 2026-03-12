"""Tests for loader contract fixes (P1 #2).

Verifies that CSV and XML loaders can process files via file_path,
and that XLSX FileReader output (list[dict]) is usable directly.
"""

import csv

import pytest

from agent_actions.input.loaders.tabular import TabularLoader
from agent_actions.input.loaders.xml import XmlLoader


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
