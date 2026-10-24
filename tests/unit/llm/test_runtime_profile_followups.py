"""Response metadata of a named runtime keeps the OpenAI fields its wire carries."""

from __future__ import annotations

from agent_actions.utils.metadata.extractor import MetadataExtractor


class TestResponseMetadata:
    def test_a_runtime_keeps_its_own_name_and_the_openai_fields(self):
        response = {"model": "local", "system_fingerprint": "b1", "created": 1}

        local = MetadataExtractor.extract_from_response(response, provider="llamafile")
        cloud = MetadataExtractor.extract_from_response(response, provider="openai")

        assert local.provider == "llamafile"
        assert local.raw == cloud.raw == {"system_fingerprint": "b1", "created": 1}
