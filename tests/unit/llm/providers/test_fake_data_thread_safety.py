"""The fake provider generates the same data for the same prompt, under concurrency.

Its seed is a hash of the prompt, so one prompt has one answer. Workflows run
actions in parallel — a version fan-out sends three concurrent calls — so that
promise has to hold across threads, not only within one.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from agent_actions.llm.providers.agac.fake_data import FakeDataGenerator

SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["keep", "drop"]},
        "diagnostic_score": {"type": "number"},
        "approved": {"type": "boolean"},
        "reason": {"type": "string"},
    },
}


def generate(prompt: str):
    FakeDataGenerator.set_context(prompt=prompt)
    return FakeDataGenerator.generate_from_schema(SCHEMA, attempt=1)


def test_one_prompt_gives_one_answer_on_a_single_thread():
    """The baseline the concurrent case has to match."""
    assert generate("rank this mark") == generate("rank this mark")


@pytest.mark.parametrize("workers", [3, 8])
def test_concurrent_calls_with_the_same_prompt_agree(workers):
    """A version fan-out: N concurrent calls, one prompt, one expected answer."""
    expected = generate("rank this mark")

    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(lambda _: generate("rank this mark"), range(workers * 8)))

    disagreeing = [r for r in results if r != expected]
    assert not disagreeing, (
        f"{len(disagreeing)} of {len(results)} concurrent generations diverged; "
        "the generator's RNG is shared across threads"
    )


def test_concurrent_calls_with_different_prompts_keep_their_own_answers():
    """Interleaving must not let one thread's context leak into another's draw."""
    prompts = [f"rank mark {i}" for i in range(6)]
    expected = {p: generate(p) for p in prompts}

    with ThreadPoolExecutor(max_workers=6) as pool:
        got = list(pool.map(lambda p: (p, generate(p)), prompts * 10))

    wrong = [(p, v) for p, v in got if v != expected[p]]
    assert not wrong, f"{len(wrong)} generations picked up another thread's context"


def test_an_explicit_seed_is_honoured_per_thread():
    FakeDataGenerator.set_context(seed=1234)
    expected = FakeDataGenerator.generate_from_schema(SCHEMA, attempt=1)

    def other_thread():
        FakeDataGenerator.set_context(seed=1234)
        return FakeDataGenerator.generate_from_schema(SCHEMA, attempt=1)

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: other_thread(), range(20)))

    assert all(r == expected for r in results)


def test_different_prompts_still_produce_different_data():
    """Guards the fix: pinning the RNG must not collapse everything to one answer."""
    values = {str(generate(f"prompt {i}")) for i in range(12)}
    assert len(values) > 1, "the generator stopped varying with the prompt"


class TestClientDeterminism:
    """The provider answers the same way for the same action and prompt, run to run."""

    @staticmethod
    def call(action: str, prompt: str, source_guid: str):
        from agent_actions.llm.providers.agac.client import AgacClient

        return AgacClient.call_json(
            None,
            {"name": action, "agent_type": action},
            prompt,
            {"source_guid": source_guid},
            {"schema": SCHEMA},
        )

    def setup_method(self):
        from agent_actions.llm.providers.agac.client import AgacClient

        AgacClient.reset()

    def test_the_same_action_and_prompt_answer_the_same_across_runs(self):
        """A record's guid is fresh every run, so it must not decide the answer."""
        first = self.call("rank_value_1", "rank this mark", "guid-from-run-one")
        self.setup_method()
        second = self.call("rank_value_1", "rank this mark", "guid-from-run-two")

        assert first == second

    def test_different_actions_on_one_prompt_still_answer_independently(self):
        """A three-way vote needs three opinions, not one opinion three times."""
        self.setup_method()
        answers = {
            str(self.call(f"rank_value_{i}", "rank this mark", "same-guid")) for i in (1, 2, 3)
        }
        assert len(answers) > 1, "the voters collapsed to a single opinion"

    def test_concurrent_actions_on_one_record_each_see_their_first_attempt(self):
        """The attempt counter is keyed per action, so voters do not consume each other's."""
        from concurrent.futures import ThreadPoolExecutor

        from agent_actions.llm.providers.agac.client import AgacClient

        self.setup_method()
        with ThreadPoolExecutor(max_workers=3) as pool:
            list(pool.map(lambda i: self.call(f"rank_value_{i}", "p", "same-guid"), (1, 2, 3)))

        counts = dict(AgacClient._attempt_counts)
        assert sorted(counts.values()) == [1, 1, 1], f"attempts collided: {counts}"
