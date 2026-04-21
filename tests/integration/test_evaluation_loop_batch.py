"""
Integration tests for EvaluationLoop end-to-end in batch mode.

These tests prove the graduated pool pattern works across the full lifecycle:
batch submission -> evaluation -> graduation -> reprompt -> disposition.

All LLM/batch API calls are mocked. Integration = testing the interaction
between EvaluationLoop, strategies, RecoveryState, and processing_recovery.
"""

from unittest.mock import MagicMock

import pytest

from agent_actions.llm.batch.infrastructure.recovery_state import RecoveryState
from agent_actions.llm.providers.batch_base import BatchResult

# Skip entire module if evaluation loop code is not yet available.
# Created by specs 062 (PR #295) and 063 (PR #297).
evaluation_mod = pytest.importorskip(
    "agent_actions.processing.evaluation",
    reason="Requires evaluation loop core (PR #295)",
)
EvaluationLoop = evaluation_mod.EvaluationLoop
EvaluationStrategy = evaluation_mod.EvaluationStrategy

strategies_mod = pytest.importorskip(
    "agent_actions.processing.evaluation.strategies",
    reason="Requires validation strategy (PR #297)",
)
ValidationStrategy = strategies_mod.ValidationStrategy


# ─── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def make_batch_results():
    """Factory for creating N batch results with optional metadata."""

    def _make(n: int, passing_ids: set[str] | None = None) -> list[BatchResult]:
        results = []
        for i in range(n):
            custom_id = f"record_{i}"
            result = MagicMock(spec=BatchResult)
            result.custom_id = custom_id
            result.recovery_metadata = {}
            result.content = f"content_{i}"
            results.append(result)
        return results

    return _make


@pytest.fixture
def deterministic_strategy():
    """Strategy where specific records always pass/fail."""

    def _make(passing_ids: set[str], max_attempts: int = 3):
        strategy = MagicMock(spec=EvaluationStrategy)
        strategy.name = "test_validation"
        strategy.max_attempts = max_attempts
        strategy.on_exhausted = "keep_last"
        strategy.evaluate = lambda r: r.custom_id in passing_ids
        strategy.build_feedback.return_value = "Please fix the output."
        return strategy

    return _make


@pytest.fixture
def nondeterministic_strategy():
    """Strategy that passes different records each call (simulated)."""

    def _make(pass_probability: float = 0.5, seed: int = 42):
        import random

        rng = random.Random(seed)
        strategy = MagicMock(spec=EvaluationStrategy)
        strategy.name = "nondeterministic"
        strategy.max_attempts = 5
        strategy.on_exhausted = "keep_last"
        strategy.evaluate = lambda r: rng.random() < pass_probability
        strategy.build_feedback.return_value = "Try again."
        return strategy

    return _make


# ─── Test 1: Graduated Pool Works ─────────────────────────────────────────────


class TestGraduatedPoolWorks:
    """N records, M fail -> only M resubmitted -> M' pass on retry -> graduated grows."""

    def test_graduated_grows_active_shrinks(self, make_batch_results, deterministic_strategy):
        """Verify graduated grows and active shrinks over iterations."""
        results = make_batch_results(10)
        # Cycle 1: records 0-6 pass, 7-9 fail
        passing = {f"record_{i}" for i in range(7)}
        strategy = deterministic_strategy(passing)
        loop = EvaluationLoop(strategy)

        graduated, failing = loop.split(results)
        assert len(graduated) == 7
        assert len(failing) == 3
        loop.tag_graduated(graduated)

        # Cycle 2: after reprompt, record_7 now passes
        passing.add("record_7")
        strategy_2 = deterministic_strategy(passing)
        loop_2 = EvaluationLoop(strategy_2)
        graduated_2, failing_2 = loop_2.split(failing)
        assert len(graduated_2) == 1  # record_7
        assert len(failing_2) == 2  # record_8, record_9

    def test_already_graduated_not_resubmitted(self, make_batch_results):
        """Graduated records from cycle 1 are never in the failing set of cycle 2."""
        results = make_batch_results(10)
        passing = {f"record_{i}" for i in range(7)}

        # Use side_effect (not plain lambda) so we can track call counts
        strategy = MagicMock(spec=EvaluationStrategy)
        strategy.name = "test_validation"
        strategy.max_attempts = 3
        strategy.on_exhausted = "keep_last"
        strategy.evaluate.side_effect = lambda r: r.custom_id in passing
        strategy.build_feedback.return_value = "Please fix the output."

        loop = EvaluationLoop(strategy)

        # Cycle 1: 7 pass, 3 fail
        graduated, failing = loop.split(results)
        assert len(graduated) == 7
        loop.tag_graduated(graduated)
        graduated_ids = {r.custom_id for r in graduated}

        # Reset call tracking
        strategy.evaluate.reset_mock()

        # Cycle 2: pass ALL results (including graduated) back to split
        graduated_2, failing_2 = loop.split(results)

        # Graduated records must NOT appear in the failing set
        failing_2_ids = {r.custom_id for r in failing_2}
        assert graduated_ids.isdisjoint(failing_2_ids), (
            "Graduated records must not appear in the failing set"
        )

        # evaluate() should only have been called for non-graduated records
        assert strategy.evaluate.call_count == 3


# ─── Test 2: Failure Set Shrinks (Deterministic) ──────────────────────────────


class TestFailureSetShrinksDeterministic:
    """With deterministic validation, each cycle has fewer failures (never more)."""

    def test_monotonic_shrinking(self, make_batch_results):
        """Failure count decreases or stays same on each cycle -- never increases."""
        results = make_batch_results(10)

        # Progressively more records pass each cycle
        cycle_passing = [
            {f"record_{i}" for i in range(3)},  # cycle 0: 3 pass, 7 fail
            {f"record_{i}" for i in range(5)},  # cycle 1: 2 more, 5 fail
            {f"record_{i}" for i in range(8)},  # cycle 2: 3 more, 2 fail
        ]

        active = results
        failure_counts = []

        for passing in cycle_passing:
            strategy = MagicMock(spec=EvaluationStrategy)
            strategy.name = "progressive"
            strategy.max_attempts = 5
            strategy.on_exhausted = "keep_last"
            strategy.evaluate.side_effect = lambda r, p=passing: r.custom_id in p
            strategy.build_feedback.return_value = "Fix."

            loop = EvaluationLoop(strategy)
            graduated, failing = loop.split(active)
            loop.tag_graduated(graduated)
            failure_counts.append(len(failing))
            active = failing
            if not active:
                break

        # Failure count is monotonically non-increasing
        for i in range(1, len(failure_counts)):
            assert failure_counts[i] <= failure_counts[i - 1], (
                f"Failure count increased from {failure_counts[i - 1]} "
                f"to {failure_counts[i]} at cycle {i}"
            )

    def test_converges_to_zero(self, make_batch_results):
        """If strategy eventually passes all, loop terminates with all graduated."""
        results = make_batch_results(10)
        all_graduated = []
        active = results

        for cycle in range(10):
            # Each cycle, one more record passes
            passing = {f"record_{i}" for i in range(min(cycle + 1, 10))}

            strategy = MagicMock(spec=EvaluationStrategy)
            strategy.name = "converging"
            strategy.max_attempts = 10
            strategy.on_exhausted = "keep_last"
            strategy.evaluate.side_effect = lambda r, p=passing: r.custom_id in p
            strategy.build_feedback.return_value = "Fix."

            loop = EvaluationLoop(strategy)
            graduated, failing = loop.split(active)
            loop.tag_graduated(graduated)
            all_graduated.extend(graduated)
            active = failing
            if not active:
                break

        assert len(active) == 0, "All records should eventually graduate"
        assert len(all_graduated) == 10


# ─── Test 3: Non-Deterministic Convergence ────────────────────────────────────


class TestNonDeterministicConvergence:
    """With random validation, graduated records are never re-evaluated."""

    def test_graduated_never_re_evaluated(self, make_batch_results, nondeterministic_strategy):
        """Once tagged graduated, strategy.evaluate() is never called for that record."""
        results = make_batch_results(20)
        strategy = nondeterministic_strategy(pass_probability=0.4, seed=123)
        loop = EvaluationLoop(strategy)

        all_graduated = []
        active = results

        for _cycle in range(5):
            graduated, failing = loop.split(active)
            loop.tag_graduated(graduated)
            all_graduated.extend(graduated)
            active = failing
            if not active:
                break

        # Key invariant: graduated count + remaining active = total
        assert len(all_graduated) + len(active) == 20

    def test_failure_set_cannot_grow(self, make_batch_results, nondeterministic_strategy):
        """Even with random validation, failure set size is non-increasing."""
        results = make_batch_results(20)
        strategy = nondeterministic_strategy(pass_probability=0.4, seed=99)
        loop = EvaluationLoop(strategy)

        active = results
        failure_counts = []

        for _cycle in range(5):
            graduated, failing = loop.split(active)
            loop.tag_graduated(graduated)
            failure_counts.append(len(failing))
            active = failing
            if not active:
                break

        for i in range(1, len(failure_counts)):
            assert failure_counts[i] <= failure_counts[i - 1], (
                f"Failure set grew from {failure_counts[i - 1]} to {failure_counts[i]} at cycle {i}"
            )


# ─── Test 4: Disposition Correct ──────────────────────────────────────────────


class TestDispositionCorrect:
    """Exhausted records get correct disposition after max_attempts."""

    def test_exhausted_records_get_correct_disposition(self, make_batch_results):
        """After max_attempts, failing records remain with correct metadata."""
        results = make_batch_results(5)

        strategy = MagicMock(spec=EvaluationStrategy)
        strategy.name = "strict_validation"
        strategy.max_attempts = 2
        strategy.on_exhausted = "keep_last"
        strategy.evaluate.return_value = False
        strategy.build_feedback.return_value = "Output invalid."

        loop = EvaluationLoop(strategy)
        all_graduated = []
        active = results

        for _attempt in range(strategy.max_attempts):
            graduated, failing = loop.split(active)
            loop.tag_graduated(graduated)
            all_graduated.extend(graduated)
            if not failing:
                break
            loop.build_resubmission(failing, {})
            active = failing

        # Nothing graduated -- always-failing strategy
        assert len(all_graduated) == 0
        # All records remain in active/failing after exhausting attempts
        assert len(active) == 5
        # Each record was evaluated max_attempts times
        assert strategy.evaluate.call_count == 5 * strategy.max_attempts
        # Caller uses on_exhausted policy for these records
        assert strategy.on_exhausted == "keep_last"

    def test_disposition_reason_includes_strategy_name(self, make_batch_results):
        """Reason string is 'evaluation_exhausted:{strategy_name}'."""
        results = make_batch_results(3)

        strategy = MagicMock(spec=EvaluationStrategy)
        strategy.name = "custom_check"
        strategy.max_attempts = 1
        strategy.on_exhausted = "drop"
        strategy.evaluate.return_value = False
        strategy.build_feedback.return_value = "Bad."

        loop = EvaluationLoop(strategy)
        graduated, failing = loop.split(results)

        assert len(graduated) == 0
        assert len(failing) == 3

        # Verify the exhaustion reason format that processing_recovery constructs
        expected_reason = f"evaluation_exhausted:{strategy.name}"
        assert expected_reason == "evaluation_exhausted:custom_check"

        # build_resubmission should produce records for all failures
        submissions = loop.build_resubmission(failing, {})
        assert len(submissions) == 3


# ─── Test 5: Retry + Evaluation Interaction ───────────────────────────────────


class TestRetryEvaluationInteraction:
    """Missing records trigger retry FIRST, then evaluation runs on complete set."""

    def test_retry_before_evaluation(self):
        """Evaluation does not run until retry produces complete result set."""
        strategy = MagicMock(spec=EvaluationStrategy)
        strategy.name = "validation"
        strategy.max_attempts = 3
        strategy.on_exhausted = "keep_last"
        strategy.evaluate.return_value = True

        # Simulate: initial batch returns 8 of 10 results (2 missing)
        initial_results = []
        for i in range(8):
            r = MagicMock(spec=BatchResult)
            r.custom_id = f"record_{i}"
            r.recovery_metadata = {}
            r.content = f"content_{i}"
            initial_results.append(r)

        # After retry: 2 missing results recovered
        retry_results = []
        for i in range(8, 10):
            r = MagicMock(spec=BatchResult)
            r.custom_id = f"record_{i}"
            r.recovery_metadata = {}
            r.content = f"content_{i}"
            retry_results.append(r)

        # Evaluation runs on complete set (initial + retry)
        complete_results = initial_results + retry_results
        loop = EvaluationLoop(strategy)
        graduated, failing = loop.split(complete_results)

        # All 10 should be evaluated and graduate
        assert len(graduated) == 10
        assert len(failing) == 0
        assert strategy.evaluate.call_count == 10

    def test_evaluation_after_retry_uses_full_set(self):
        """After retry fills gaps, evaluation runs on all returned results."""
        strategy = MagicMock(spec=EvaluationStrategy)
        strategy.name = "validation"
        strategy.max_attempts = 3
        strategy.on_exhausted = "keep_last"
        # Even-indexed records pass, odd fail
        strategy.evaluate.side_effect = lambda r: int(r.custom_id.split("_")[1]) % 2 == 0
        strategy.build_feedback.return_value = "Fix."

        complete_results = []
        for i in range(10):
            r = MagicMock(spec=BatchResult)
            r.custom_id = f"record_{i}"
            r.recovery_metadata = {}
            r.content = f"content_{i}"
            complete_results.append(r)

        loop = EvaluationLoop(strategy)
        graduated, failing = loop.split(complete_results)

        # Even: 0,2,4,6,8 = 5 graduated
        assert len(graduated) == 5
        # Odd: 1,3,5,7,9 = 5 failing
        assert len(failing) == 5
        # All 10 were evaluated
        assert strategy.evaluate.call_count == 10

        # Verify correct records graduated
        graduated_ids = {r.custom_id for r in graduated}
        expected = {"record_0", "record_2", "record_4", "record_6", "record_8"}
        assert graduated_ids == expected


# ─── Test 6: Strategy is Pluggable ────────────────────────────────────────────


class TestStrategyPluggable:
    """Mock strategy with custom evaluate/build_feedback works identically."""

    def test_custom_strategy_same_behavior(self, make_batch_results):
        """A custom strategy produces same loop behavior as ValidationStrategy."""

        class AlwaysFailStrategy:
            name = "always_fail"
            max_attempts = 2
            on_exhausted = "drop"

            def evaluate(self, result):
                return False

            def build_feedback(self, result):
                return "This will never pass."

        results = make_batch_results(5)
        loop = EvaluationLoop(AlwaysFailStrategy())
        graduated, failing = loop.split(results)
        assert len(graduated) == 0
        assert len(failing) == 5

    def test_always_pass_strategy_graduates_all(self, make_batch_results):
        """Strategy that always passes graduates everything on first split."""

        class AlwaysPassStrategy:
            name = "always_pass"
            max_attempts = 1
            on_exhausted = "keep_last"

            def evaluate(self, result):
                return True

            def build_feedback(self, result):
                return "Should not be called."

        results = make_batch_results(10)
        loop = EvaluationLoop(AlwaysPassStrategy())
        graduated, failing = loop.split(results)
        assert len(graduated) == 10
        assert len(failing) == 0


# ─── Test 7: Backward Compatibility ──────────────────────────────────────────


class TestBackwardCompat:
    """Old recovery state files (no graduated_results) work correctly."""

    def test_old_state_no_graduated_field(self):
        """Deserialized old state defaults graduated_results to []."""
        state = RecoveryState(phase="reprompt")
        assert hasattr(state, "graduated_results")
        assert state.graduated_results == []
        assert state.evaluation_strategy_name is None

    def test_old_state_evaluation_loop_still_works(self):
        """EvaluationLoop works on results from old state (no evaluation metadata)."""
        results = []
        for i in range(5):
            r = MagicMock(spec=BatchResult)
            r.custom_id = f"record_{i}"
            r.recovery_metadata = {}
            r.content = f"content_{i}"
            results.append(r)

        strategy = MagicMock(spec=EvaluationStrategy)
        strategy.name = "validation"
        strategy.max_attempts = 3
        strategy.on_exhausted = "keep_last"
        strategy.evaluate.return_value = True

        loop = EvaluationLoop(strategy)
        graduated, failing = loop.split(results)

        # All pass -- old results treated as not-yet-evaluated
        assert len(graduated) == 5
        assert len(failing) == 0

    def test_mixed_old_new_results(self, make_batch_results):
        """Mix of results with and without evaluation metadata handled correctly."""
        results = make_batch_results(10)
        # Simulate: first 5 have no metadata (old), last 5 have graduated metadata
        for i in range(5, 10):
            results[i].recovery_metadata = {
                "evaluation": {"passed": True, "strategy_name": "validation"}
            }

        strategy = MagicMock(spec=EvaluationStrategy)
        strategy.name = "validation"
        strategy.evaluate = lambda r: True  # All new ones would pass
        loop = EvaluationLoop(strategy)

        graduated, failing = loop.split(results)
        # 5 already-graduated (skipped) + 5 newly evaluated (all pass) = 10 graduated
        assert len(graduated) == 10
        assert len(failing) == 0
