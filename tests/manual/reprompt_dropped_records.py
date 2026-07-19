"""Reproduce: reprompt batch silently drops records when provider returns fewer.

Simulates validate_and_reprompt() with 10 records where 5 fail validation.
The mock provider returns only 3 of the 5 resubmitted records (dropped 2).
Before the fix, the 2 dropped records vanish from the final output entirely.
After the fix, they appear with recovery metadata (passed=False).
"""

from unittest.mock import MagicMock, patch

from agent_actions.llm.providers.batch_base import BatchResult

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

NUM_RECORDS = 10
FAIL_IDS = {"rec_003", "rec_005", "rec_006", "rec_008", "rec_009"}
DROPPED_IDS = {"rec_006", "rec_009"}  # Provider will not return these
RETURNED_IDS = FAIL_IDS - DROPPED_IDS  # rec_003, rec_005, rec_008


def make_results():
    return [
        BatchResult(
            custom_id=f"rec_{i:03d}",
            content='{"answer": "bad"}'
            if f"rec_{i:03d}" in FAIL_IDS
            else f'{{"answer": "ok_{i}"}}',
            success=True,
        )
        for i in range(NUM_RECORDS)
    ]


def make_context_map():
    return {
        f"rec_{i:03d}": {
            "content": {"question": f"q_{i}"},
            "user_content": f"original prompt {i}",
            "target_id": f"rec_{i:03d}",
        }
        for i in range(NUM_RECORDS)
    }


def validation_func(content):
    """Reject records whose content contains 'bad'."""
    return "bad" not in str(content)


# ---------------------------------------------------------------------------
# Reproduce
# ---------------------------------------------------------------------------


def run():
    from agent_actions.llm.batch.services.reprompt_ops import validate_and_reprompt

    results = make_results()
    context_map = make_context_map()
    all_input_ids = {r.custom_id for r in results}

    # Provider returns only RETURNED_IDS (drops DROPPED_IDS)
    provider = MagicMock()
    provider.submit_batch.return_value = ("batch_rp_1", "submitted")
    provider.retrieve_results.return_value = [
        BatchResult(custom_id=cid, content='{"answer": "fixed"}', success=True)
        for cid in RETURNED_IDS
    ]

    mock_parse = MagicMock()
    mock_parse.return_value = MagicMock(
        validation_name="check_it",
        max_attempts=2,
        on_exhausted="return_last",
    )

    with (
        patch(
            "agent_actions.processing.recovery.reprompt.parse_reprompt_config",
            mock_parse,
        ),
        patch(
            "agent_actions.processing.recovery.validation.get_validation_function",
            return_value=(validation_func, "fix it"),
        ),
        patch(
            "agent_actions.processing.recovery.response_validator.build_validation_feedback",
            return_value="Please fix",
        ),
        patch(
            "agent_actions.processing.recovery.response_validator.resolve_feedback_strategies",
            return_value=[],
        ),
        patch(
            "agent_actions.llm.batch.services.reprompt_ops._load_source_data_for_reprompt",
            return_value=None,
        ),
        patch(
            "agent_actions.llm.batch.services.reprompt_ops.wait_for_batch_completion",
            return_value="completed",
        ),
        patch(
            "agent_actions.llm.batch.services.reprompt_ops.BatchStatus",
        ) as MockBatchStatus,
        patch("agent_actions.llm.batch.processing.preparator.BatchTaskPreparator") as MockPrep,
    ):
        MockBatchStatus.COMPLETED = "completed"
        mock_prep = MockPrep.return_value
        mock_prepared = MagicMock()
        mock_prepared.tasks = [MagicMock() for _ in range(len(FAIL_IDS))]
        mock_prep.prepare_tasks.return_value = mock_prepared

        final = validate_and_reprompt(
            action_indices={},
            dependency_configs={},
            storage_backend=None,
            results=results,
            provider=provider,
            context_map=context_map,
            output_directory="/tmp/out",
            file_name="batch_1",
            agent_config={"reprompt": {"validation": "check_it", "max_attempts": 2}},
        )

    final_ids = {r.custom_id for r in final}
    missing = all_input_ids - final_ids

    print(f"Input records:    {len(all_input_ids)} — {sorted(all_input_ids)}")
    print(f"Output records:   {len(final_ids)} — {sorted(final_ids)}")
    print(f"Missing records:  {len(missing)} — {sorted(missing)}")
    print()

    if missing:
        print("BUG CONFIRMED: records silently dropped by reprompt batch")
        print(f"  Dropped IDs: {sorted(missing)}")
        print(f"  Expected dropped: {sorted(DROPPED_IDS)}")

        # Compare with retry path (which does reconcile)
        print()
        print("The retry path uses BatchResultReconciler to detect missing records")
        print("and builds exhausted recovery metadata. The reprompt path has none of this.")
        return False
    else:
        # Check that dropped records have recovery metadata
        dropped_with_metadata = []
        for r in final:
            if r.custom_id in DROPPED_IDS:
                has_meta = (
                    r.recovery_metadata
                    and r.recovery_metadata.reprompt
                    and not r.recovery_metadata.reprompt.passed
                )
                dropped_with_metadata.append((r.custom_id, has_meta))

        print("FIX VERIFIED: all records present in output")
        for cid, has_meta in dropped_with_metadata:
            status = "has recovery metadata (passed=False)" if has_meta else "MISSING metadata"
            print(f"  {cid}: {status}")

        all_have_meta = all(m for _, m in dropped_with_metadata)
        if all_have_meta:
            print("\nAll dropped records correctly marked with recovery metadata.")
            return True
        else:
            print("\nWARNING: some dropped records lack recovery metadata.")
            return False


if __name__ == "__main__":
    ok = run()
    raise SystemExit(0 if ok else 1)
