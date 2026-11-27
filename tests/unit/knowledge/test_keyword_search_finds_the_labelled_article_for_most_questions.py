"""A retrieval regression test: labelled questions against a small help centre.

Each question names the articles that answer it. Keyword search must put one of them in
the top 3 for at least 9 of the 12 questions: the design's own measurement gives 9/12 with
stopwords dropped (10/12 with them kept, at a lower mean reciprocal rank). Paraphrases
with no shared word ("double billed", "money back", "colleague") are what it misses.
"""

from __future__ import annotations

import json
from pathlib import Path

from tests.unit.knowledge.conftest import find, make_project

ARTICLES = json.loads((Path(__file__).parent / "fixtures" / "help_centre.json").read_text())

QUESTIONS = [
    ("I was charged twice for my March invoice.", {"billing-duplicate"}),
    ("The app closes when I upload a photo.", {"app-crash"}),
    ("WIN A FREE CRUISE! Click this link now.", {"security-phishing"}),
    ("Please change the email address of my account.", {"account-email"}),
    ("The refund for my cancelled order has not arrived.", {"refund-timing", "orders-cancel"}),
    ("can't log in to my account", {"account-login", "account-password"}),
    ("how do I get my money back for the yearly subscription", {"refund-policy"}),
    ("double billed this month", {"billing-duplicate"}),
    ("my phone app keeps crashing when sending pictures", {"app-crash"}),
    ("too many requests error from the API", {"api-rate"}),
    ("where do I find my bills", {"billing-invoice"}),
    ("add a colleague to our workspace", {"team-invite"}),
]


def test_keyword_search_puts_a_labelled_article_in_the_top_3_for_9_of_12(tmp_path):
    files = {
        f"kb/{a['slug']}.md": f"# {a['section']}\n\n## {a['heading']}\n\n{a['body']}\n"
        for a in ARTICLES
    }
    root = make_project(tmp_path / "p", files, {"help": {"sources": ["kb/*.md"]}})

    hits = 0
    misses = []
    for question, labelled in QUESTIONS:
        result = find(root, "help", {"keyword": 1.0}, question, top_k=3)
        found = {m["origin"].removeprefix("kb/").removesuffix(".md") for m in result["matches"]}
        if found & labelled:
            hits += 1
        else:
            misses.append(question)

    assert hits >= 9, json.dumps(misses)
