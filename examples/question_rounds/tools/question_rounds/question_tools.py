"""Tools of the question_rounds example.

`check_question` stands in for a real validator: it passes a question once the record has
been tried `bar` times, so the run shows records leaving the loop in rounds 1, 2 and never.
"""

from typing import Any

from agent_actions import udf_tool


@udf_tool
def read_spec(data: Any, *args) -> dict:
    source = data["source"]
    return {"topic": source["topic"], "bar": int(source["bar"])}


@udf_tool
def check_question(data: Any, *args) -> dict:
    spec = data.get("spec") or {}
    prior = data.get("prior") or {}
    tries = int(prior.get("tries") or 0) + 1
    passed = tries >= int(spec.get("bar") or 1)
    return {
        "passed": passed,
        "outcome": "passed" if passed else "failed",
        "reasons": ""
        if passed
        else f"round {tries}: the question does not test {spec.get('topic')}",
        "tries": tries,
        "question": str((data.get("write") or {}).get("question") or ""),
    }


@udf_tool
def publish_question(data: Any, *args) -> dict:
    checked = data.get("round") or {}
    return {
        "status": "published",
        "summary": f"{(data.get('spec') or {}).get('topic')}: passed in round "
        f"{checked.get('tries')}",
    }


@udf_tool
def flag_question(data: Any, *args) -> dict:
    checked = data.get("round") or {}
    return {
        "status": "needs review",
        "summary": f"{(data.get('spec') or {}).get('topic')}: {checked.get('reasons')}",
    }
