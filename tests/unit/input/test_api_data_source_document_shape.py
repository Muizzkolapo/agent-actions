"""The API data source writes a staging document, so it must write the one shape."""

import io
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from agent_actions.errors import AgentActionsError
from agent_actions.input.loaders.data_source import resolve_start_node_data_source
from agent_actions.input.loaders.file_reader import FileReader
from agent_actions.input.preprocessing.staging.initial_pipeline import (
    DataPreparationContext,
    _prepare_online_data,
)

ENVELOPE = {"count": 2, "results": [{"id": 1}, {"id": 2}]}


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _fetch(tmp_path, payload, url="https://api.example.com/items"):
    """Resolve an API data source against *payload* and return its cache file."""
    body = json.dumps(payload).encode()
    with patch("urllib.request.urlopen", return_value=_Response(body)):
        result = resolve_start_node_data_source(
            Path(tmp_path), {"type": "api", "url": url}, "extract"
        )
    return Path(result.directories[0]) / "extract.json"


def _stage(cache_file):
    ctx = DataPreparationContext(
        content=FileReader(str(cache_file)).read(),
        file_type=".json",
        agent_config={},
        file_path=str(cache_file),
        agent_name="extract",
        idx=0,
    )
    rows, _ = _prepare_online_data(ctx)
    return rows


class TestTheCacheFileIsAStagingDocument:
    def test_an_object_response_is_cached_as_a_list(self, tmp_path):
        assert json.loads(_fetch(tmp_path, ENVELOPE).read_text()) == [ENVELOPE]

    def test_a_list_response_is_cached_unchanged(self, tmp_path):
        rows = [{"id": 1}, {"id": 2}]
        assert json.loads(_fetch(tmp_path, rows).read_text()) == rows

    def test_an_empty_list_response_is_cached_unchanged(self, tmp_path):
        assert json.loads(_fetch(tmp_path, []).read_text()) == []


class TestItStagesWhatItStagedBefore:
    def test_an_object_response_is_one_record_holding_the_response(self, tmp_path):
        rows = _stage(_fetch(tmp_path, ENVELOPE))
        assert [row["content"]["source"] for row in rows] == [ENVELOPE]

    def test_a_list_response_is_one_record_per_element(self, tmp_path):
        payload = [{"id": 1}, {"id": 2}]
        rows = _stage(_fetch(tmp_path, payload))
        assert [row["content"]["source"] for row in rows] == payload

    def test_an_empty_list_response_stages_nothing(self, tmp_path):
        assert _stage(_fetch(tmp_path, [])) == []

    def test_a_scalar_response_is_still_refused_as_a_row(self, tmp_path):
        with pytest.raises(AgentActionsError) as caught:
            _stage(_fetch(tmp_path, 42))
        assert caught.value.context["row_index"] == 0
        assert caught.value.context["row_type"] == "int"

    def test_no_api_response_is_refused_as_a_document(self, tmp_path):
        """The user cannot wrap a file the framework wrote; the producer must."""
        for payload in (ENVELOPE, [{"id": 1}], [], 42, "text", None):
            cache = _fetch(tmp_path, payload, url=f"https://api.example.com/{payload!r}")
            assert isinstance(json.loads(cache.read_text()), list)


def _cache_of(tmp_path, payload, url="https://api.example.com/items"):
    """Resolve once, then leave *payload* in the cache file."""
    cache = _fetch(tmp_path, [{"seed": True}], url=url)
    cache.write_text(json.dumps(payload))
    return cache


def _resolve_again(tmp_path, url="https://api.example.com/items"):
    """Resolve with the cache already populated; re-fetching is a failure."""
    with patch("urllib.request.urlopen", side_effect=AssertionError("re-fetched a warm cache")):
        result = resolve_start_node_data_source(
            Path(tmp_path), {"type": "api", "url": url}, "extract"
        )
    return Path(result.directories[0]) / "extract.json"


class TestACacheAlreadyHoldingADocument:
    def test_it_is_left_exactly_as_it_was(self, tmp_path):
        rows = [{"id": 1}, {"id": 2}]
        cache = _cache_of(tmp_path, rows)
        before = cache.read_bytes()
        assert _resolve_again(tmp_path).read_bytes() == before

    def test_an_empty_document_is_left_alone(self, tmp_path):
        cache = _cache_of(tmp_path, [])
        before = cache.read_bytes()
        assert _resolve_again(tmp_path).read_bytes() == before

    def test_an_entry_beside_it_is_not_read(self, tmp_path):
        """The resolve checks only the cache file of this action."""
        cache = _cache_of(tmp_path, [{"id": 1}])
        sibling = cache.parent / "fetch_tickets.json"
        sibling.write_bytes(b"\x00\x05not json at all")
        before = sibling.read_bytes()
        _resolve_again(tmp_path)
        assert sibling.read_bytes() == before


class TestACacheHoldingNoDocumentIsFetchedAgain:
    @pytest.mark.parametrize(
        "content",
        [json.dumps(ENVELOPE), json.dumps(42), "{not json", ""],
        ids=["object", "scalar", "not_json", "empty_file"],
    )
    def test_it_is_overwritten_with_the_response(self, tmp_path, content):
        cache = _cache_of(tmp_path, [])
        cache.write_text(content)
        fetched = _fetch(tmp_path, ENVELOPE)
        assert fetched == cache
        assert json.loads(cache.read_text()) == [ENVELOPE]


def test_a_directory_at_the_cache_path_is_refused_before_any_fetch(tmp_path):
    cache = _fetch(tmp_path, [{"seed": True}])
    cache.unlink()
    cache.mkdir()

    with pytest.raises(AgentActionsError, match="is a directory"):
        _resolve_again(tmp_path)
