"""A guard the retry round cannot evaluate gives its records up, and the pass finishes.

A guard that decides differently when a record is prepared again, here one reading `workflow.*`
in a pass that has no run metadata, turns the retried record away. Preparation then admits no
task, which failed the collect pass and left the finished batch owed to every later run.
"""

from tests.unit.llm.batch.test_recovery_preparation_parity import _World, world  # noqa: F401
from tests.unit.llm.batch.test_recovery_round_guard_reads_workflow import _guarded


class TestTheCollectPassOverAGuardTheRetryCannotEvaluate:
    def test_the_pass_finishes_instead_of_raising(self, world):  # noqa: F811
        w = world(_guarded(retry=True))
        w.original = []

        w.collect(None)

        assert w.provider.submitted == []

    def test_the_file_is_collected_so_no_later_run_waits_on_it(self, world):  # noqa: F811
        w = world(_guarded(retry=True))
        w.original = []

        w.collect(None)

        entry = w.manager.get_batch_job("f.json")
        assert entry is None or entry.collected_at is not None
