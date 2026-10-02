"""The card's metadata list must hold every envelope field the framework defines.

`METADATA_KEYS` has two readers: this module's own classifier, and the HITL approval
screen -- `hitl/server.py` serialises it into `approval.html`, which filters it out of
what a human reviewer is shown. A framework field missing from the list renders to that
reviewer as business data.

Three hand-kept lists answer one question (`METADATA_KEYS`, `IDENTITY_KEYS`,
`RECORD_FRAMEWORK_FIELDS`) and nothing pinned them against each other, which is how
`_delta_mode` and `version_correlation_id` came to be absent from the card's list while
the framework counted them as envelope fields.
"""

from agent_actions.record.envelope import RECORD_FRAMEWORK_FIELDS
from agent_actions.tooling.rendering.data_card import (
    IDENTITY_KEYS,
    METADATA_KEYS,
    classify_field,
)


class TestTheCardKnowsEveryFrameworkField:
    def test_no_framework_field_would_render_as_business_data(self):
        card_knows = set(METADATA_KEYS) | set(IDENTITY_KEYS)
        # `content` is the payload the other fields wrap, not metadata about it.
        unclassified = RECORD_FRAMEWORK_FIELDS - card_knows - {"content"}

        assert unclassified == set(), (
            f"framework fields the card would show a human as content: {sorted(unclassified)}"
        )

    def test_the_two_fields_that_were_missing_classify_as_metadata(self):
        """Named explicitly, so the pair stays covered if RECORD_FRAMEWORK_FIELDS changes."""
        assert classify_field("_delta_mode") == "metadata"
        assert classify_field("version_correlation_id") == "metadata"

    def test_a_user_field_is_still_content(self):
        """The guard must not have been satisfied by classifying everything as metadata."""
        assert classify_field("verdict") == "content"
        assert classify_field("some_user_field") == "content"
