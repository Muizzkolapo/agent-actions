"""Two sites #1571 left reading vendor names: the batch action validator and response metadata.

Each llamafile assertion is paired with the vendor that site always handled.
"""

from __future__ import annotations

from types import SimpleNamespace

from agent_actions.utils.metadata.extractor import MetadataExtractor
from agent_actions.validation.action_validators.vendor_compatibility_validator import (
    VendorCompatibilityValidator,
)


def _batch_warnings(vendor: str) -> list[str]:
    context = SimpleNamespace(
        normalized_entry={"run_mode": "batch", "model_vendor": vendor}, description="a1"
    )
    return VendorCompatibilityValidator().validate(context).warnings


class TestTheBatchActionValidator:
    def test_does_not_call_a_runtimes_refused_batch_safe_to_ignore(self):
        assert _batch_warnings("llamafile") == []

    def test_still_warns_for_a_vendor_it_cannot_place(self):
        assert len(_batch_warnings("cohere")) == 1


class TestResponseMetadata:
    def test_a_runtime_keeps_its_own_name_and_the_openai_fields(self):
        response = {"model": "local", "system_fingerprint": "b1", "created": 1}

        local = MetadataExtractor.extract_from_response(response, provider="llamafile")
        cloud = MetadataExtractor.extract_from_response(response, provider="openai")

        assert local.provider == "llamafile"
        assert local.raw == cloud.raw == {"system_fingerprint": "b1", "created": 1}
