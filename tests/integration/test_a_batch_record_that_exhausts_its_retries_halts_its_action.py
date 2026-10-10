"""A batch record that exhausts its retries under `on_exhausted: raise` halts its action.

The halt is raised once the file holding the record is written, and the collect pass took
it for that file's own failure: it logged it and went on, and the action completed with
exit 0 holding the record unanswered, as `return_last` would. Online, the same policy
halts the action, and later runs leave it to `agac retry` or `--fresh`.

Every run is an `agac run` through the CLI, executor, store and mock batch provider. Only
the provider's loss of one record is stood in for.
"""

import pytest

from agent_actions.llm.providers.agac.batch_client import AgacBatchClient
from agent_actions.workflow.executor import action_is_halted
from tests.integration.test_a_stopped_action_keeps_only_what_its_config_still_answers import (
    ACTION,
    _backend,
    _config,
    _run,
    _sent,
    _sent_since,
    _status,
    project,  # noqa: F401
)


@pytest.fixture
def retries_that_raise(project):  # noqa: F811
    config = _config(project)
    config.write_text(
        config.read_text().replace(
            "  run_mode: batch\n",
            "  run_mode: batch\n  retry: { enabled: true, max_attempts: 2, on_exhausted: raise }\n",
        )
    )
    return project


@pytest.fixture
def one_record_never_answered(monkeypatch):
    """The provider drops the first record it is asked for, from every batch it is in."""
    retrieve = AgacBatchClient.retrieve_results
    dropped: list[str] = []

    def dropping(self, batch_id, output_directory=None):
        results = retrieve(self, batch_id, output_directory)
        if not dropped and results:
            dropped.append(min(result.custom_id for result in results))
        return [result for result in results if result.custom_id not in dropped]

    monkeypatch.setattr(AgacBatchClient, "retrieve_results", dropping)


def _halted(root):
    backend = _backend(root)
    try:
        return action_is_halted(backend, ACTION)
    finally:
        backend.close()


def _run_until_nothing_is_out(root):
    """The first batch and each retry of the dropped record take a run to collect."""
    result = _run("--fresh")
    for _ in range(5):
        if _status(root) != "batch_submitted":
            break
        result = _run()
    return result


def test_a_batch_record_that_exhausts_its_retries_halts_the_action(
    retries_that_raise, one_record_never_answered
):
    result = _run_until_nothing_is_out(retries_that_raise)

    assert result.exit_code == 1, result.output
    assert "Retry exhausted" in result.output
    assert _status(retries_that_raise) == "failed"
    assert _halted(retries_that_raise)
    sent = _sent(retries_that_raise)
    again = _run()
    assert again.exit_code == 1, again.output
    assert _sent_since(retries_that_raise, sent) == []
