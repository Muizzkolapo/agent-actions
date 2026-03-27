"""
Format a publishable FAQ entry from upstream pipeline outputs.
Combines deduplicated FAQ draft data with cluster context.
"""

from typing import Any

from agent_actions import udf_tool


@udf_tool()
def format_faq_entry(data: dict[str, Any]) -> dict[str, Any]:
    """
    Package final FAQ output into a clean, publishable structure.

    Combines fields from deduplicate_faqs, generate_faq_draft, and
    cluster_tickets_by_topic into a single FAQ record with a
    generated FAQ ID.

    Expected input fields (via context_scope / passthrough):
        - question: The FAQ question text
        - answer: The FAQ answer text
        - cluster_topic: Topic category from clustering
        - cluster_size: Number of tickets behind this FAQ
        - ticket_ids: Source ticket identifiers
        - confidence_score: Quality/confidence of the draft
        - keywords: Relevant search keywords
        - source_tickets_summary: Brief summary of source tickets

    Output fields:
        - faq_id: Generated identifier (e.g. "FAQ-NEW-001")
        - question: The FAQ question
        - answer: The FAQ answer
        - category: Topic category
        - metadata: Supporting context (source count, confidence, keywords)
    """
    content = data.get("content", data)

    # Generate a sequential FAQ ID from source_guid or index
    source_guid = content.get("source_guid", "")
    # Extract a numeric suffix from the guid if possible, otherwise default
    faq_number = 1
    if source_guid:
        # Try to pull trailing digits from the guid for sequencing
        digits = "".join(c for c in str(source_guid) if c.isdigit())
        if digits:
            faq_number = int(digits[-3:]) if len(digits) >= 3 else int(digits)
    faq_id = f"FAQ-NEW-{faq_number:03d}"

    question = content.get("question", "")
    answer = content.get("answer", "")
    category = content.get("cluster_topic", content.get("category", "General"))

    return {
        "faq_id": faq_id,
        "question": question,
        "answer": answer,
        "category": category,
        "metadata": {
            "source_ticket_count": content.get("cluster_size", 0),
            "ticket_ids": content.get("ticket_ids", []),
            "confidence_score": content.get("confidence_score", 0.0),
            "keywords": content.get("keywords", []),
            "source_tickets_summary": content.get("source_tickets_summary", ""),
        },
    }
