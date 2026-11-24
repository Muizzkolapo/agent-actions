"""Each decision of a sandbox scenario is a hash of the seed, action, record, attempt and name.

So the decisions do not depend on the order the calls arrive in, a record matched by
``records`` takes its rules over the action's and the defaults', and a fault stops at
``heal_on_attempt``.
"""

from __future__ import annotations

import random

from agent_actions.llm.providers.agac import scenario as sc

ACTIONS = {"extract": None, "classify": None}


def _scenario(tmp_path, text: str) -> sc.Scenario:
    (tmp_path / "sandbox.yml").write_text(text, encoding="utf-8")
    return sc.load(None, tmp_path, ACTIONS)


def _errors(
    scenario: sc.Scenario, calls: list[tuple[str, int]]
) -> dict[tuple[str, int], str | None]:
    rules = scenario.rules_for("extract", {})
    return {
        (record, attempt): scenario.error_for("extract", record, attempt, rules)
        for record, attempt in calls
    }


ERRORS = "seed: 3\ndefaults:\n  errors: {rate: 0.5, kinds: [rate_limit, timeout, refusal]}\n"


def test_the_decisions_do_not_depend_on_the_order_of_the_calls(tmp_path):
    scenario = _scenario(tmp_path, ERRORS)
    calls = [(f"r{n}", attempt) for n in range(40) for attempt in (1, 2, 3)]
    shuffled = calls[:]
    random.Random(1).shuffle(shuffled)

    assert _errors(scenario, calls) == _errors(scenario, shuffled)
    decided = set(_errors(scenario, calls).values())
    assert None in decided and {"rate_limit", "timeout", "refusal"} <= decided


def test_another_seed_makes_other_decisions(tmp_path):
    calls = [(f"r{n}", 1) for n in range(40)]
    first = _errors(_scenario(tmp_path, ERRORS), calls)

    second = _errors(_scenario(tmp_path, ERRORS.replace("seed: 3", "seed: 4")), calls)

    assert first != second


def test_a_rate_of_one_fails_every_call_and_zero_none(tmp_path):
    always = _scenario(tmp_path, "defaults:\n  errors: {rate: 1.0, kinds: [timeout]}\n")
    never = _scenario(tmp_path, "defaults:\n  errors: {rate: 0.0, kinds: [timeout]}\n")
    calls = [(f"r{n}", a) for n in range(20) for a in (1, 5)]

    assert set(_errors(always, calls).values()) == {"timeout"}
    assert set(_errors(never, calls).values()) == {None}


def test_a_fault_stops_at_heal_on_attempt(tmp_path):
    scenario = _scenario(
        tmp_path, "defaults:\n  errors: {rate: 1.0, kinds: [empty], heal_on_attempt: 3}\n"
    )

    decided = _errors(scenario, [("r", 1), ("r", 2), ("r", 3), ("r", 4)])

    assert list(decided.values()) == ["empty", "empty", None, None]


def test_rules_break_until_heal_on_attempt(tmp_path):
    scenario = _scenario(
        tmp_path, "defaults:\n  break_rules: {rules: all, rate: 1.0, heal_on_attempt: 2}\n"
    )
    rules = scenario.rules_for("extract", {})

    assert scenario.breaks("extract", "r", 1, rules)
    assert not scenario.breaks("extract", "r", 2, rules)


PRECEDENCE = """
defaults:
  latency_ms: 1
  errors: {rate: 0.2, kinds: [timeout], heal_on_attempt: 3}
actions:
  extract:
    errors: {rate: 0.4, kinds: [empty]}
    pin: {label: low}
records:
  - match: {source.page_id: p3}
    actions:
      extract: {error: refusal}
  - match: {source.page_id: p3, source.lang: en}
    actions:
      extract: {pin: {label: never}}
"""


def test_an_action_s_errors_replace_the_default_errors_whole(tmp_path):
    rules = _scenario(tmp_path, PRECEDENCE).rules_for("extract", {"source": {"page_id": "p1"}})

    assert rules.errors.rate == 0.4 and rules.errors.kinds == ["empty"]
    assert rules.errors.heal_on_attempt is None
    assert rules.latency_ms == (1, 1)
    assert rules.pin == {"label": "low"}


def test_a_matched_record_takes_its_rules_over_the_action_s(tmp_path):
    scenario = _scenario(tmp_path, PRECEDENCE)

    rules = scenario.rules_for("extract", {"source": {"page_id": "p3", "lang": "en"}})

    assert rules.errors.rate == 1.0 and rules.errors.kinds == ["refusal"]
    assert rules.pin == {"label": "low"}
    assert scenario.error_for("extract", "any", 7, rules) == "refusal"


def test_a_match_reads_a_dotted_path_into_the_context_as_sent(tmp_path):
    scenario = _scenario(tmp_path, PRECEDENCE)

    as_text = scenario.rules_for("extract", '{"source": {"page_id": "p3"}}')
    other_action = scenario.rules_for("classify", {"source": {"page_id": "p3"}})

    assert as_text.errors.kinds == ["refusal"]
    assert other_action.errors.kinds == ["timeout"]


def test_a_judge_passes_at_its_pass_rate(tmp_path):
    half = _scenario(tmp_path, "defaults:\n  judge: {pass_rate: 0.5}\n")
    prompts = [f"judge prompt {n}" for n in range(200)]

    passed = [half.judge_passes("extract", prompt) for prompt in prompts]

    assert 60 < sum(passed) < 140
    assert passed == [half.judge_passes("extract", prompt) for prompt in prompts]


def test_latency_is_chosen_inside_its_range(tmp_path):
    scenario = _scenario(tmp_path, "defaults:\n  latency_ms: [10, 20]\n")
    rules = scenario.rules_for("extract", {})

    waits = {scenario.latency_ms("extract", f"r{n}", 1, rules) for n in range(50)}

    assert waits <= set(range(10, 21)) and len(waits) > 1


def test_a_batch_drops_a_result_only_the_first_time(tmp_path):
    scenario = _scenario(tmp_path, "batch: {drop_rate: 1.0, fail: [classify]}\n")

    assert scenario.drops("extract", "r", 1)
    assert not scenario.drops("extract", "r", 2)
    assert scenario.fails_batch("classify") and not scenario.fails_batch("extract")


def test_the_summary_line_counts_what_the_mock_did(tmp_path):
    scenario = sc.load("chaos", tmp_path, ACTIONS)
    scenario.count("errors", 2)
    scenario.count("rules_broken")

    assert scenario.summary() == (
        "SANDBOX scenario chaos: 2 errors, 1 rules broken, 0 batch results dropped"
    )


def test_a_decision_depends_on_the_attempt(tmp_path):
    scenario = _scenario(tmp_path, "seed: 1\n")
    records = [f"r{n}" for n in range(40)]

    first = [scenario.chance("extract", record, 1, "error") for record in records]
    second = [scenario.chance("extract", record, 2, "error") for record in records]

    assert all(a != b for a, b in zip(first, second, strict=True))


def test_a_decision_depends_on_the_action(tmp_path):
    scenario = _scenario(tmp_path, "seed: 1\n")
    records = [f"r{n}" for n in range(40)]

    extract = [scenario.chance("extract", record, 1, "error") for record in records]
    classify = [scenario.chance("classify", record, 1, "error") for record in records]

    assert all(a != b for a, b in zip(extract, classify, strict=True))


def test_a_record_is_named_by_its_input_whatever_the_order_of_its_keys():
    one = sc.Scenario.record_key({"source": {"a": 1, "b": 2}, "up": {"c": 3}}, "g-1")
    same = sc.Scenario.record_key({"up": {"c": 3}, "source": {"b": 2, "a": 1}}, "g-2")
    other = sc.Scenario.record_key({"source": {"a": 1, "b": 3}, "up": {"c": 3}}, "g-1")

    assert one == same != other
    assert sc.Scenario.record_key(None, "g-1") == "g-1"


GROUPS = {"score_1": "score", "score_2": "score", "foo_2": None}
BY_GROUP = """
actions:
  score: {latency_ms: 7}
records:
  - match: {source.page_id: p3}
    actions: {score: {error: refusal}}
batch:
  fail: [score]
"""


def test_a_version_group_s_base_name_names_each_version_in_every_section(tmp_path):
    (tmp_path / "sandbox.yml").write_text(BY_GROUP)
    scenario = sc.load(None, tmp_path, GROUPS)
    p3 = {"source": {"page_id": "p3"}}

    for version in ("score_1", "score_2"):
        assert scenario.rules_for(version, {}).latency_ms == (7, 7)
        assert scenario.rules_for(version, p3).errors.kinds == ["refusal"]
        assert scenario.fails_batch(version)


def test_an_exact_name_takes_its_entry_over_its_group_s(tmp_path):
    (tmp_path / "sandbox.yml").write_text(
        "actions:\n  score: {latency_ms: 7}\n  score_2: {latency_ms: 9}\n"
    )
    scenario = sc.load(None, tmp_path, GROUPS)

    assert scenario.rules_for("score_1", {}).latency_ms == (7, 7)
    assert scenario.rules_for("score_2", {}).latency_ms == (9, 9)


def test_an_action_named_like_a_version_is_no_group_s(tmp_path):
    (tmp_path / "sandbox.yml").write_text("actions:\n  foo_2: {latency_ms: 3}\n")
    scenario = sc.load(None, tmp_path, GROUPS)

    assert scenario.rules_for("foo_2", {}).latency_ms == (3, 3)
    assert not scenario.fails_batch("foo_2")
