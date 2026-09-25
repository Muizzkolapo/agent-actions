"""`--full` means a from-scratch rebuild, including on the interpreter it documents.

The script is copied into a user's skills directory and `SKILL.md` tells them to
run it with a plain `python3`, where the framework is usually not importable.
Reclaiming batch records there is impossible — but that says nothing about
whether any exist, so it must not turn `--full` into something narrower.
"""

import builtins
import importlib.util
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
    root = tmp_path / "project"
    base = root / "agent_workflow" / "wf" / "agent_io"
    (base / "store").mkdir(parents=True)
    (base / "store" / "wf.db").write_text("not really a database")
    return root, base


def _import_failing_on(monkeypatch, predicate, error):
    real_import = builtins.__import__

    def _import(name, *args, **kwargs):
        if predicate(name):
            raise error(f"refused {name}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _import)


def test_an_unreachable_framework_does_not_narrow_the_reset(script, project, monkeypatch, capsys):
    root, base = project
    _import_failing_on(monkeypatch, lambda n: n.startswith("agent_actions"), ImportError)

    kept = script.release_batch_records(root, base, "wf")

    assert kept is True
    assert "agac clean -a wf --all" in capsys.readouterr().err


def test_a_reclaim_that_fails_does_narrow_it(script, project, monkeypatch, capsys):
    """The store is what names that record; removing it strands the payload."""
    root, base = project
    _import_failing_on(monkeypatch, lambda n: n == "agent_actions.storage", RuntimeError)

    kept = script.release_batch_records(root, base, "wf")

    assert kept is False
    assert "could not load the reclaimer" in capsys.readouterr().err


def test_a_workflow_with_no_store_has_nothing_to_keep(script, tmp_path):
    root = tmp_path / "project"
    base = root / "agent_workflow" / "wf" / "agent_io"
    base.mkdir(parents=True)

    assert script.release_batch_records(root, base, "wf") is True
