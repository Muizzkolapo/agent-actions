"""A source-pool row carrying no ``content`` envelope is refused, not guessed at.

Each granularity resolves a pool row into the document a prompt sees, and each guesses
when the row has no envelope to separate the user's keys from the framework's. They guess
in opposite directions. Measured on the row below, one row read by both:

* FILE answers ``{"url": "POOL"}`` — ``_extract_content_data`` subtracts
  ``_RECORD_METADATA_KEYS``, sixteen names, five of which an exported or scraped document
  may legitimately carry (``metadata``, ``lineage``, ``chunk_info``, ``node_id``,
  ``target_id``). The user's ``metadata`` and ``lineage`` are gone, with no error and no
  disposition.
* RECORD answers all four keys including ``source_guid`` — the namespace builder subtracts
  nothing, so the framework's identity is offered to the model as a field of the user's
  document.

Neither guess is better, and the boundary is information the row does not carry. #584
faced the same question for identity derivation — ``derive_source_guid`` subtracted
framework field names and collapsed two rows whose user column was called ``node_id`` —
and deleted the subtraction rather than improving it, wrapping the payload under
``content.source`` so there is nothing to subtract. ``SOURCE_GUID_EXCLUDED_FIELDS`` went
with it. The read path keeps the same rule: a row with no envelope is a store this
version cannot read, said out loud, the way ``write_source`` already refuses a row with
no ``source_guid`` rather than dropping it silently.

The refusal belongs at the pool boundary and nowhere else. Both flat branches serve a
second, legitimate population — the namespace builder's takes a bare user payload on the
first-stage prompt path (379 calls across the suite, none of them a record), and
``_extract_content_data``'s is also reached with the record being processed. Only a row
read out of ``source_data`` is promised an envelope.

An enveloped row is untouched, and that is the case a naive fix breaks: #1100 records
that routing the RECORD path through ``_extract_content_data`` was tried and reverted for
exactly this reason. #1130, split from #1100.
"""

import pytest

from agent_actions.errors import DataValidationError
from agent_actions.processing.guard_context import build_guard_context
from agent_actions.processing.source_resolution import resolve_source_content
from agent_actions.prompt.context.scope_application import apply_context_scope_for_records

SCOPE = {"observe": ["source.url"]}

DOCUMENT = {
    "url": "POOL",
    "metadata": {"author": "a. user", "published": "2019-04-01"},
    "lineage": "https://example.com/whitepaper",
}

# A row from a store written before the envelope: the user's own fields sit at the top
# level beside the framework's identity, two of them under names the framework also uses.
FLAT_POOL = [{"source_guid": "G0", **DOCUMENT}]

ENVELOPED_POOL = [{"source_guid": "G0", "content": {"source": dict(DOCUMENT)}}]


def consumer(source_guid="G0"):
    """A later-stage record that resolves to the pool by its own identity.

    It carries no ``source`` namespace of its own, so the pool row is the only document
    either granularity can answer with.
    """
    return {"source_guid": source_guid, "content": {"a1": {"n": 1}}}


def record_mode_source(record, pool, scope=None):
    """The ``source`` namespace a RECORD-granularity action observes."""
    return build_guard_context(
        dict(record),
        agent_name="a2",
        agent_config={"granularity": "record", "context_scope": scope or SCOPE},
        agent_indices={"a1": 0, "a2": 1},
        source_data=pool,
        is_first_stage=False,
    ).get("source")


SKIPPED = "<record skipped>"


def file_mode_source(record, pool, scope=None):
    """The ``source`` namespace a FILE-granularity action observes.

    Returns the ``SKIPPED`` sentinel rather than None when the record was dropped, so a
    parity assertion cannot pass by both sides answering "nothing".
    """
    enriched, _ = apply_context_scope_for_records(
        [dict(record)], scope or SCOPE, action_name="a2", source_data=pool
    )
    if not enriched:
        return SKIPPED
    return enriched[0]["content"].get("source")


class TestNeitherGranularityGuessesAtAFlatPoolRow:
    def test_the_file_path_refuses_it(self):
        """Trunk answers ``{"url": "POOL"}``: the user's ``metadata`` and ``lineage``
        deleted, silently, on the way to the model."""
        with pytest.raises(DataValidationError):
            file_mode_source(consumer(), FLAT_POOL)

    def test_the_record_path_refuses_it(self):
        """Trunk answers the whole row, so ``source_guid`` reaches the model as a field
        of the user's document."""
        with pytest.raises(DataValidationError):
            record_mode_source(consumer(), FLAT_POOL)

    def test_the_resolver_refuses_it_before_a_caller_can_read_content(self):
        """At the resolver boundary too, not only through the two builders: a caller that
        reads ``content`` off the returned row would otherwise see the same guess."""
        with pytest.raises(DataValidationError):
            resolve_source_content(consumer(), "G0", FLAT_POOL, "a2")

    def test_a_row_reached_through_the_carried_parent_identity_is_refused_too(self):
        """The second identity hop resolves rows from the same pool and had the same
        guess behind it."""
        minted = {"source_guid": "MINTED", "parent_source_guid": "G0", "content": {"a1": {"n": 1}}}

        with pytest.raises(DataValidationError):
            record_mode_source(minted, FLAT_POOL)
        with pytest.raises(DataValidationError):
            file_mode_source(minted, FLAT_POOL)

    def test_a_row_whose_content_is_not_a_namespace_dict_is_refused(self):
        """``content`` present but scalar takes the same flat branch, and a row that
        names the key without holding namespaces is no more readable than one that
        omits it."""
        pool = [{"source_guid": "G0", "content": "a plain string", **DOCUMENT}]

        with pytest.raises(DataValidationError):
            file_mode_source(consumer(), pool)

    def test_the_refusal_names_the_row_and_what_is_missing(self):
        """A store-level problem, so the message points at the row's identity and the
        envelope rather than reading as one bad field: every row in such a store is
        shaped this way."""
        with pytest.raises(DataValidationError) as excinfo:
            file_mode_source(consumer(), FLAT_POOL)

        message = str(excinfo.value)
        assert "G0" in message
        assert "content" in message

    def test_a_flat_row_the_pool_never_matches_changes_nothing(self):
        """The refusal fires on the row that is read, not on the pool's mere presence: a
        record resolving to an enveloped row must not fail because some other row in the
        same pool is flat."""
        pool = ENVELOPED_POOL + [{"source_guid": "G9", "url": "NEVER READ"}]

        assert record_mode_source(consumer(), pool) == file_mode_source(consumer(), pool)


class TestTheEnvelopeIsWhatDrawsTheBoundary:
    """An enveloped row's user fields are untouchable whatever they are named — the
    property #584 bought by moving the payload under ``content.source``."""

    def test_a_user_field_named_metadata_survives_on_the_file_path(self):
        assert file_mode_source(consumer(), ENVELOPED_POOL)["metadata"] == DOCUMENT["metadata"]

    def test_a_user_field_named_metadata_survives_on_the_record_path(self):
        assert record_mode_source(consumer(), ENVELOPED_POOL)["metadata"] == DOCUMENT["metadata"]

    def test_a_user_field_named_lineage_survives_on_both_paths(self):
        expected = DOCUMENT["lineage"]

        assert file_mode_source(consumer(), ENVELOPED_POOL)["lineage"] == expected
        assert record_mode_source(consumer(), ENVELOPED_POOL)["lineage"] == expected

    def test_an_enveloped_row_offers_no_framework_key_as_a_document_field(self):
        """The other horn, on the shape that is actually written: the row's own
        ``source_guid`` sits outside ``content`` and must not reach the document."""
        for resolved in (
            file_mode_source(consumer(), ENVELOPED_POOL),
            record_mode_source(consumer(), ENVELOPED_POOL),
        ):
            assert set(resolved) == {"url", "metadata", "lineage"}

    def test_both_granularities_read_the_same_enveloped_document(self):
        assert record_mode_source(consumer(), ENVELOPED_POOL) == file_mode_source(
            consumer(), ENVELOPED_POOL
        )


class TestTheBareDocumentPathIsUntouched:
    """The namespace builder's flat branch is reached 379 times across the suite with a
    bare user payload — the first-stage prompt path hands it the document itself, not a
    record. Refusing there would break every one of those, so the guard sits at the pool
    boundary and this branch keeps working."""

    def test_a_bare_user_payload_is_still_published_as_the_source_namespace(self):
        from agent_actions.prompt.context.scope_builder import SourceNamespaceBuilder

        assert SourceNamespaceBuilder.build(dict(DOCUMENT), "a1") == DOCUMENT

    def test_a_bare_payload_whose_field_is_named_metadata_keeps_it(self):
        from agent_actions.prompt.context.scope_builder import SourceNamespaceBuilder

        built = SourceNamespaceBuilder.build({"text": "t", "metadata": {"k": "v"}}, "a1")

        assert built == {"text": "t", "metadata": {"k": "v"}}
