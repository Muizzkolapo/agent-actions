"""A batch the provider refuses because the quota is used up stops the run, failing nothing.

Any refused batch failed its action once every file was walked, so the files after
it were still sent. A quota answer ends the walk at that file: nothing more is sent,
the batch another file already has at the provider stays registered, and the records
of the refused file hold no disposition, so the next run sends them.

The pipeline, store and registry are real; only the provider is a stand-in.
"""

from __future__ import annotations

import pytest

from agent_actions.errors import AgentActionsError, ProviderQuotaStop, VendorAPIError
from agent_actions.llm.batch.infrastructure.registry import BatchRegistryManager
from tests.integration.test_a_collect_pass_leaves_collected_files_alone import _Action, _Provider
from tests.integration.test_batch_rerun_matches_online import ACTION, rec

PROVIDER_TEXT = "Your credit balance is too low"


class _PaymentRequired(Exception):
    """What a provider SDK raises for HTTP 402."""

    status_code = 402


class _OutOfQuota(_Provider):
    """Takes every batch until told its quota is used up, then answers 402."""

    def __init__(self) -> None:
        super().__init__()
        self.out_of_quota = False
        self.refused: list[str] = []

    def submit_batch(self, tasks, batch_name, output_directory):
        if self.out_of_quota:
            self.refused.append(batch_name)
            cause = _PaymentRequired(PROVIDER_TEXT)
            # A batch client raises its own error, with the SDK's as the cause.
            raise VendorAPIError("API error during batch submission", cause=cause) from cause
        return super().submit_batch(tasks, batch_name, output_directory)


@pytest.fixture
def action(tmp_path) -> _Action:
    action = _Action(tmp_path)
    action.provider = _OutOfQuota()
    return action


def _failures(action: _Action) -> list[tuple[str, str]]:
    return [
        (row["record_id"], row["disposition"])
        for row in action.backend.get_disposition(ACTION, snapshots=False)
        if row["disposition"] in ("failed", "exhausted")
    ]


def test_a_quota_refusal_stops_the_run_and_names_the_provider_and_its_text(action):
    files = {"page1.json": [rec("a1", keep=True)]}
    action.upstream_holds(files)
    action.provider.out_of_quota = True

    with pytest.raises(ProviderQuotaStop) as stopped:
        action.process("page1.json", files["page1.json"])

    assert stopped.value.provider == action.config["model_vendor"]
    assert PROVIDER_TEXT in stopped.value.provider_message


def test_the_records_of_the_refused_file_hold_no_failure_and_no_batch_is_registered(action):
    files = {"page1.json": [rec("a1", keep=True)]}
    action.upstream_holds(files)
    action.provider.out_of_quota = True

    with pytest.raises(ProviderQuotaStop):
        action.process("page1.json", files["page1.json"])

    assert action.backend.get_disposition(ACTION, snapshots=False) == []
    assert BatchRegistryManager(action.backend, ACTION).get_all_jobs() == {}


def test_the_batch_another_file_already_has_at_the_provider_stays_registered(action):
    files = {"page1.json": [rec("a1", keep=True)], "page2.json": [rec("b1", keep=True)]}
    action.upstream_holds(files)
    action.process("page1.json", files["page1.json"])
    action.provider.out_of_quota = True

    with pytest.raises(ProviderQuotaStop):
        action.process("page2.json", files["page2.json"])

    jobs = BatchRegistryManager(action.backend, ACTION).get_all_jobs()
    assert {name: entry.batch_id for name, entry in jobs.items()} == {"page1.json": "batch-1"}
    assert _failures(action) == []


def test_the_next_run_sends_the_refused_file_once_the_quota_is_back(action):
    files = {"page1.json": [rec("a1", keep=True)], "page2.json": [rec("b1", keep=True)]}
    action.upstream_holds(files)
    action.process("page1.json", files["page1.json"])
    action.provider.out_of_quota = True
    with pytest.raises(ProviderQuotaStop):
        action.process("page2.json", files["page2.json"])

    action.provider.out_of_quota = False
    action.run(files)

    assert action.provider.names == {"batch-1": "page1.json", "batch-2": "page2.json"}
    assert action.files() == {
        "page1.json": ["processed:a1@batch-1"],
        "page2.json": ["processed:b1@batch-2"],
    }
    assert _failures(action) == []


def test_a_refusal_that_is_not_a_quota_answer_fails_the_action_as_before(action):
    files = {"page1.json": [rec("a1", keep=True)]}
    action.upstream_holds(files)

    def refuse(tasks, batch_name, output_directory):
        raise ConnectionError("the provider refused the batch")

    action.provider.submit_batch = refuse

    with pytest.raises(AgentActionsError, match="Failed to submit batch job"):
        action.process("page1.json", files["page1.json"])
