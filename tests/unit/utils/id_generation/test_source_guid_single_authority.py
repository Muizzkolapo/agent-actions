"""Single authority for the source_guid exclusion set (spec 576).

derive_source_guid must exclude exactly the fields record.envelope declares
authoritative — as the same object — so the exclusion list cannot drift from the
field definitions. The set is the *volatile positional/identity* subset only: it
must NOT contain content-carrying framework fields (content, metadata), which are
the hash payload at the first-stage stamp sites.
"""

import pytest

from agent_actions.utils.id_generation import IDGenerator


def test_generator_shares_envelope_authority_object():
    """Single authority: generator excludes the SAME object record.envelope owns."""
    from agent_actions.record import envelope
    from agent_actions.utils.id_generation import generator

    assert hasattr(envelope, "SOURCE_GUID_EXCLUDED_FIELDS"), (
        "record.envelope must own the authoritative source_guid exclusion set "
        "(SOURCE_GUID_EXCLUDED_FIELDS)"
    )
    assert (
        getattr(generator, "SOURCE_GUID_EXCLUDED_FIELDS", None)
        is envelope.SOURCE_GUID_EXCLUDED_FIELDS
    ), "generator must import that same object, not maintain its own list"


def test_derive_excludes_whatever_the_authority_declares(monkeypatch):
    """Data-driven: extending the authoritative set changes what derive strips."""
    from agent_actions.utils.id_generation import generator

    if not hasattr(generator, "SOURCE_GUID_EXCLUDED_FIELDS"):
        pytest.fail("generator must consult record.envelope.SOURCE_GUID_EXCLUDED_FIELDS")

    probe = "_drift_probe_field"
    monkeypatch.setattr(
        generator,
        "SOURCE_GUID_EXCLUDED_FIELDS",
        generator.SOURCE_GUID_EXCLUDED_FIELDS | {probe},
    )
    a = {"content": "same", probe: "one"}
    b = {"content": "same", probe: "two"}
    assert generator.IDGenerator.derive_source_guid(a) == generator.IDGenerator.derive_source_guid(
        b
    )


def test_excluded_set_equals_the_historical_envelope_fields():
    """Pin the exact set: a no-op refactor must keep excluding precisely these."""
    from agent_actions.record import envelope

    if not hasattr(envelope, "SOURCE_GUID_EXCLUDED_FIELDS"):
        pytest.fail("record.envelope must own SOURCE_GUID_EXCLUDED_FIELDS")
    assert set(envelope.SOURCE_GUID_EXCLUDED_FIELDS) == {
        "source_guid",
        "target_id",
        "node_id",
        "parent_target_id",
        "root_target_id",
        "batch_id",
        "batch_uuid",
    }


def test_excluded_set_is_volatile_identity_subset_not_content():
    """Excluded fields are all framework fields, but content/metadata are payload."""
    from agent_actions.record import envelope

    if not hasattr(envelope, "SOURCE_GUID_EXCLUDED_FIELDS"):
        pytest.fail("record.envelope must own SOURCE_GUID_EXCLUDED_FIELDS")
    excl = envelope.SOURCE_GUID_EXCLUDED_FIELDS
    framework_plus_batch = envelope.RECORD_FRAMEWORK_FIELDS | {"batch_id", "batch_uuid"}
    assert excl <= framework_plus_batch, "every excluded field must be a framework field"
    assert "content" not in excl and "metadata" not in excl, (
        "content/metadata are the hash payload at the stamp sites, not envelope"
    )


def test_content_and_metadata_are_hash_payload_not_excluded():
    """content/metadata must enter the hash — excluding them collapses identity."""
    G = IDGenerator.derive_source_guid
    assert G({"content": "chunk A", "target_id": "t"}) != G(
        {"content": "chunk B", "target_id": "t"}
    )
    assert G({"q": "x", "metadata": {"a": 1}}) != G({"q": "x", "metadata": {"a": 2}})


def test_golden_projections_unchanged():
    """Failure-mode #2 guard: no persisted source_guid may change.

    Frozen values for representative stamp-site records under the current
    projection. If the exclusion ever strips a content-carrying field, these
    change and the test fails.
    """
    G = IDGenerator.derive_source_guid
    tid = "11111111-1111-1111-1111-111111111111"
    text_chunk = {
        "content": "The mitochondria is the powerhouse of the cell.",
        "batch_id": "batch_abc",
        "batch_uuid": "batch_abc_3",
        "target_id": tid,
        "parent_target_id": None,
        "root_target_id": tid,
        "node_id": "node_0_xyz",
    }
    json_row = {
        "question": "What is 2+2?",
        "answer": "4",
        "metadata": {"src": "quiz.json", "row": 7},
        "batch_id": "batch_abc",
        "batch_uuid": "batch_abc_7",
        "target_id": tid,
        "parent_target_id": None,
        "root_target_id": tid,
        "node_id": "node_0_xyz",
    }
    online_text = {"content": "A short online paragraph."}
    online_json = {"id": 42, "title": "Widget", "tags": ["a", "b"]}

    assert G(text_chunk) == "865e85c1-c292-5537-a9dc-aed6618263eb"
    assert G(json_row) == "cac9d8de-ed99-5b95-948e-ebd0439e27e2"
    assert G(online_text) == "6aaf98d9-eb44-552f-adc8-2267290fda73"
    assert G(online_json) == "bd78edf7-5e94-567f-b848-dd4c1de6142e"
    # bare-string normalization (575) still agrees with the {"content": …} wrapper
    assert G("A short online paragraph.") == G(online_text)
