"""A guard that reads `workflow.*` still admits its record in a recovery round.

The round is prepared from the stored record, and the guard is evaluated again.
Without the run's metadata the guard cannot read `workflow.*` and filters the
record, so the round goes out empty. This holds for an action that is not
versioned, with a prompt that reads nothing from the run: the guard alone
depends on it.
"""

from .test_recovery_preparation_parity import METADATA, _chain_config, _failing, world  # noqa: F401

GUARD = {"clause": 'workflow.name == "wf"', "behavior": "filter"}


def _guarded(*, retry: bool, repair_rounds: int = 0):
    config = _chain_config(retry=retry, repair_rounds=repair_rounds)
    config.pop("is_versioned_agent")
    config.pop("_version_context")
    config["prompt"] = "Write the options."
    config["guard"] = dict(GUARD)
    return config


class TestARecoveryRoundEvaluatesAGuardThatReadsTheRun:
    def test_a_retry_first_pass_is_sent(self, world):  # noqa: F811
        w = world(_guarded(retry=True))
        w.original = []

        w.collect(METADATA)

        assert len(w.provider.submitted) == 1

    def test_a_repair_first_pass_is_sent(self, world):  # noqa: F811
        w = world(_guarded(retry=False, repair_rounds=2))
        w.original = [_failing()]

        w.collect(METADATA)

        assert len(w.provider.submitted) == 1
        assert "only-one" in w.provider.submitted[0]["body"]["messages"][0]["content"]
