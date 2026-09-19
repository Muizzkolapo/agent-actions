"""The identity given to a record whose content another staged record already took.

It has to be stable across runs — the disposition and checkpoint gates match on
it, and a batch resume is a different process — and it has to be unreachable by
hashing a record's content, or a record could be handed an identity that already
belongs to someone else's repeat.
"""

import pytest

from agent_actions.utils.id_generation import IDGenerator

BASE = IDGenerator.derive_source_guid({"page_content": "same"})


class TestItIsStable:
    def test_the_same_repeat_derives_the_same_identity(self):
        assert IDGenerator.derive_repeat_source_guid(BASE, 1) == (
            IDGenerator.derive_repeat_source_guid(BASE, 1)
        )

    def test_each_occurrence_gets_its_own(self):
        guids = {IDGenerator.derive_repeat_source_guid(BASE, n) for n in (1, 2, 3)}

        assert len(guids) == 3

    def test_it_is_not_the_identity_it_repeats(self):
        assert IDGenerator.derive_repeat_source_guid(BASE, 1) != BASE

    def test_repeats_of_different_content_do_not_meet(self):
        other = IDGenerator.derive_source_guid({"page_content": "different"})

        assert IDGenerator.derive_repeat_source_guid(BASE, 1) != (
            IDGenerator.derive_repeat_source_guid(other, 1)
        )

    def test_an_occurrence_below_one_is_refused(self):
        """There is no zeroth repeat — the first record of a content keeps its own
        identity, so numbering starts at one."""
        with pytest.raises(ValueError, match="at least 1"):
            IDGenerator.derive_repeat_source_guid(BASE, 0)


class TestNoRecordCanBeGivenOne:
    """Hashed in a different UUID namespace from record content."""

    def test_a_record_shaped_like_the_derivation_does_not_collide(self):
        """The contrived case: a staged record whose fields are literally the
        pair this derives from. In the content namespace it would land on the
        same identity as a repeat."""
        impostor = IDGenerator.derive_source_guid({"repeat_of": BASE, "occurrence": 1})

        assert impostor != IDGenerator.derive_repeat_source_guid(BASE, 1)

    def test_the_derivation_is_not_a_content_hash(self):
        assert IDGenerator.derive_repeat_source_guid(BASE, 1) != (
            IDGenerator.generate_content_hash({"repeat_of": BASE, "occurrence": 1})
        )
