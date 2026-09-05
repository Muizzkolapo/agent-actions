"""Deterministic stages of the species-identification pipeline.

Input arrives namespaced by the action that produced it, so each tool reaches
into the namespace it declared as a dependency rather than the bare record.
"""

from typing import Any

from agent_actions import udf_tool
from agent_actions.config.schema import Granularity
from agent_actions.utils.udf_management.registry import FileUDFResult

MARK_KINDS = ("plumage", "structure", "voice", "behaviour", "habitat")


def _as_list(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        return [v for v in value if isinstance(v, dict)]
    return []


@udf_tool()
def flatten_marks(data: dict[str, Any]) -> list[dict[str, Any]]:
    """One record per canonical mark (1->N), so each is voted on independently."""
    canonical = data.get("canonicalize_marks", {}) or {}
    marks = _as_list(canonical.get("canonical_marks"))
    if not marks:
        raise ValueError(
            "no 'canonical_marks' under the canonicalize_marks namespace; "
            f"available keys: {sorted(data)}"
        )

    flattened = []
    for mark in marks:
        kind = str(mark.get("mark_kind", "") or "").lower()
        flattened.append(
            {
                "mark_text": str(mark.get("mark_text", "") or ""),
                "mark_kind": kind if kind in MARK_KINDS else "structure",
                "species": str(mark.get("species", "") or ""),
                "merged_count": int(mark.get("merged_count", 1) or 1),
            }
        )
    return flattened


@udf_tool(granularity=Granularity.FILE)
def dedupe_across_guides(data: list[Any]) -> FileUDFResult:
    """Collapse marks that two guides describe in the same words.

    FILE granularity because a duplicate is only visible across records: the
    same mark reached here from separate entries, and neither record can see
    the other.
    """
    records = [dict(r) for r in data if isinstance(r, dict)]

    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    order: list[tuple[str, str]] = []
    contributors: dict[tuple[str, str], list[int]] = {}

    for index, record in enumerate(records):
        key = (
            str(record.get("species", "")).strip().lower(),
            " ".join(str(record.get("mark_text", "")).lower().split()),
        )
        if key not in by_key:
            by_key[key] = dict(record)
            order.append(key)
            contributors[key] = []
        else:
            by_key[key]["merged_count"] = int(by_key[key].get("merged_count", 1) or 1) + 1
        contributors[key].append(index)

    return FileUDFResult(
        outputs=[{"source_index": contributors[key], "data": by_key[key]} for key in order]
    )


@udf_tool()
def aggregate_votes(data: dict[str, Any]) -> dict[str, Any]:
    """Majority rule over however many voters ran."""
    votes = [
        v
        for key, v in data.items()
        if key.startswith("rank_diagnostic_value") and isinstance(v, dict)
    ]
    keep_votes = sum(1 for v in votes if str(v.get("verdict", "")).lower() == "keep")
    reasons = [str(v.get("reason", "")) for v in votes if v.get("reason")]

    return {
        "decision": "keep" if votes and keep_votes * 2 > len(votes) else "drop",
        "keep_votes": keep_votes,
        "vote_summary": " | ".join(reasons),
        "split_decision": bool(votes) and keep_votes not in (0, len(votes)),
    }


@udf_tool()
def select_approved_marks(data: dict[str, Any]) -> dict[str, Any]:
    """Carry the mark forward with the decision that let it through."""
    mark = data.get("dedupe_across_guides", {}) or {}
    votes = data.get("aggregate_votes", {}) or {}
    return {
        "mark_text": mark.get("mark_text", ""),
        "mark_kind": mark.get("mark_kind", ""),
        "species": mark.get("species", ""),
        "decision": votes.get("decision", ""),
        "vote_summary": votes.get("vote_summary", ""),
    }


@udf_tool()
def locate_supporting_passage(data: dict[str, Any]) -> dict[str, Any]:
    """Find the quote in the entry and return the passage around it.

    ``passage_found`` is what the downstream guards read: a note whose quote is
    not in the entry it claims to come from is ungrounded, and the pipeline
    stops spending on it rather than reviewing it.
    """
    note = data.get("consolidate_id_note", {}) or {}
    source = data.get("source", {}) or {}
    quote = " ".join(str(note.get("supporting_quote", "")).split())
    entry = str(source.get("entry_text", ""))

    if not quote or not entry:
        return {"passage": "", "passage_found": False}

    haystack = " ".join(entry.split())
    position = haystack.lower().find(quote.lower())
    if position < 0:
        return {"passage": "", "passage_found": False}

    start = max(0, position - 200)
    end = min(len(haystack), position + len(quote) + 200)
    return {"passage": haystack[start:end], "passage_found": True}
