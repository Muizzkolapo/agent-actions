"""`agac knowledge list | build | search` on a project with a knowledge base.

`list` builds nothing. `build` writes one index file per kind and says when an index is
up to date. `search` prints the matches, or the step's output with `--json`. `--prune`
removes the files of an older digest and is refused while a run holds its lock.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from agent_actions.storage.run_lock import hold_run_lock
from tests._support.agac_cli import run_agac

ARTICLES = {
    "billing.md": "# Billing\n\n## Duplicate charges\n\nIf you were charged twice, the second "
    "charge is a pending authorization.\n",
    "access.md": "# Account access\n\nReset your password from the sign-in page.\n",
}


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    (root / "knowledge" / "help").mkdir(parents=True)
    for name, text in ARTICLES.items():
        (root / "knowledge" / "help" / name).write_text(text, encoding="utf-8")
    config = {
        "project_name": "proj",
        "knowledge": {
            "help_center": {"sources": ["knowledge/help/*.md"], "index": ["keyword", "fuzzy"]}
        },
    }
    (root / "agent_actions.yml").write_text(yaml.safe_dump(config), encoding="utf-8")
    return root


def _ok(result) -> str:
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


def _index_files(project: Path) -> list[str]:
    folder = project / ".agac" / "knowledge" / "help_center"
    return sorted(p.name for p in folder.iterdir()) if folder.exists() else []


def test_list_shows_each_base_and_builds_nothing(project):
    out = _ok(run_agac(project, "knowledge", "list"))

    assert "help_center: 1 source(s), index: keyword, fuzzy" in out
    assert "2 file(s)" in out
    assert "(not built)" in out
    assert _index_files(project) == []


def test_build_writes_each_index_once(project):
    first = _ok(run_agac(project, "knowledge", "build"))
    second = _ok(run_agac(project, "knowledge", "build", "help_center"))

    assert first.count("(built)") == 2
    assert second.count("(up to date)") == 2
    assert [name.split("-")[0] for name in _index_files(project)] == ["fuzzy", "keyword", "set"]
    assert "(built)" in _ok(run_agac(project, "knowledge", "list"))


def test_search_prints_the_best_match_first(project):
    out = _ok(run_agac(project, "knowledge", "search", "help_center", "charged twice"))

    assert "1. knowledge/help/billing.md#1" in out
    assert "Billing > Duplicate charges" in out


def test_search_with_json_prints_the_step_output(project):
    out = _ok(
        run_agac(
            project, "knowledge", "search", "help_center", "pasword", "--method", "fuzzy", "--json"
        )
    )
    result = json.loads(out[out.index("{") :])

    assert result["count"] >= 1
    assert result["matches"][0]["origin"] == "knowledge/help/access.md"
    assert set(result["matches"][0]) == {
        "id",
        "rank",
        "score",
        "text",
        "title",
        "origin",
        "hash",
        "metadata",
    }


def test_an_unknown_base_is_named_with_a_suggestion(project):
    result = run_agac(project, "knowledge", "search", "help_centre", "x")

    assert result.returncode != 0
    assert "Did you mean 'help_center'" in result.stdout + result.stderr


KEY_WORKFLOW = """name: wf
description: d
defaults: {model_vendor: openai, model_name: gpt-4o-mini}
actions:
  - name: answer
    intent: x
    prompt: "{{ source.text }} {{ retrieve.one.count }}"
    schema: {a: string}
    context_scope:
      observe: [source.text, source.faq_id]
      retrieve:
        one: {from: faq, method: key, query: source.faq_id}
"""


@pytest.fixture
def key_project(project: Path) -> Path:
    (project / "knowledge" / "faq.json").write_text(
        json.dumps([{"id": "f1", "q": "How do refunds work?"}]), encoding="utf-8"
    )
    config = yaml.safe_load((project / "agent_actions.yml").read_text())
    config["knowledge"]["faq"] = {
        "sources": [{"path": "knowledge/faq.json", "text": "q", "id": "id"}]
    }
    (project / "agent_actions.yml").write_text(yaml.safe_dump(config), encoding="utf-8")
    workflow = project / "agent_workflow" / "wf" / "agent_config" / "wf.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text(KEY_WORKFLOW, encoding="utf-8")
    return project


def test_list_and_build_report_the_key_index_an_entry_uses_and_prune_keeps_it(key_project):
    listed = _ok(run_agac(key_project, "knowledge", "list"))
    built = _ok(run_agac(key_project, "knowledge", "build", "faq"))
    pruned = _ok(run_agac(key_project, "knowledge", "build", "faq", "--prune"))

    assert "  key: " in listed.split("faq:")[1]
    assert "faq key: " in built and "(built)" in built
    assert "Removed 0 old index file(s)." in pruned
    folder = key_project / ".agac" / "knowledge" / "faq"
    assert sorted(p.name.split("-")[0] for p in folder.iterdir()) == ["key", "keyword"]
    found = _ok(run_agac(key_project, "knowledge", "search", "faq", "f1", "--method", "key"))
    assert "1. f1" in found


def test_prune_removes_old_digests_but_not_during_a_run(project):
    _ok(run_agac(project, "knowledge", "build"))
    before = _index_files(project)
    (project / "knowledge" / "help" / "access.md").write_text("# Access\n\nNew.", encoding="utf-8")

    io_dir = project / "agent_workflow" / "wf" / "agent_io"
    with hold_run_lock(io_dir, "wf"):
        refused = run_agac(project, "knowledge", "build", "--prune")
    assert refused.returncode != 0
    assert "Another run of workflow 'wf' is in progress" in refused.stdout + refused.stderr

    out = _ok(run_agac(project, "knowledge", "build", "--prune"))
    assert "Removed 3 old index file(s)." in out
    after = _index_files(project)
    assert len(after) == 3 and not set(before) & set(after)
