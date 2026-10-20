from pathlib import Path

from tests.unit.workflow.test_fresh_run_cleanup import _make_coordinator_stub


class TestFreshRunClearsWhatTheLoggerWrote:
    def test_the_log_the_run_logger_wrote_is_cleared(self, tmp_path: Path):
        import logging

        from agent_actions.logging.factory import LoggerFactory

        stub = _make_coordinator_stub(tmp_path, ["a1"])
        io_dir = stub.services.core.action_runner.get_action_folder.return_value
        try:
            LoggerFactory.initialize(output_dir=io_dir, workflow_name="wf", force=True)
            logging.getLogger("agent_actions.workflow").error("a previous run")
            LoggerFactory.flush()
            logs = Path(io_dir) / "logs"
            assert (logs / "events.json").stat().st_size > 0
            assert (logs / "errors.json").stat().st_size > 0

            stub._clear_for_fresh_run()

            assert not (logs / "events.json").exists()
            assert not (logs / "errors.json").exists()
        finally:
            LoggerFactory.reset()
