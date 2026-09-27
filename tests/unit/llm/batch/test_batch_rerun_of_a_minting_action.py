"""A batch re-run of an action that mints an identity for each output row.

Every such identity is freshly generated, so matching the run's own output
against the stored rows by identity finds nothing in common and hands back each
stale row beside its own replacement. Driven through a real ``SQLiteBackend``,
which is where the rows and the fields that attribute them round-trip.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from agent_actions.config.types import RunMode
from agent_actions.llm.batch.services.processing import BatchProcessingService
from agent_actions.processing.enrichment import EnrichmentPipeline
from agent_actions.processing.types import ProcessingContext, ProcessingResult, ProcessingStatus
from agent_actions.processing.unified import UnifiedProcessor
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend

ACTION = "expand_page"
RELATIVE = "page.json"


def _row(guid: str, *, producers: list[str] | None = None) -> dict[str, Any]:
    """An output row as the action writes it, minted when it names its producers."""
    row: dict[str, Any] = {
        "source_guid": guid,
        "answer": f"answer-for-{guid}",
        "_delta_mode": "full",
        "_state": "processed",
    }
    if producers is not None:
        row["producer_source_guids"] = producers
    return row


def _failed(input_guid: str) -> dict[str, Any]:
    """A failed record's row: keyed on the input, unenriched, naming no producer."""
    return {
        "source_guid": input_guid,
        "error": "provider overloaded",
        "metadata": {},
        "_state": "failed",
    }


def _rerun(tmp_path: Path, stored: list[dict], produced: list[dict]) -> list[dict]:
    """Store *stored* as the previous run's output, then merge *produced* over it."""
    backend = SQLiteBackend(str(tmp_path / "store.db"), workflow_name="w")
    backend.initialize()
    backend._write_target_raw(ACTION, RELATIVE, stored)
    backend._reconstruction_cache.clear()

    service = BatchProcessingService(
        client_resolver=MagicMock(),
        context_manager=MagicMock(),
        result_processor=MagicMock(),
        registry_manager_factory=MagicMock(),
        workflow_name=ACTION,
        storage_backend=backend,
    )
    return service._merge_carry_forward(ACTION, list(produced), RELATIVE)


class TestMintedIdentitiesAreNotCarriedBesideTheirReplacements:
    def test_a_full_rerun_replaces_the_rows_it_regenerated(self, tmp_path):
        """Two inputs expanded into three rows stay three rows on a re-run."""
        stored = [
            _row("m1", producers=["i1"]),
            _row("m2", producers=["i1"]),
            _row("m3", producers=["i2"]),
        ]
        produced = [
            _row("n1", producers=["i1"]),
            _row("n2", producers=["i1"]),
            _row("n3", producers=["i2"]),
        ]

        result = _rerun(tmp_path, stored, produced)

        assert [r["source_guid"] for r in result] == ["n1", "n2", "n3"], (
            f"the previous run's rows were carried beside their replacements: {result}"
        )

    def test_a_narrowed_batch_carries_only_the_inputs_it_did_not_answer(self, tmp_path):
        """One of two inputs re-run: its stale rows go, the other input's stay."""
        stored = [
            _row("m1", producers=["i1"]),
            _row("m2", producers=["i1"]),
            _row("m3", producers=["i2"]),
        ]
        produced = [_row("n3", producers=["i2"])]

        result = _rerun(tmp_path, stored, produced)

        assert [r["source_guid"] for r in result] == ["n3", "m1", "m2"], (
            f"i2's stale row was carried beside its replacement: {result}"
        )

    def test_a_row_the_run_did_not_answer_for_keeps_its_data(self, tmp_path):
        """A carried row arrives whole, not as an identity."""
        stored = [_row("m1", producers=["i1"]), _row("m2", producers=["i2"])]
        produced = [_row("n2", producers=["i2"])]

        result = _rerun(tmp_path, stored, produced)

        carried = [r for r in result if r["source_guid"] == "m1"]
        assert len(carried) == 1
        assert carried[0]["answer"] == "answer-for-m1"

    def test_a_minted_row_whose_input_is_gone_is_still_carried(self, tmp_path):
        """An input no longer in the run holds rows nobody will write again."""
        stored = [_row("m1", producers=["i1"]), _row("m2", producers=["i_removed"])]
        produced = [_row("n1", producers=["i1"])]

        result = _rerun(tmp_path, stored, produced)

        assert [r["source_guid"] for r in result] == ["n1", "m2"]


class TestAnInputWhoseRowCountChangesBetweenRuns:
    """How many rows an input yields is decided per run, from what the provider
    returned, so the same input can mint several rows one run and keep its own
    identity the next. Both directions replace what was stored.
    """

    def test_an_input_falling_to_one_row_replaces_the_rows_it_minted(self, tmp_path):
        stored = [
            _row("m1", producers=["i1"]),
            _row("m2", producers=["i1"]),
            _row("m3", producers=["i1"]),
        ]
        produced = [_row("i1")]

        result = _rerun(tmp_path, stored, produced)

        assert [r["source_guid"] for r in result] == ["i1"], (
            f"the three rows i1 minted last run were carried beside its one row now: {result}"
        )

    def test_an_input_rising_to_several_rows_replaces_the_row_it_kept(self, tmp_path):
        stored = [_row("i1")]
        produced = [_row("n1", producers=["i1"]), _row("n2", producers=["i1"])]

        result = _rerun(tmp_path, stored, produced)

        assert [r["source_guid"] for r in result] == ["n1", "n2"], (
            f"the row i1 kept last run was carried beside the rows it minted now: {result}"
        )


class TestAFailureDoesNotDeleteTheAnswersItCouldNotReplace:
    """A failed record's row is keyed on the input itself and minted from nothing.

    It stands for no produced row, so a minting action's stored answers have to
    outlive it — a run the provider refused must not empty the file.
    """

    def test_a_provider_error_leaves_the_previous_answers_in_place(self, tmp_path):
        stored = [_row("m1", producers=["i1"]), _row("m2", producers=["i1"])]
        produced = [_failed("i1")]

        result = _rerun(tmp_path, stored, produced)

        assert [r["source_guid"] for r in result] == ["i1", "m1", "m2"]
        assert [r.get("answer") for r in result[1:]] == ["answer-for-m1", "answer-for-m2"]

    def test_a_run_answering_one_input_and_failing_another_keeps_both(self, tmp_path):
        stored = [
            _row("m1", producers=["i1"]),
            _row("m2", producers=["i1"]),
            _row("m3", producers=["i2"]),
        ]
        produced = [_row("n1", producers=["i1"]), _row("n2", producers=["i1"]), _failed("i2")]

        result = _rerun(tmp_path, stored, produced)

        assert [r["source_guid"] for r in result] == ["n1", "n2", "i2", "m3"]

    def test_an_identity_carrying_action_still_replaces_the_row_that_failed(self, tmp_path):
        """The failed row does carry this input's identity, so it does replace it."""
        stored = [_row("r1"), _row("r2")]
        produced = [_failed("r1")]

        result = _rerun(tmp_path, stored, produced)

        assert [r["source_guid"] for r in result] == ["r1", "r2"]
        assert result[0].get("error"), "r1 is the stored answer, not the row that failed"
        assert "answer" not in result[0], "the stored answer was carried as well as replaced"

    @pytest.mark.parametrize("state", ["failed", "exhausted", "cascade_skipped"])
    def test_a_row_that_named_its_input_but_did_not_settle_answers_for_nothing(
        self, tmp_path, state
    ):
        """Naming an input is not answering for it.

        A row can be stamped unsettled after enrichment named its producers, so the
        name survives on a row holding nothing. Read as an answer it deletes the
        answers the last run did produce.
        """
        stored = [_row("m1", producers=["i1"]), _row("m2", producers=["i1"])]
        produced = [{"source_guid": "n1", "producer_source_guids": ["i1"], "_state": state}]

        result = _rerun(tmp_path, stored, produced)

        assert [r["source_guid"] for r in result] == ["n1", "m1", "m2"], (
            f"a row stamped {state} deleted the answers it did not replace: {result}"
        )

    def test_an_exhausted_row_replaces_nothing_it_was_minted_beside(self, tmp_path):
        """Exhaustion holds no answer either, on the same reading as a failure."""
        stored = [_row("m1", producers=["i1"]), _row("m2", producers=["i1"])]
        produced = [{"source_guid": "i1", "_state": "exhausted", "content": {}}]

        result = _rerun(tmp_path, stored, produced)

        assert [r["source_guid"] for r in result] == ["i1", "m1", "m2"]


class TestIdentityCarryingActionsAreUnchanged:
    """An action whose rows keep their input's identity: the existing rule already
    matched these, and it has to keep matching them."""

    def test_a_full_rerun_replaces_every_row(self, tmp_path):
        stored = [_row("r1"), _row("r2"), _row("r3")]
        produced = [_row("r1"), _row("r2"), _row("r3")]

        result = _rerun(tmp_path, stored, produced)

        assert [r["source_guid"] for r in result] == ["r1", "r2", "r3"]

    def test_a_narrowed_rerun_carries_the_rest(self, tmp_path):
        stored = [_row("r1"), _row("r2"), _row("r3")]
        produced = [_row("r3")]

        result = _rerun(tmp_path, stored, produced)

        assert [r["source_guid"] for r in result] == ["r3", "r1", "r2"]

    def test_the_only_row_is_replaced_not_duplicated(self, tmp_path):
        result = _rerun(tmp_path, [_row("r1")], [_row("r1")])

        assert [r["source_guid"] for r in result] == ["r1"]


class TestPartlyReproducedRowsAreNotDropped:
    def test_a_row_merging_two_inputs_survives_a_run_answering_one(self, tmp_path):
        """Half an answer replacing a whole one is a loss, so the row is handed back.

        A duplicate is visible in the output; a row that silently stopped existing
        is not. Which of the two ought to survive is not decided here.
        """
        stored = [_row("m1", producers=["i1", "i2"])]
        produced = [_row("n1", producers=["i1"])]

        result = _rerun(tmp_path, stored, produced)

        assert [r["source_guid"] for r in result] == ["n1", "m1"]
        assert result[1]["answer"] == "answer-for-m1", "i2's half of the row was dropped"


class TestOnlyASettledAnswerCounts:
    """`processed` is the whole test, not "has settled".

    Several states are terminal and say the action yielded nothing for that input.
    Reading any of them as an answer deletes what the previous run produced, so the
    rule asks the narrower question.
    """

    def test_a_guard_skipped_row_does_not_delete_what_it_skipped_past(self, tmp_path):
        """A record the guard skipped comes back keyed on its input, holding no answer.

        Its state is terminal and its disposition a passthrough, so widening the test
        to "has settled" reads it as an answer and drops the stored rows — which is
        why the test is for `processed` and not for settledness.
        """
        stored = [_row("m1", producers=["i1"]), _row("m2", producers=["i1"])]
        produced = [{"source_guid": "i1", "_state": "guard_skipped", "content": {}}]

        result = _rerun(tmp_path, stored, produced)

        assert [r["source_guid"] for r in result] == ["i1", "m1", "m2"], (
            f"a guard skip deleted the answers it did not replace: {result}"
        )

    def test_a_row_naming_several_inputs_is_never_inferred_away(self, tmp_path):
        """Naming one input is the shape a mint makes; naming several is not.

        Such a row also holds what its other inputs gave it, and the identity it
        carries is then an input's rather than a mint's — which no field distinguishes.
        So it is handed back even where every input it names was answered for, and the
        cost is a duplicate rather than a row that stopped existing.
        """
        stored = [_row("m1", producers=["i1", "i2"])]
        produced = [_row("n1", producers=["i1", "i2"])]

        result = _rerun(tmp_path, stored, produced)

        assert [r["source_guid"] for r in result] == ["n1", "m1"]
        assert result[1]["answer"] == "answer-for-m1"


class TestACarriedRowNeverSharesAnIdentityWithAProducedOne:
    """The rule the subtraction it replaced held for free.

    Carried rows are appended to the run's own output, so an identity in both lists
    is written twice. Subtracting one set of identities from the other could not
    produce that; matching on inputs can, wherever a stored row names producers and
    the run rewrote a row under that stored row's own identity.
    """

    def test_a_stored_row_the_run_rewrote_in_place_is_not_also_carried(self, tmp_path):
        stored = [_row("i1", producers=["i2"])]
        produced = [_failed("i1")]

        result = _rerun(tmp_path, stored, produced)

        guids = [r["source_guid"] for r in result]
        assert len(guids) == len(set(guids)), f"one identity written twice: {guids}"


class TestTheAccumulationDoesNotResumeAcrossPasses:
    """The defect grew the file by its previous contents on *every* pass.

    One merge proves nothing about the second: the carried rows are re-stored on the
    way out, and the rule reads fields that have to survive that round trip.
    """

    def test_three_consecutive_rerans_stay_at_three_rows(self, tmp_path):
        backend = SQLiteBackend(str(tmp_path / "store.db"), workflow_name="w")
        backend.initialize()
        service = BatchProcessingService(
            client_resolver=MagicMock(),
            context_manager=MagicMock(),
            result_processor=MagicMock(),
            registry_manager_factory=MagicMock(),
            workflow_name=ACTION,
            storage_backend=backend,
        )

        counts = []
        for run in ("a", "b", "c"):
            produced = [
                _row(f"{run}1", producers=["i1"]),
                _row(f"{run}2", producers=["i1"]),
                _row(f"{run}3", producers=["i2"]),
            ]
            merged = service._merge_carry_forward(ACTION, list(produced), RELATIVE)
            backend.write_target(ACTION, RELATIVE, merged)
            backend._reconstruction_cache.clear()
            counts.append(len(merged))

        assert counts == [3, 3, 3], f"the file grew across passes: {counts}"

    def test_a_carried_row_is_still_replaced_by_the_pass_after_it(self, tmp_path):
        """A row carried once is re-stored; the next run that answers for its input
        must still replace it, which only holds if it kept what attributes it."""
        backend = SQLiteBackend(str(tmp_path / "store.db"), workflow_name="w")
        backend.initialize()
        service = BatchProcessingService(
            client_resolver=MagicMock(),
            context_manager=MagicMock(),
            result_processor=MagicMock(),
            registry_manager_factory=MagicMock(),
            workflow_name=ACTION,
            storage_backend=backend,
        )

        backend.write_target(
            ACTION,
            RELATIVE,
            [_row("a1", producers=["i1"]), _row("a2", producers=["i2"])],
        )
        backend._reconstruction_cache.clear()

        # A narrowed run: i1's row is replaced, i2's is carried and re-stored.
        narrowed = service._merge_carry_forward(ACTION, [_row("b1", producers=["i1"])], RELATIVE)
        assert [r["source_guid"] for r in narrowed] == ["b1", "a2"]
        backend.write_target(ACTION, RELATIVE, narrowed)
        backend._reconstruction_cache.clear()

        full = service._merge_carry_forward(
            ACTION, [_row("c1", producers=["i1"]), _row("c2", producers=["i2"])], RELATIVE
        )

        assert [r["source_guid"] for r in full] == ["c1", "c2"], (
            f"the carried row survived a pass that answered for its input: {full}"
        )


class TestTheRowShapesTheseTestsRelyOn:
    """The fixtures above stand or fall on enrichment writing these fields."""

    def test_a_batch_expansion_mints_an_identity_and_names_its_input(self):
        context = ProcessingContext(
            agent_config={"kind": "llm"}, agent_name=ACTION, mode=RunMode.BATCH
        )
        context.source_data = [{"source_guid": "i1", "page_content": "text"}]

        # The strategy stamps the input's guid on every item before enrichment sees
        # it, so handing items without one never exercises the re-mint decision.
        result = ProcessingResult(
            status=ProcessingStatus.SUCCESS,
            data=[{"source_guid": "i1", "answer": "a"}, {"source_guid": "i1", "answer": "b"}],
            source_guid="i1",
        )
        result.is_expansion = True

        rows = EnrichmentPipeline().enrich(result, context).data

        assert [r.get("producer_source_guids") for r in rows] == [["i1"], ["i1"]]
        minted = [r["source_guid"] for r in rows]
        assert "i1" not in minted, "the input's identity was reused for a minted row"
        assert len(set(minted)) == 2, "expansion children share an identity"

    def test_collection_settles_a_minted_row_and_leaves_its_input_named(self):
        """Both fields the rule reads, off the path batch retrieval actually runs.

        Enrichment names the input, collection settles the state, and the rule needs
        both on the same row: with either missing the stale rows are carried again.
        """
        context = ProcessingContext(
            agent_config={"kind": "llm"}, agent_name=ACTION, mode=RunMode.BATCH
        )
        context.source_data = [{"source_guid": "i1", "page_content": "text"}]

        result = ProcessingResult(
            status=ProcessingStatus.SUCCESS,
            data=[{"source_guid": "i1", "answer": "a"}, {"source_guid": "i1", "answer": "b"}],
            source_guid="i1",
        )
        result.is_expansion = True

        rows, _stats = UnifiedProcessor(
            enrichment_pipeline=EnrichmentPipeline()
        ).enrich_and_collect([result], context)

        assert [r.get("producer_source_guids") for r in rows] == [["i1"], ["i1"]]
        assert [r.get("_state") for r in rows] == ["processed", "processed"]

    def test_the_fields_survive_a_store_round_trip(self, tmp_path):
        backend = SQLiteBackend(str(tmp_path / "store.db"), workflow_name="w")
        backend.initialize()
        backend._write_target_raw(ACTION, RELATIVE, [_row("m1", producers=["i1"])])
        backend._reconstruction_cache.clear()

        rows = backend.read_target_for_rewrite(ACTION, RELATIVE)

        assert [r.get("producer_source_guids") for r in rows] == [["i1"]]

    def test_the_write_production_uses_keeps_what_attributes_a_row(self, tmp_path):
        """The one silent-revert path: a minted row goes in through the schema-echo
        gate, and dropping what attributes it there turns every re-run back into the
        doubling this suite pins, with every other test still green."""
        backend = SQLiteBackend(str(tmp_path / "store.db"), workflow_name="w")
        backend.initialize()

        backend.write_target(
            ACTION, RELATIVE, [_row("m1", producers=["i1"]), _row("m2", producers=["i1"])]
        )
        backend._reconstruction_cache.clear()
        rows = backend.read_target_for_rewrite(ACTION, RELATIVE)

        assert [r.get("producer_source_guids") for r in rows] == [["i1"], ["i1"]]
