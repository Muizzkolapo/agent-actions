"""Two instances that share one compiled schema object each get their own judge contexts.

The render compiles a schema file one time; the actions of every instance that names it can
hold the same object. Renamed in place, the second instance's names would be applied over the
first instance's, and both would read one instance.
"""

from __future__ import annotations

from agent_actions.config.includes import rename_schema_judge_contexts


def _action(instance: str, schema: dict) -> dict:
    return {
        "name": f"{instance}__review",
        "schema": schema,
        "_include": {
            "branch": "round",
            "instance": instance,
            "local_name": "review",
            "names": {"write": f"{instance}__write", "spec": f"spec_{instance}"},
        },
    }


def test_each_instance_reads_its_own_names_from_one_shared_schema_object():
    rule = {"type": "llm_judge", "params": {"context": ["write.word", "spec.text"]}}
    shared = {
        "name": "review",
        "fields": [{"id": "verdict", "type": "string", "expectations": [rule]}],
        "expectations": [{"type": "llm_judge", "params": {"context": ["write.word"]}}],
    }
    data = {"actions": [_action("c1", shared), _action("c2", shared)]}

    rename_schema_judge_contexts(data)

    first, second = (action["schema"] for action in data["actions"])
    assert first["fields"][0]["expectations"][0]["params"]["context"] == [
        "c1__write.word",
        "spec_c1.text",
    ]
    assert second["fields"][0]["expectations"][0]["params"]["context"] == [
        "c2__write.word",
        "spec_c2.text",
    ]
    assert first["expectations"][0]["params"]["context"] == ["c1__write.word"]
    assert second["expectations"][0]["params"]["context"] == ["c2__write.word"]
    assert shared["fields"][0]["expectations"][0]["params"]["context"] == [
        "write.word",
        "spec.text",
    ]
