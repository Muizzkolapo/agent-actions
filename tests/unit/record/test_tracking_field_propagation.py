"""Tests for tracking field propagation through RecordEnvelope and enrichment pipeline."""

from agent_actions.record.envelope import (
    RECORD_FRAMEWORK_FIELDS,
    RECORD_LIFECYCLE_FIELDS,
    RECORD_STAGE_FIELDS,
    RECORD_TRACKING_FIELDS,
    RecordEnvelope,
)


class TestFieldSets:
    def test_tracking_fields_are_subset_of_framework(self):
        assert RECORD_TRACKING_FIELDS < RECORD_FRAMEWORK_FIELDS

    def test_lifecycle_fields_are_subset_of_framework(self):
        assert RECORD_LIFECYCLE_FIELDS < RECORD_FRAMEWORK_FIELDS

    def test_stage_fields_are_subset_of_framework(self):
        assert RECORD_STAGE_FIELDS < RECORD_FRAMEWORK_FIELDS

    def test_framework_is_union(self):
        assert RECORD_FRAMEWORK_FIELDS == (
            RECORD_TRACKING_FIELDS | RECORD_LIFECYCLE_FIELDS | RECORD_STAGE_FIELDS
        )

    def test_tracking_and_lifecycle_are_disjoint(self):
        assert RECORD_TRACKING_FIELDS.isdisjoint(RECORD_LIFECYCLE_FIELDS)

    def test_tracking_and_stage_are_disjoint(self):
        assert RECORD_TRACKING_FIELDS.isdisjoint(RECORD_STAGE_FIELDS)

    def test_lifecycle_and_stage_are_disjoint(self):
        assert RECORD_LIFECYCLE_FIELDS.isdisjoint(RECORD_STAGE_FIELDS)

    def test_tracking_contains_source_guid(self):
        assert "source_guid" in RECORD_TRACKING_FIELDS

    def test_tracking_contains_version_correlation_id(self):
        assert "version_correlation_id" in RECORD_TRACKING_FIELDS

    def test_metadata_not_in_tracking(self):
        # metadata is a per-stage field — must not bleed into tracking carry
        assert "metadata" not in RECORD_TRACKING_FIELDS

    def test_target_id_not_in_tracking(self):
        assert "target_id" not in RECORD_TRACKING_FIELDS

    def test_producer_source_guids_is_a_stage_field(self):
        """It names which input of *this* action produced the row. Carried forward
        it would name, at the next action, a record that action never received —
        the degradation that already makes parent_source_guid unusable as one."""
        assert "producer_source_guids" in RECORD_STAGE_FIELDS
        assert "producer_source_guids" not in RECORD_TRACKING_FIELDS


class TestEnvelopeBuildCarriesTrackingFields:
    def test_carries_version_correlation_id(self):
        inp = {
            "source_guid": "g1",
            "version_correlation_id": "vcid-abc",
            "content": {},
        }
        result = RecordEnvelope.build("act", {"x": 1}, inp)
        assert result["version_correlation_id"] == "vcid-abc"

    def test_carries_source_guid(self):
        inp = {"source_guid": "g1", "content": {}}
        result = RecordEnvelope.build("act", {"x": 1}, inp)
        assert result["source_guid"] == "g1"

    def test_does_not_carry_metadata(self):
        inp = {"source_guid": "g1", "metadata": {"model": "gpt-4"}, "content": {}}
        result = RecordEnvelope.build("act", {"x": 1}, inp)
        assert "metadata" not in result

    def test_does_not_carry_target_id(self):
        inp = {"source_guid": "g1", "target_id": "t1", "content": {}}
        result = RecordEnvelope.build("act", {"x": 1}, inp)
        assert "target_id" not in result

    def test_does_not_carry_producer_source_guids(self):
        inp = {"source_guid": "g1", "producer_source_guids": ["r0"], "content": {}}
        result = RecordEnvelope.build("act", {"x": 1}, inp)
        assert "producer_source_guids" not in result

    def test_does_not_carry_lineage(self):
        inp = {"source_guid": "g1", "lineage": ["n1", "n2"], "content": {}}
        result = RecordEnvelope.build("act", {"x": 1}, inp)
        assert "lineage" not in result

    def test_no_input_record_no_tracking_fields(self):
        result = RecordEnvelope.build("act", {"x": 1})
        assert "source_guid" not in result
        assert "version_correlation_id" not in result

    def test_tracking_fields_chain_through_stages(self):
        """version_correlation_id must survive 3 sequential build() calls."""
        r1 = RecordEnvelope.build(
            "source",
            {"raw": "data"},
            {"source_guid": "g1", "version_correlation_id": "vcid-xyz", "content": {}},
        )
        r2 = RecordEnvelope.build("summarize", {"summary": "short"}, r1)
        r3 = RecordEnvelope.build("review", {"score": 9}, r2)

        assert r3["version_correlation_id"] == "vcid-xyz"
        assert r3["source_guid"] == "g1"


class TestEnvelopeBuildCarriesLifecycleFields:
    def test_carries_state_history(self):
        history = [
            {
                "timestamp": "t",
                "action": "a",
                "from": None,
                "to": "active",
                "reason": "r",
                "detail": None,
            }
        ]
        inp = {"source_guid": "g1", "_state_history": history, "content": {}}
        result = RecordEnvelope.build("act", {"x": 1}, inp)
        assert result["_state_history"] == history

    def test_carries_state_schema_version(self):
        inp = {"source_guid": "g1", "_state_schema_version": 1, "content": {}}
        result = RecordEnvelope.build("act", {"x": 1}, inp)
        assert result["_state_schema_version"] == 1

    def test_build_skipped_carries_state_history(self):
        history = [
            {
                "timestamp": "t",
                "action": "a",
                "from": None,
                "to": "active",
                "reason": "r",
                "detail": None,
            }
        ]
        inp = {"source_guid": "g1", "_state_history": history, "content": {"prior": {"x": 1}}}
        result = RecordEnvelope.build_skipped("skipped_action", inp)
        assert result["_state_history"] == history

    def test_does_not_carry_state(self):
        """_state is a per-stage field — must not be carried by build()."""
        inp = {"source_guid": "g1", "_state": "processed", "content": {}}
        result = RecordEnvelope.build("act", {"x": 1}, inp)
        assert "_state" not in result

    def test_carried_history_is_isolated_copy(self):
        """Mutating output history must not corrupt input record."""
        history = [
            {
                "timestamp": "t",
                "action": "a",
                "from": None,
                "to": "active",
                "reason": "r",
                "detail": None,
            }
        ]
        inp = {"source_guid": "g1", "_state_history": history, "content": {}}
        result = RecordEnvelope.build("act", {"x": 1}, inp)
        result["_state_history"].append({"extra": True})
        assert len(inp["_state_history"]) == 1  # input unchanged

    def test_build_skipped_history_is_isolated_copy(self):
        """Mutating skipped output history must not corrupt input record."""
        history = [
            {
                "timestamp": "t",
                "action": "a",
                "from": None,
                "to": "active",
                "reason": "r",
                "detail": None,
            }
        ]
        inp = {"source_guid": "g1", "_state_history": history, "content": {"prior": {"x": 1}}}
        result = RecordEnvelope.build_skipped("skipped_action", inp)
        result["_state_history"].append({"extra": True})
        assert len(inp["_state_history"]) == 1

    def test_cumulative_growth_across_build_transition_build(self):
        """History must grow across build → transition → build chain."""
        from agent_actions.record.state import RecordState

        r1 = RecordEnvelope.build("stage1", {"a": 1}, {"source_guid": "g1", "content": {}})
        RecordEnvelope.transition(r1, RecordState.PROCESSED, "stage1", "done")
        assert len(r1["_state_history"]) == 1

        RecordEnvelope.transition(r1, RecordState.ACTIVE, "reset", "downstream_reset")
        r2 = RecordEnvelope.build("stage2", {"b": 2}, r1)
        RecordEnvelope.transition(r2, RecordState.PROCESSED, "stage2", "done")
        assert len(r2["_state_history"]) == 3  # stage1 + reset + stage2

    def test_build_skipped_carries_state_schema_version(self):
        inp = {"source_guid": "g1", "_state_schema_version": 1, "content": {"prior": {"x": 1}}}
        result = RecordEnvelope.build_skipped("skipped_action", inp)
        assert result["_state_schema_version"] == 1

    def test_empty_history_list_carried(self):
        inp = {"source_guid": "g1", "_state_history": [], "content": {}}
        result = RecordEnvelope.build("act", {"x": 1}, inp)
        assert result["_state_history"] == []


class TestBuildSkippedCarriesTrackingFields:
    def test_carries_version_correlation_id(self):
        inp = {
            "source_guid": "g1",
            "version_correlation_id": "vcid-abc",
            "content": {"prior": {"x": 1}},
        }
        result = RecordEnvelope.build_skipped("skipped_action", inp)
        assert result["version_correlation_id"] == "vcid-abc"

    def test_does_not_carry_metadata(self):
        inp = {
            "source_guid": "g1",
            "metadata": {"model": "gpt-4"},
            "content": {},
        }
        result = RecordEnvelope.build_skipped("skipped_action", inp)
        assert "metadata" not in result


class TestTheProducerIsNotOfferedAsBusinessData:
    """It is a framework identity, like every other *_source_guid. Two hand-kept lists
    decide whether such a field reaches a prompt or a reviewer's screen, and neither is
    derived from the field sets — a new identity field has to be added to both."""

    def test_it_is_not_offered_to_a_prompt_as_record_content(self):
        from agent_actions.prompt.context.scope_namespace import _RECORD_METADATA_KEYS

        assert "producer_source_guids" in _RECORD_METADATA_KEYS

    def test_a_record_carrying_it_does_not_put_it_in_prompt_content(self):
        """The behaviour the list gates: without it the field is sent to the model
        beside the business fields."""
        from agent_actions.prompt.context.scope_namespace import _extract_content_data

        content = _extract_content_data(
            {
                "source_guid": "minted",
                "parent_source_guid": "s0",
                "producer_source_guids": ["r0"],
                "question": "what is 2+2?",
            }
        )

        assert content == {"question": "what is 2+2?"}

    def test_every_identity_field_the_prompt_list_excludes_is_also_a_card_field(self):
        """Two hand-kept lists, one purpose: a framework identity is not business data.
        Whatever the prompt list excludes, the card must classify as metadata too, or
        the same field is hidden from the model and shown to a human reviewer."""
        from agent_actions.prompt.context.scope_namespace import _RECORD_METADATA_KEYS
        from agent_actions.tooling.rendering.data_card import METADATA_KEYS

        assert sorted(_RECORD_METADATA_KEYS - METADATA_KEYS) == []

    def test_a_parent_identity_is_classified_as_metadata_not_content(self):
        from agent_actions.tooling.rendering.data_card import classify_field

        assert classify_field("parent_source_guid") == "metadata"

    def test_a_repeat_identity_is_classified_as_metadata_not_content(self):
        from agent_actions.tooling.rendering.data_card import classify_field

        assert classify_field("repeat_of_source_guid") == "metadata"

    def test_it_is_not_rendered_as_a_data_card_field(self):
        """data_card.METADATA_KEYS calls itself the single source of truth, mirrored in
        the frontend and the HITL approval template; an unlisted key renders as business
        data in the reviewer UI."""
        from agent_actions.tooling.rendering.data_card import METADATA_KEYS

        assert "producer_source_guids" in METADATA_KEYS
