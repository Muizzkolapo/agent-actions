"""A record's own field named `metadata` is the user's data, not framework noise.

`render_card_markdown` unwraps the envelope on purpose, so the human sees the action's
fields — and then classified every key by NAME against a hand-kept list. A user field
called `metadata`, `lineage`, `node_id`, `target_id` or `chunk_info` was filed under
framework metadata. Nothing is lost, but on the HITL screen the field a reviewer most
needs to read could be hidden among framework keys.

The boundary is known at that point and the flattening throws it away: the action's own
fields are exactly `content[action_name]`. So it is passed on rather than re-guessed.
Classifying by name is only right for a caller holding a flat dict with no boundary left,
which is why it stays available rather than being removed.
"""

from agent_actions.record.envelope import RECORD_FRAMEWORK_FIELDS
from agent_actions.tooling.rendering.data_card import (
    IDENTITY_KEYS,
    METADATA_KEYS,
    classify_record,
    render_card_markdown,
)


def _record(action_fields: dict) -> dict:
    return {"source_guid": "g1", "node_id": "n1", "content": {"a1": dict(action_fields)}}


class TestAUserFieldKeepsItsOwnName:
    def test_a_field_called_metadata_is_shown_as_content(self):
        card = render_card_markdown(_record({"metadata": "THE USER'S NOTES"}), action_name="a1")

        assert "THE USER'S NOTES" in card
        assert "_metadata: node_id, metadata" not in card

    def test_every_framework_name_a_user_might_reuse_stays_content(self):
        for name in ("metadata", "lineage", "chunk_info", "target_id", "node_id"):
            card = render_card_markdown(_record({name: "USER VALUE"}), action_name="a1")

            assert "USER VALUE" in card, f"{name} was hidden from the reviewer"

    def test_the_framework_key_of_the_same_name_is_still_framework(self):
        """`node_id` on the envelope is the framework's; only the action's copy is not."""
        card = render_card_markdown(_record({"verdict": "keep"}), action_name="a1")

        assert "_metadata: node_id" in card, card


class TestClassifyRecordStillGuessesWhenItMust:
    def test_without_provenance_the_name_rule_applies(self):
        """A caller holding a flat dict has no boundary left, so the guess is all there is."""
        groups = classify_record({"metadata": "x", "verdict": "keep"})

        assert [k for k, _ in groups["metadata"]] == ["metadata"]

    def test_with_provenance_the_named_keys_win(self):
        groups = classify_record({"metadata": "x", "verdict": "keep"}, content_keys={"metadata"})

        assert [k for k, _ in groups["content"]] == ["metadata", "verdict"]
        assert groups["metadata"] == []


class TestTheCardKnowsEveryFrameworkField:
    """Three hand-kept lists answer one question; nothing pinned this pair before."""

    def test_no_framework_field_would_render_as_business_data(self):
        card_knows = set(METADATA_KEYS) | set(IDENTITY_KEYS)
        # `content` is the envelope itself, unwrapped before classification ever runs.
        unclassified = RECORD_FRAMEWORK_FIELDS - card_knows - {"content"}

        assert unclassified == set(), (
            f"framework fields the card would show a human as content: {sorted(unclassified)}"
        )
