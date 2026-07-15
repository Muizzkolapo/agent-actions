"""derive_source_guid: deterministic content identity over the RAW payload (spec 577).

No field is stripped by name. Identity stability across runs comes from callers deriving
over the raw record BEFORE the volatile framework envelope is added (see
``initial_pipeline``), not from name-based exclusion — so a user field named like a
framework field is part of identity and cannot silently collapse distinct records.
"""

from agent_actions.utils.id_generation import IDGenerator

# Frozen identities for raw stamp-site payloads: pins that 577 is a strict no-op for real
# data (values frozen by 576). A moved value means a persisted source_guid changed.
_GOLDEN = {
    "865e85c1-c292-5537-a9dc-aed6618263eb": {
        "content": "The mitochondria is the powerhouse of the cell."
    },
    "cac9d8de-ed99-5b95-948e-ebd0439e27e2": {
        "question": "What is 2+2?",
        "answer": "4",
        "metadata": {"src": "quiz.json", "row": 7},
    },
    "6aaf98d9-eb44-552f-adc8-2267290fda73": {"content": "A short online paragraph."},
    "bd78edf7-5e94-567f-b848-dd4c1de6142e": {"id": 42, "title": "Widget", "tags": ["a", "b"]},
}


def test_deterministic_for_same_content():
    r = {"id": "x", "content": "hello"}
    assert IDGenerator.derive_source_guid(r) == IDGenerator.derive_source_guid(dict(r))


def test_hashes_payload_as_given_no_name_stripping():
    # Fields that were previously stripped by name (node_id/target_id/batch_uuid) now
    # affect identity — records differing only in such a field are distinct, not collapsed.
    a = {"id": "x", "content": "c", "node_id": "n1"}
    b = {"id": "x", "content": "c", "node_id": "n2"}
    assert IDGenerator.derive_source_guid(a) != IDGenerator.derive_source_guid(b)


def test_distinguishes_different_content():
    assert IDGenerator.derive_source_guid({"id": "1"}) != IDGenerator.derive_source_guid(
        {"id": "2"}
    )


def test_non_dict_content():
    assert IDGenerator.derive_source_guid("text") == IDGenerator.derive_source_guid("text")
    assert IDGenerator.derive_source_guid("a") != IDGenerator.derive_source_guid("b")


def test_bare_string_matches_content_wrapper():
    # A text chunk is stamped from the raw string (task_preparer) at one site and from a
    # {"content": text} wrapper (initial_pipeline) at another — they must derive the SAME
    # guid so source_data and the disposition key agree.
    assert IDGenerator.derive_source_guid("chunk") == IDGenerator.derive_source_guid(
        {"content": "chunk"}
    )


def test_golden_identities_preserved():
    # No-op guard: hashing the raw payload reproduces the historical guid for real data.
    for gold, raw in _GOLDEN.items():
        assert IDGenerator.derive_source_guid(dict(raw)) == gold, f"identity moved for {raw!r}"
