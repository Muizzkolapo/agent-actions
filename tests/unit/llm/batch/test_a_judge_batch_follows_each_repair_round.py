"""A record the judge fails is repaired in a batch, and its repair is judged in a batch (1814).

The loop is the existing one — `<file>_repair_<n>` for what failed, bounded by
`max_iterations`, ended by `on_exhausted` — with a judge batch after the main
batch and after each repair round.
"""

from .judge_batch_world import (
    JudgingProvider,
    Run,
    answers,
    judge_rule,
    judged_config,
    value_in,
    verdict,
)


def _run(repaired_value, **expect):
    provider = JudgingProvider(
        lambda prompt, _vote: verdict(value_in(prompt) in (["good"], ["fixed"]), "judged"),
        repair=lambda _custom_id: {"options": repaired_value},
    )
    run = Run(judged_config([judge_rule()], **expect), provider)
    assert run.main_batch_returns(answers({"r1": ["bad"], "r2": ["good"]})) is False
    out = None
    for _pass in range(6):
        out = run.recovery_batch_returns()
        if out is not None:
            break
    return run, provider, out


def test_the_repair_round_is_judged_by_a_second_judge_batch():
    run, provider, out = _run(["fixed"], repair="auto", max_iterations=3)

    assert out == "/out.json"
    assert [name for name, _n in provider.batches] == [
        "f.json_judge_1",
        "f.json_repair_1",
        "f.json_judge_2",
    ]
    assert provider.batches[2] == ("f.json_judge_2", 1), "only the repaired value is judged"
    assert run.online == []
    assert {cid: v["overall_pass"] for cid, v in run.verdicts().items()} == {
        "r1": True,
        "r2": True,
    }


def test_max_iterations_and_on_exhausted_still_end_the_loop():
    run, provider, out = _run(["bad"], repair="auto", max_iterations=2, on_exhausted="fail")

    assert out == "/out.json"
    assert [name for name, _n in provider.batches] == [
        "f.json_judge_1",
        "f.json_repair_1",
    ], "the repair repeated a value already judged, so it needs no second judge batch"
    assert run.online == []
    finalized = {r.custom_id: r for r in run.finalized}
    assert finalized["r1"].success is False
    assert finalized["r1"].exhausted is True
    assert "Expectations exhausted after 2 iteration(s)" in finalized["r1"].error
    assert finalized["r2"].success is True


def test_each_new_value_a_round_produces_is_judged_before_the_loop_ends():
    run, provider, _out = _run(["worse"], repair="auto", max_iterations=2, on_exhausted="fail")

    assert [name for name, _n in provider.batches] == [
        "f.json_judge_1",
        "f.json_repair_1",
        "f.json_judge_2",
    ]
    assert run.online == []
    finalized = {r.custom_id: r for r in run.finalized}
    assert finalized["r1"].exhausted is True
