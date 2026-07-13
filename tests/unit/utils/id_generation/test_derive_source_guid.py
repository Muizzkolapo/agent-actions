"""derive_source_guid: deterministic content identity, envelope excluded."""

from agent_actions.utils.id_generation import IDGenerator


def test_deterministic_for_same_content():
    r = {"id": "x", "content": "hello"}
    assert IDGenerator.derive_source_guid(r) == IDGenerator.derive_source_guid(dict(r))


def test_excludes_volatile_envelope_fields():
    # Same content, different per-run envelope → same identity.
    a = {"id": "x", "content": "c", "target_id": "t1", "batch_uuid": "b_0", "node_id": "n1"}
    b = {"id": "x", "content": "c", "target_id": "t2", "batch_uuid": "b_9", "node_id": "n2"}
    assert IDGenerator.derive_source_guid(a) == IDGenerator.derive_source_guid(b)


def test_ignores_an_already_set_source_guid():
    a = {"content": "c"}
    b = {"content": "c", "source_guid": "pre-existing"}
    assert IDGenerator.derive_source_guid(a) == IDGenerator.derive_source_guid(b)


def test_distinguishes_different_content():
    assert IDGenerator.derive_source_guid({"id": "1"}) != IDGenerator.derive_source_guid(
        {"id": "2"}
    )


def test_non_dict_content():
    assert IDGenerator.derive_source_guid("text") == IDGenerator.derive_source_guid("text")
    assert IDGenerator.derive_source_guid("a") != IDGenerator.derive_source_guid("b")


def test_bare_string_matches_content_wrapper():
    # A text chunk is stamped from the raw string (task_preparer) at one site and
    # from a {"content": text} wrapper (_prepare_online_data) at another — they must
    # derive the SAME guid so source_data and the disposition key agree.
    assert IDGenerator.derive_source_guid("chunk") == IDGenerator.derive_source_guid(
        {"content": "chunk"}
    )


def test_all_text_projections_agree_across_modes():
    # batch text (enveloped record → stripped), online ingestion wrapper, and the raw
    # string (processing) must all collapse to one identity for the same chunk.
    text = "a chunk of text"
    batch = IDGenerator.derive_source_guid(
        {"content": text, "target_id": "t", "node_id": "n", "batch_uuid": "b_0"}
    )
    online_ingestion = IDGenerator.derive_source_guid({"content": text})
    processing_raw = IDGenerator.derive_source_guid(text)
    assert batch == online_ingestion == processing_raw
