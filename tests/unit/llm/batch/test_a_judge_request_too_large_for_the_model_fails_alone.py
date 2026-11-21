"""A judge request too large for the model fails only its judge call, as online does.

Online, the judge call raises and that one rule fails with `judge call failed: <error>`;
every other record goes on. The judge batch raised the error instead, which failed every
record of the file.
"""

from agent_actions.errors import PromptTooLargeError

from .judge_batch_world import (
    JudgingProvider,
    Run,
    _write,
    answers,
    judge_rule,
    judged_config,
    value_in,
    verdict,
)

TOO_LARGE = "Estimated prompt size exceeds model context window (128000 tokens)"


class SizeCheckingProvider(JudgingProvider):
    """Refuses a judge request whose value under test is `huge`, as the message builder does."""

    def format_task_for_provider(self, batch_task, schema=None):
        if batch_task.custom_id.startswith("j_") and value_in(batch_task.prompt) == ["huge"]:
            raise PromptTooLargeError(TOO_LARGE)
        return super().format_task_for_provider(batch_task, schema)


def _run(values, votes=2, repair="none"):
    provider = SizeCheckingProvider(lambda prompt, vote: verdict(True))
    run = Run(judged_config([judge_rule(votes=votes)], repair=repair), provider)
    return run, provider, run.main_batch_returns(answers(values))


def _detail(written, record):
    (outcome,) = written[record]["outcomes"]
    return outcome["passed"], outcome["detail"]


def test_the_other_judge_requests_still_go_out():
    _run_, provider, wrote = _run({"r1": ["huge"], "r2": ["small"]})

    assert wrote is False
    assert provider.batches == [("f.json_judge_1", 2)]


def test_the_call_fails_with_the_error_online_gives_and_the_rest_pass():
    run, _provider, _wrote = _run({"r1": ["huge"], "r2": ["small"]})
    run.recovery_batch_returns()

    assert _detail(run.verdicts(), "r1") == (False, f"judge call failed: {TOO_LARGE}")
    assert _detail(run.verdicts(), "r2")[0] is True
    assert run.online == []


def test_a_round_where_no_request_fits_writes_the_file_without_a_judge_batch():
    values = {"r1": ["huge"]}
    run, provider, wrote = _run(values)

    assert provider.batches == []
    assert wrote is True
    written = _write(run.config, answers(values), run.context_map)
    assert _detail(written, "r1") == (False, f"judge call failed: {TOO_LARGE}")
    assert run.online == []


def test_under_a_repair_policy_the_failed_call_sends_its_record_to_repair():
    run, provider, wrote = _run({"r1": ["huge"]}, repair="auto")

    assert wrote is False
    assert [name for name, _ in provider.batches] == ["f.json_repair_1"]
    assert run.online == []
