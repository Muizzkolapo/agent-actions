"""The API data source writes a staging document, so it must write the one shape."""

import io
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from agent_actions.errors import AgentActionsError, ConfigurationError
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
    """Resolve once, then leave *payload* in the cache file as an older version wrote it."""
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


class TestACacheWrittenBeforeTheDocumentRule:
    def test_it_is_brought_to_the_document_rule(self, tmp_path):
        _cache_of(tmp_path, ENVELOPE)
        assert json.loads(_resolve_again(tmp_path).read_text()) == [ENVELOPE]

    def test_it_stages_the_record_it_always_staged(self, tmp_path):
        _cache_of(tmp_path, ENVELOPE)
        rows = _stage(_resolve_again(tmp_path))
        assert [row["content"]["source"] for row in rows] == [ENVELOPE]

    def test_a_scalar_cache_is_brought_over_too(self, tmp_path):
        _cache_of(tmp_path, 42)
        assert json.loads(_resolve_again(tmp_path).read_text()) == [42]


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


class TestEveryEntryTheWalkStages:
    """The cache directory is the input directory; the rule must cover what is staged."""

    def test_an_entry_left_by_another_action_is_brought_over(self, tmp_path):
        cache = _cache_of(tmp_path, [{"id": 1}])
        sibling = cache.parent / "fetch_tickets.json"
        sibling.write_text(json.dumps(ENVELOPE))
        _resolve_again(tmp_path)
        assert json.loads(sibling.read_text()) == [ENVELOPE]

    def test_such_an_entry_then_stages(self, tmp_path):
        cache = _cache_of(tmp_path, [{"id": 1}])
        sibling = cache.parent / "fetch_tickets.json"
        sibling.write_text(json.dumps(ENVELOPE))
        _resolve_again(tmp_path)
        assert [row["content"]["source"] for row in _stage(sibling)] == [ENVELOPE]

    def test_an_entry_beside_a_freshly_fetched_one_is_brought_over(self, tmp_path):
        """A renamed action fetches under its new name; the old name still stages."""
        cache = _cache_of(tmp_path, [{"id": 1}])
        legacy = cache.parent / "fetch_tickets.json"
        legacy.write_text(json.dumps(ENVELOPE))
        body = json.dumps([{"id": 9}]).encode()
        with patch("urllib.request.urlopen", return_value=_Response(body)):
            resolve_start_node_data_source(
                Path(tmp_path), {"type": "api", "url": "https://api.example.com/items"}, "pull"
            )
        assert json.loads(legacy.read_text()) == [ENVELOPE]


class TestWhatTheWalkSkipsTheRuleLeavesAlone:
    """Reading an entry the runner never stages turns a fine run into a failed one."""

    def _poison(self, cache, name):
        target = cache.parent / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"\x00\x05\x16\x07not json at all")
        return target

    def test_a_macos_sidecar_does_not_fail_the_resolve(self, tmp_path):
        """A Finder copy onto SMB/exFAT leaves ._name.json beside name.json."""
        cache = _cache_of(tmp_path, [{"id": 1}])
        self._poison(cache, "._extract.json")
        _resolve_again(tmp_path)
        assert json.loads(cache.read_text()) == [{"id": 1}]

    def test_an_entry_under_batch_does_not_fail_the_resolve(self, tmp_path):
        cache = _cache_of(tmp_path, [{"id": 1}])
        self._poison(cache, "batch/job.json")
        _resolve_again(tmp_path)
        assert json.loads(cache.read_text()) == [{"id": 1}]

    def test_a_directory_named_like_an_entry_does_not_fail_the_resolve(self, tmp_path):
        cache = _cache_of(tmp_path, [{"id": 1}])
        (cache.parent / "weird.json").mkdir()
        _resolve_again(tmp_path)
        assert json.loads(cache.read_text()) == [{"id": 1}]

    def test_a_sidecar_is_not_rewritten_either(self, tmp_path):
        cache = _cache_of(tmp_path, [{"id": 1}])
        sidecar = self._poison(cache, "._extract.json")
        before = sidecar.read_bytes()
        _resolve_again(tmp_path)
        assert sidecar.read_bytes() == before


class TestACacheThatCannotBeRead:
    def test_it_fails_naming_the_file_and_the_remedy(self, tmp_path):
        cache = _cache_of(tmp_path, ENVELOPE)
        cache.write_text("{not json")
        with pytest.raises(ConfigurationError) as caught:
            _resolve_again(tmp_path)
        assert "_remote_cache" in str(caught.value)
        assert str(cache) in str(caught.value.context.values()) or str(cache) in str(caught.value)
