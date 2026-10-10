"""A workflow the shipped skill shows is one `agac run` accepts.

Authors copy these blocks. Each is loaded as `agac run` loads it and put through
the pre-flight it runs. Only what a block leaves to its author is filled in: an
intent, a prompt, a tool's impl, a HITL's instructions, and a schema whose fields
nothing in the block reads. A block that names an action it does not show continues
a workflow: an action an earlier block of the same page shows is that action, wired
as shown, and any other stands in with no schema, so any field of it may be read. A
stand-in the block only reads sits upstream of one it depends on.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from agent_actions.services.workflow_inspector import WorkflowInspector

_SKILL = Path(__file__).resolve().parents[3] / "agent_actions" / "skills" / "agac-agent-skills"
_FENCE = re.compile(r"^```yaml\n(.*?)^```", re.S | re.M)
_GUARD_NAME = re.compile(r"\b([A-Za-z_]\w*)\.[A-Za-z_]")
_NOT_ACTIONS = {"source", "seed", "version"}


def _blocks() -> list[Any]:
    found = []
    for page in sorted(_SKILL.rglob("*.md")):
        text = page.read_text(encoding="utf-8")
        earlier: dict[str, dict[str, Any]] = {}
        for match in _FENCE.finditer(text):
            block = yaml.safe_load(match.group(1))
            if isinstance(block, list) and all(isinstance(a, dict) and "name" in a for a in block):
                line = text.count("\n", 0, match.start()) + 1
                found.append(
                    pytest.param(block, dict(earlier), id=f"{page.relative_to(_SKILL)}:{line}")
                )
                earlier.update({action["name"]: action for action in block})
    return found


def _guarded(action: dict[str, Any]) -> list[str]:
    guard = action.get("guard")
    condition = guard.get("condition", "") if isinstance(guard, dict) else str(guard or "")
    return _GUARD_NAME.findall(condition)


def _named(action: dict[str, Any]) -> list[str]:
    scope = action.get("context_scope") or {}
    refs = [ref for key in ("observe", "passthrough", "drop") for ref in scope.get(key) or []]
    return [str(ref).split(".", 1)[0] for ref in refs] + _guarded(action)


def _stand_in(name: str, dependencies: list[str], observe: list[str]) -> dict[str, Any]:
    return {
        "name": name,
        "intent": name,
        "prompt": "Answer.",
        "dependencies": dependencies,
        "context_scope": {"observe": observe},
    }


def _upstream(
    block: list[dict[str, Any]], earlier: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    """What *block* names without showing: from earlier blocks of its page, else stand-ins."""
    shown = {action["name"] for action in block} | _NOT_ACTIONS
    borrowed: set[str] = set()
    readers = list(block)
    while readers:
        reader = readers.pop()
        for name in [*(reader.get("dependencies") or []), *_named(reader)]:
            if name in earlier and name not in shown and name not in borrowed:
                borrowed.add(name)
                readers.append(earlier[name])
    from_earlier = [action for name, action in earlier.items() if name in borrowed]
    actions = from_earlier + block
    known = shown | borrowed
    depended = [d for a in actions for d in a.get("dependencies") or [] if d not in known]
    depended = list(dict.fromkeys(depended))
    read = [n for a in actions for n in _named(a) if n not in known and n not in depended]
    read = list(dict.fromkeys(read))
    stand_ins = [_stand_in(n, [], ["source.*"]) for n in read] + [
        _stand_in(n, read, [f"{r}.*" for r in read] or ["source.*"]) for n in depended
    ]
    return stand_ins + [_borrowed(a) for a in from_earlier]


def _authored(action: dict[str, Any]) -> dict[str, Any]:
    action = dict(action)
    action.setdefault("intent", action["name"])
    kind = action.get("kind", "llm")
    if kind == "tool":
        action.setdefault("impl", action["name"])
    elif kind == "hitl":
        action["hitl"] = {"instructions": "Review.", **(action.get("hitl") or {})}
    elif not isinstance(action.get("prompt"), str) or action["prompt"].startswith("$"):
        action["prompt"] = "Answer."
    if kind != "hitl" and not isinstance(action.get("schema"), dict):
        action["schema"] = {"out": "string"}
    return action


def _borrowed(action: dict[str, Any]) -> dict[str, Any]:
    """An earlier block's action; one whose schema the page does not show stands in, wired as shown."""
    if isinstance(action.get("schema"), dict):
        return _authored(action)
    observe = (action.get("context_scope") or {}).get("observe") or ["source.*"]
    return _stand_in(action["name"], action.get("dependencies") or [], observe)


def _project(root: Path, block: list[dict[str, Any]], earlier: dict[str, dict[str, Any]]) -> None:
    workflow = root / "agent_workflow" / "snippet"
    (workflow / "agent_config").mkdir(parents=True)
    (workflow / "agent_io" / "staging").mkdir(parents=True)
    (root / "agent_actions.yml").write_text("default_agent_config: {model_name: gpt-4o-mini}\n")
    config = {
        "name": "snippet",
        "description": "A block of the skill",
        "version": "1.0",
        "defaults": {
            "json_mode": True,
            "granularity": "Record",
            "run_mode": "online",
            "model_vendor": "agac-provider",
            "model_name": "gpt-4o-mini",
            "api_key": "OPENAI_API_KEY",
            "data_source": {"type": "local", "folder": "./staging", "file_type": ["json"]},
        },
        "actions": _upstream(block, earlier) + [_authored(a) for a in block],
    }
    (workflow / "agent_config" / "snippet.yml").write_text(yaml.safe_dump(config, sort_keys=False))


def test_the_skill_shows_workflows():
    assert len(_blocks()) >= 20


@pytest.mark.parametrize(("block", "earlier"), _blocks())
def test_preflight_accepts_the_block(block, earlier, tmp_path):
    _project(tmp_path, block, earlier)
    WorkflowInspector("snippet", project_root=tmp_path).validate()


@pytest.mark.parametrize(("block", "earlier"), _blocks())
def test_no_guard_reads_its_own_action(block, earlier):
    """A guard runs before its action, so the action's own fields are not there yet.

    Pre-flight does not refuse it, and the run reports success with every record guarded out.
    """
    assert [action["name"] for action in block if action["name"] in _guarded(action)] == []
