"""`--full` is a from-scratch rebuild, and the store is what names batch records.

The script is copied into a user's skills directory and `SKILL.md` tells them to
run it with a plain `python3`, where the framework is usually not importable.
Reclaiming is impossible there — but whether anything is at stake is still
visible, because records live at a fixed path only a submit creates.
"""

import builtins
import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[3]
    / "agent_actions"
    / "skills"
    / "agac-agent-skills"
    / "scripts"
    / "reset_workflow.py"
)


@pytest.fixture
def script():
    spec = importlib.util.spec_from_file_location("reset_workflow_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def project(tmp_path):
    """A project whose workflow has a store, as a run that submitted would leave."""
    root = tmp_path / "project"
    base = root / "agent_workflow" / "wf" / "agent_io"
    (base / "store").mkdir(parents=True)
    (base / "target").mkdir()
    (root / "agent_actions.yml").write_text("version: '1.0'\n")
    return root, base


def _record(root, batch_id="mock_batch_abc123"):
    state = root / ".agac" / "batch_state"
    state.mkdir(parents=True, exist_ok=True)
    path = state / f"{batch_id}.json"
    path.write_text(json.dumps({"tasks": [{"user_content": "secret"}]}))
    return path


def _import_failing_on(monkeypatch, predicate, error):
    real_import = builtins.__import__

    def _import(name, *args, **kwargs):
        if predicate(name):
            raise error(f"refused {name}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _import)


def _run_full(script, monkeypatch, root):
    monkeypatch.chdir(root)
    monkeypatch.setattr("sys.argv", ["reset_workflow.py", "wf", "--full"])
    script.main()


class TestWithoutTheFramework:
    """The documented invocation: `python3 scripts/reset_workflow.py wf --full`."""

    def test_a_project_with_no_records_gets_its_full_reset(
        self, script, project, monkeypatch, capsys
    ):
        """Nothing is at stake, so refusing the wipe would narrow --full for no one."""
        root, base = project
        _import_failing_on(monkeypatch, lambda n: n.startswith("agent_actions"), ImportError)

        _run_full(script, monkeypatch, root)

        assert not (base / "store").exists()
        assert "warning" not in capsys.readouterr().err

    def test_a_record_that_would_be_stranded_keeps_the_store(
        self, script, project, monkeypatch, capsys
    ):
        """Wiping the store here orphans the payload for good: --fresh cannot find
        it, and the `clean --all` this would otherwise suggest needs that store."""
        root, base = project
        record = _record(root)
        _import_failing_on(monkeypatch, lambda n: n.startswith("agent_actions"), ImportError)

        _run_full(script, monkeypatch, root)

        assert (base / "store").exists()
        assert record.exists()
        assert "agac clean -a wf --all" in capsys.readouterr().err

    def test_target_and_source_still_go(self, script, project, monkeypatch):
        """Keeping the store is not an excuse to do nothing."""
        root, base = project
        _record(root)
        _import_failing_on(monkeypatch, lambda n: n.startswith("agent_actions"), ImportError)

        _run_full(script, monkeypatch, root)

        assert (base / "target").exists(), "target/ is recreated after the wipe"
        assert not (base / "target" / "anything").exists()


class TestWithTheFramework:
    """On the project's own interpreter the reclaim really runs."""

    @staticmethod
    def _registry(base, batch_id):
        """A store naming one batch, as a submitted run leaves behind."""
        from agent_actions.storage import get_storage_backend

        backend = get_storage_backend(workflow_path=str(base.parent), workflow_name="wf")
        backend.initialize()
        try:
            backend.save_metadata(
                "batch_registry:summarize",
                json.dumps(
                    {
                        "pages.json": {
                            "batch_id": batch_id,
                            "status": "completed",
                            "timestamp": "t",
                            "provider": "agac-provider",
                        }
                    }
                ),
            )
        finally:
            backend.close()

    def test_one_record_that_would_not_go_keeps_the_store(self, script, project, monkeypatch):
        """Not every record — one is enough, because the store names them all."""
        from agent_actions.llm.providers import local_batch_records

        root, base = project
        self._registry(base, "mock_batch_abc123")
        _record(root)
        monkeypatch.setattr(
            local_batch_records, "release_local_batch_record", lambda batch_id: False
        )

        assert script.release_batch_records(root, base, "wf") is False

    def test_records_that_all_go_release_the_store(self, script, project, monkeypatch):
        from agent_actions.llm.providers import local_batch_records

        root, base = project
        self._registry(base, "mock_batch_abc123")
        _record(root)
        monkeypatch.setattr(
            local_batch_records, "release_local_batch_record", lambda batch_id: True
        )

        assert script.release_batch_records(root, base, "wf") is True


class TestTheHelperItself:
    def test_a_reclaimer_that_will_not_load_keeps_the_store(self, script, project, monkeypatch):
        root, base = project
        _record(root)
        _import_failing_on(monkeypatch, lambda n: n == "agent_actions.storage", RuntimeError)

        assert script.release_batch_records(root, base, "wf") is False

    def test_a_workflow_with_no_store_has_nothing_to_keep(self, script, tmp_path):
        root = tmp_path / "project"
        base = root / "agent_workflow" / "wf" / "agent_io"
        base.mkdir(parents=True)

        assert script.release_batch_records(root, base, "wf") is True
