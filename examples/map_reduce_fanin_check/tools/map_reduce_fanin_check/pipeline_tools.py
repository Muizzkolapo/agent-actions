"""Deterministic tools exercising map, version merge, fan-in, and file reduce."""

from typing import Any

from agent_actions import udf_tool
from agent_actions.config.schema import Granularity
from agent_actions.utils.udf_management.registry import FileUDFResult


@udf_tool()
def stage_items(data: dict[str, Any]) -> dict[str, Any]:
    src = data.get("source", {}) or {}
    return {"item_id": src.get("item_id", ""), "text": src.get("text", "")}


@udf_tool()
def split_words(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Map: one record per word of the staged text (1->N expansion)."""
    staged = data.get("stage_items", {}) or {}
    item_id = staged.get("item_id", "")
    words = str(staged.get("text", "")).split()
    return [{"item_id": item_id, "word": w, "word_index": i} for i, w in enumerate(words)]


@udf_tool()
def cast_vote(data: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    part = data.get("split_words", {}) or {}
    return {"vote": "keep", "voted_word": part.get("word", "")}


@udf_tool()
def merge_votes(data: dict[str, Any]) -> dict[str, Any]:
    votes = [v for k, v in data.items() if k.startswith("vote_") and isinstance(v, dict)]
    return {
        "decision": "keep" if votes and all(v.get("vote") == "keep" for v in votes) else "drop",
        "n_votes": len(votes),
    }


@udf_tool()
def plain_note(data: dict[str, Any]) -> dict[str, Any]:
    part = data.get("split_words", {}) or {}
    return {"note": f"note-{part.get('item_id', '?')}-{part.get('word_index', '?')}"}


@udf_tool()
def fanin_consumer(data: dict[str, Any]) -> dict[str, Any]:
    merged = data.get("merge_votes")
    note = data.get("plain_note")
    return {
        "decision_seen": bool(isinstance(merged, dict) and "decision" in merged),
        "note_seen": bool(isinstance(note, dict) and "note" in note),
        "both_branches": bool(
            isinstance(merged, dict)
            and "decision" in merged
            and isinstance(note, dict)
            and "note" in note
        ),
    }


@udf_tool()
def unequal_diamond(data: dict[str, Any]) -> dict[str, Any]:
    """Consumes an action and one of its descendants (unequal-depth diamond)."""
    part = data.get("split_words")
    note = data.get("plain_note")
    return {
        "word_seen": bool(isinstance(part, dict) and "word" in part),
        "diamond_note_seen": bool(isinstance(note, dict) and "note" in note),
        "diamond_ok": bool(
            isinstance(part, dict) and "word" in part and isinstance(note, dict) and "note" in note
        ),
    }


@udf_tool(granularity=Granularity.FILE)
def reduce_summary(data: list[Any]) -> FileUDFResult:
    """Reduce: aggregate every fan-in record into a single summary record."""
    items = [dict(item) for item in data]
    merged_count = sum(1 for r in items if r.get("both_branches"))
    return FileUDFResult(
        outputs=[
            {
                "source_index": list(range(len(items))),
                "data": {
                    "total_records": len(items),
                    "fully_merged_records": merged_count,
                    "all_merged": merged_count == len(items) and len(items) > 0,
                },
            }
        ]
    )


@udf_tool()
def cast_vote_direct(data: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    staged = data.get("stage_items", {}) or {}
    return {"vote": "keep", "voted_item": staged.get("item_id", "")}


@udf_tool()
def note_direct(data: dict[str, Any]) -> dict[str, Any]:
    staged = data.get("stage_items", {}) or {}
    return {"note": f"direct-{staged.get('item_id', '?')}"}


@udf_tool()
def fanin_asymmetric(data: dict[str, Any]) -> dict[str, Any]:
    merged = data.get("merge_direct")
    note = data.get("note_direct")
    return {
        "decision_seen": bool(isinstance(merged, dict) and "decision" in merged),
        "note_seen": bool(isinstance(note, dict) and "note" in note),
        "both_branches": bool(
            isinstance(merged, dict)
            and "decision" in merged
            and isinstance(note, dict)
            and "note" in note
        ),
    }
