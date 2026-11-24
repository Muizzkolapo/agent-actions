"""`--full` removes the output of sandbox runs with the store that holds the sandbox db.

Left behind, `agent_io/sandbox/.agent_status.json` tells the next `--sandbox` run that
each action is complete, and the store it would read is gone.
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
    """A project that a real run and a sandbox run have run."""
    root = tmp_path / "project"
    base = root / "agent_workflow" / "wf" / "agent_io"
    (base / "store").mkdir(parents=True)
    (base / "store" / "wf.sandbox.db").write_bytes(b"")
    (base / "target").mkdir()
    sandbox = base / "sandbox"
    (sandbox / "target" / "summarize").mkdir(parents=True)
    (sandbox / ".agent_status.json").write_text(json.dumps({"summarize": "completed"}))
    (root / "agent_actions.yml").write_text("version: '1.0'\n")
    return root, base


@pytest.mark.parametrize("framework", [True, False], ids=["framework", "plain-python"])
def test_a_full_reset_removes_the_sandbox_output(script, project, monkeypatch, framework):
    root, base = project
    if not framework:
        real_import = builtins.__import__

        def _import(name, *args, **kwargs):
            if name.startswith("agent_actions"):
                raise ImportError(f"refused {name}")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _import)
    monkeypatch.chdir(root)
    monkeypatch.setattr("sys.argv", ["reset_workflow.py", "wf", "--full"])

    script.main()

    assert not (base / "sandbox").exists()
    assert [p.name for p in (base / "store").iterdir()] == ["wf.db.lock"]


def test_a_soft_reset_leaves_the_sandbox_output(script, project, monkeypatch):
    root, base = project
    monkeypatch.chdir(root)
    monkeypatch.setattr("sys.argv", ["reset_workflow.py", "wf"])

    script.main()

    assert (base / "sandbox" / ".agent_status.json").exists()


def test_a_full_reset_reclaims_the_batches_the_sandbox_store_names(script, project, monkeypatch):
    from agent_actions.config.sandbox import sandbox_mode
    from agent_actions.llm.providers import local_batch_records
    from agent_actions.storage import get_storage_backend

    root, base = project
    (base / "store" / "wf.sandbox.db").unlink()
    with sandbox_mode(True):
        backend = get_storage_backend(workflow_path=str(base.parent), workflow_name="wf")
    backend.initialize()
    entry = {"batch_id": "sandbox_batch", "status": "completed", "timestamp": "t"}
    backend.save_metadata("batch_registry:summarize", json.dumps({"pages.json": entry}))
    backend.close()
    released = []
    monkeypatch.setattr(local_batch_records, "discard_partial_batch_records", lambda: None)
    monkeypatch.setattr(
        local_batch_records,
        "release_local_batch_record",
        lambda batch_id: released.append(batch_id) or True,
    )

    assert script.release_batch_records(root, base, "wf") is True

    assert released == ["sandbox_batch"]
    assert not (base / "store" / "wf.db").exists()
