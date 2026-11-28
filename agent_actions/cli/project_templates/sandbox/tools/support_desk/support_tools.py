"""Tools of the support_desk workflow: plain Python, no network, no model."""

from typing import Any

from agent_actions import udf_tool

SPAM_WORDS = ("win a free", "click this link")
BILLING_WORDS = ("charged", "invoice", "refund", "payment")
# Canonical keywords: two tickets that say the same thing in other words share one, so a
# keyword search of the tickets (classify's retrieve entry `similar`) finds one for the other.
KEYWORDS = {
    "billing": BILLING_WORDS,
    "account": ("account", "email", "password"),
    "app": ("app", "upload", "crash"),
}


@udf_tool
def read_ticket(data: Any, *args: Any) -> dict:
    source = data["source"]
    text = str(source["text"])
    lowered = text.lower()
    return {
        "ticket_id": str(source["ticket_id"]),
        "text": text,
        "priority": "high" if source.get("priority") == "high" else "normal",
        "queue": "billing" if any(word in lowered for word in BILLING_WORDS) else "support",
        "is_spam": any(word in lowered for word in SPAM_WORDS),
        "keywords": [key for key, words in KEYWORDS.items() if any(w in lowered for w in words)],
    }


@udf_tool
def merge_scores(data: Any, *args: Any) -> dict:
    ratings = [int((data.get(name) or {}).get("urgency") or 1) for name in ("score_1", "score_2")]
    return {"urgency": max(ratings)}


@udf_tool
def assign_team(data: Any, *args: Any) -> dict:
    ticket = data.get("read_ticket") or {}
    teams = (data.get("seed") or {}).get("teams") or {}
    return {
        "ticket_id": ticket.get("ticket_id", ""),
        "team": teams.get(ticket.get("queue"), "support team"),
        "urgency": int((data.get("merge_scores") or {}).get("urgency") or 1),
    }


@udf_tool
def check_reply(data: Any, *args: Any) -> dict:
    """Stand in for a real reviewer: a high-priority reply passes in round 2."""
    prior = data.get("prior") or {}
    tries = int(prior.get("tries") or 0) + 1
    needed = 2 if (data.get("ticket") or {}).get("priority") == "high" else 1
    passed = tries >= needed
    return {
        "passed": passed,
        "reasons": "" if passed else "a high-priority reply needs a second look",
        "tries": tries,
        "reply": str((data.get("draft_reply") or {}).get("reply") or ""),
    }
