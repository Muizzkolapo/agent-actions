"""An action's expect: suite driving batch repair rounds."""

from agent_actions.expectations.service import ExpectationService
from agent_actions.expectations.types import Suite
from agent_actions.llm.providers.batch_base import BatchResult
from agent_actions.processing.evaluation.strategies import ExpectationStrategy

SUITE = Suite(
    name="s",
    expectations=[
        {
            "id": "enough_options",
            "type": "item_count",
            "field": "options",
            "min": 2,
            "hint": "list at least two options",
        }
    ],
)


def _service(**kwargs) -> ExpectationService:
    return ExpectationService(suite=SUITE, **{"repair": "auto", "max_iterations": 2, **kwargs})


def _result(custom_id: str, content) -> BatchResult:
    return BatchResult(custom_id=custom_id, content=content, success=True)


class TestEvaluate:
    def test_a_record_that_satisfies_the_suite_passes(self):
        strategy = ExpectationStrategy(_service())
        outcome = strategy.evaluate(_result("r1", {"options": ["a", "b"]}))
        assert outcome.passed is True

    def test_a_record_that_fails_the_suite_does_not_pass(self):
        strategy = ExpectationStrategy(_service())
        outcome = strategy.evaluate(_result("r1", {"options": ["a"]}))
        assert outcome.passed is False
        assert outcome.failure_type == "expectation_fail"

    def test_an_api_error_is_not_an_expectation_failure(self):
        strategy = ExpectationStrategy(_service())
        failed = BatchResult(custom_id="r1", content=None, success=False, error="429")
        outcome = strategy.evaluate(failed)
        assert outcome.passed is False
        assert outcome.failure_type == "api_error"

    def test_an_expansion_fails_when_any_of_its_records_does(self):
        strategy = ExpectationStrategy(_service())
        outcome = strategy.evaluate(_result("r1", [{"options": ["a", "b"]}, {"options": ["a"]}]))
        assert outcome.passed is False

    def test_an_expansion_passes_only_when_every_record_does(self):
        strategy = ExpectationStrategy(_service())
        outcome = strategy.evaluate(
            _result("r1", [{"options": ["a", "b"]}, {"options": ["c", "d"]}])
        )
        assert outcome.passed is True

    def test_a_response_that_is_not_a_record_fails_structurally(self):
        strategy = ExpectationStrategy(_service())
        outcome = strategy.evaluate(_result("r1", "not a record"))
        assert outcome.passed is False


class TestTheVerdictIsKept:
    def test_the_verdict_is_available_without_re_running_the_suite(self):
        strategy = ExpectationStrategy(_service())
        strategy.evaluate(_result("r1", {"options": ["a"]}))
        verdict = strategy.verdict_for("r1")
        assert verdict is not None
        assert verdict.overall_pass is False
        assert [o.id for o in verdict.failed] == ["enough_options"]

    def test_an_unevaluated_record_has_no_verdict(self):
        strategy = ExpectationStrategy(_service())
        assert strategy.verdict_for("never-seen") is None

    def test_a_second_evaluation_replaces_the_first(self):
        strategy = ExpectationStrategy(_service())
        strategy.evaluate(_result("r1", {"options": ["a"]}))
        strategy.evaluate(_result("r1", {"options": ["a", "b"]}))
        assert strategy.verdict_for("r1").overall_pass is True


class TestBuildFeedback:
    def test_auto_names_the_failed_rule_and_its_hint(self):
        strategy = ExpectationStrategy(_service())
        result = _result("r1", {"options": ["a"]})
        strategy.evaluate(result)
        feedback = strategy.build_feedback(result)
        assert "enough_options" in feedback
        assert "list at least two options" in feedback

    def test_auto_carries_the_previous_output_back(self):
        strategy = ExpectationStrategy(_service())
        result = _result("r1", {"options": ["only-one"]})
        strategy.evaluate(result)
        assert "only-one" in strategy.build_feedback(result)

    def test_retry_resends_the_prompt_with_nothing_appended(self):
        strategy = ExpectationStrategy(
            ExpectationService(suite=SUITE, repair="retry", max_iterations=2)
        )
        result = _result("r1", {"options": ["a"]})
        strategy.evaluate(result)
        assert strategy.build_feedback(result) == ""


class TestPolicyComesFromTheService:
    def test_max_attempts_is_max_iterations(self):
        assert ExpectationStrategy(_service(max_iterations=4)).max_attempts == 4

    def test_on_exhausted_is_carried_through(self):
        strategy = ExpectationStrategy(_service(on_exhausted="raise"))
        assert strategy.on_exhausted == "raise"

    def test_the_strategy_is_named_for_the_recovery_key_it_writes(self):
        assert ExpectationStrategy(_service()).name == "expectations"


class TestTheVerdictMapNeedsAnIdentityToo:
    """Two records that lost their correlation are not the same record.

    The verdict map keys on custom_id. A provider that returns results with no
    id stamps the same sentinel on each, so without a guard the second record's
    verdict overwrites the first's — and a record that genuinely passed ships an
    `expect` block that is factually wrong about its own data.
    """

    def _strategy(self):
        from agent_actions.llm.batch.services.repair_ops import build_repair_strategy

        return build_repair_strategy(
            {
                "name": "author",
                "action_name": "author",
                "expect": {
                    "repair": "auto",
                    "max_iterations": 2,
                    "expectations": [
                        {"id": "enough", "type": "item_count", "field": "options", "min": 2}
                    ],
                },
            }
        )

    def test_two_unidentified_records_keep_their_own_verdicts(self):
        from agent_actions.llm.providers.batch_base import UNIDENTIFIED_RECORD

        strategy = self._strategy()
        good = BatchResult(
            custom_id=UNIDENTIFIED_RECORD, content={"options": ["a", "b"]}, success=True
        )
        bad = BatchResult(
            custom_id=UNIDENTIFIED_RECORD, content={"options": ["only-one"]}, success=True
        )
        assert strategy.evaluate(good).passed is True
        assert strategy.evaluate(bad).passed is False
        strategy.write_verdicts([good, bad])

        assert good.content["expect"]["overall_pass"] is True, (
            "a record that passed shipped the other record's failing verdict, which is factually "
            f"wrong about its own data: {good.content['expect']}"
        )
        assert bad.content["expect"]["overall_pass"] is False

    def test_identified_records_are_unaffected(self):
        strategy = self._strategy()
        good = BatchResult(custom_id="r1", content={"options": ["a", "b"]}, success=True)
        bad = BatchResult(custom_id="r2", content={"options": ["only-one"]}, success=True)
        strategy.evaluate(good)
        strategy.evaluate(bad)
        strategy.write_verdicts([good, bad])
        assert good.content["expect"]["overall_pass"] is True
        assert bad.content["expect"]["overall_pass"] is False
