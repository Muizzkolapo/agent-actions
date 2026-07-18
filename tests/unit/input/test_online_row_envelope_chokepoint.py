"""Every online first-stage row branch envelopes + stamps through one authority.

Online tabular/xlsx rows shipped FLAT and UNSTAMPED (data_chunk = loader output), so they
failed loud at write_source and, if merely stamped, re-exposed the get_existing_content
name-strip. Separately, the online JSON branch adopted a user column literally named
``source_guid`` as the framework identity — collapsing distinct rows into one guid (the
reserved-field collision the batch path never had). These pin that all online row branches
wrap the payload under ``content.source`` and derive identity over the RAW payload, identically
to the batch envelope.
"""

from pathlib import Path

# Pre-load the workflow package to break a pre-existing import-order cycle.
import agent_actions.workflow.coordinator  # noqa: F401
from agent_actions.input.preprocessing.staging.initial_pipeline import (
    DataPreparationContext,
    _add_batch_metadata,
    _prepare_online_data,
)
from agent_actions.utils.id_generation import IDGenerator


def _online(content, file_type, file_path):
    ctx = DataPreparationContext(
        content=content,
        file_type=file_type,
        agent_config={},
        file_path=file_path,
        agent_name="a",
    )
    return _prepare_online_data(ctx)


def _write_csv(tmp_path: Path) -> str:
    p = tmp_path / "rows.csv"
    p.write_text("id,body,node_id\n1,hello,USER_A\n2,world,USER_B\n", encoding="utf-8")
    return str(p)


def test_online_csv_row_is_wrapped_and_stamped(tmp_path):
    _dc, st = _online(None, ".csv", _write_csv(tmp_path))
    rec = st[0]
    assert isinstance(rec.get("content"), dict) and set(rec["content"].keys()) == {"source"}
    assert rec["content"]["source"] == {"id": "1", "body": "hello", "node_id": "USER_A"}
    assert rec.get("source_guid"), "online csv row not stamped"
    # identity is derived over the RAW row, not the wrapped record
    assert rec["source_guid"] == IDGenerator.derive_source_guid(
        {"id": "1", "body": "hello", "node_id": "USER_A"}
    )


def test_online_csv_reserved_column_survives_under_source(tmp_path):
    # a user column named node_id must not be stripped by name — it lives inside content.source
    _dc, st = _online(None, ".csv", _write_csv(tmp_path))
    assert (st[0].get("content") or {}).get("source", {}).get("node_id") == "USER_A"


def test_online_xlsx_row_is_wrapped_and_stamped():
    row = {"id": "1", "body": "hello", "node_id": "USER_A"}
    _dc, st = _online([dict(row)], ".xlsx", "/tmp/d.xlsx")
    rec = st[0]
    assert isinstance(rec.get("content"), dict) and rec["content"].get("source") == row
    assert rec.get("source_guid") == IDGenerator.derive_source_guid(row)


def test_online_csv_data_chunk_is_the_wrapped_processor_input(tmp_path):
    # the processor consumes data_chunk (return[0]); pin it IS the wrapped record
    dc, st = _online(None, ".csv", _write_csv(tmp_path))
    assert dc is st
    assert (
        isinstance(dc[0].get("content"), dict)
        and dc[0]["content"].get("source", {}).get("id") == "1"
    )


def test_online_csv_is_deterministic_across_reruns(tmp_path):
    csv_path = _write_csv(tmp_path)
    _a, st_a = _online(None, ".csv", csv_path)
    _b, st_b = _online(None, ".csv", csv_path)
    assert [r.get("source_guid") for r in st_a] == [r.get("source_guid") for r in st_b]
    assert all(r.get("source_guid") for r in st_a)


def test_online_csv_and_batch_produce_identical_envelope(tmp_path):
    # parity: the same string-valued row via online csv and via batch -> identical content + guid
    _dc, st = _online(None, ".csv", _write_csv(tmp_path))
    online = st[0]
    batch = _add_batch_metadata(
        [{"id": "1", "body": "hello", "node_id": "USER_A"}], batch_id="run", node_id="n0"
    )[0]
    assert online["content"] == batch["content"]
    assert online["source_guid"] == batch["source_guid"]


def test_online_json_source_guid_column_does_not_hijack_identity():
    # a user column named source_guid must NOT become the framework identity (reserved-field
    # collision); two distinct rows sharing that value must still get distinct derived guids.
    rows = [{"source_guid": "collide", "a": "1"}, {"source_guid": "collide", "a": "2"}]
    _dc, st = _online([dict(r) for r in rows], ".json", "/tmp/d.json")
    assert st[0].get("source_guid") != st[1].get("source_guid"), (
        "a user source_guid column hijacked the framework identity"
    )
    assert st[0].get("source_guid") == IDGenerator.derive_source_guid(
        {"source_guid": "collide", "a": "1"}
    )
    # the user's column is still preserved under content.source
    assert (st[0].get("content") or {}).get("source", {}).get("source_guid") == "collide"
