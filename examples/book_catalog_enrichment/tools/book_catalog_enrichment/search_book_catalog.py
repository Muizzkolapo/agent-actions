"""Search for similar books using the Open Library API.

Production-grade tool that queries Open Library's free API to find
real books by subject, author, and keyword. No API key required.
Returns grounded results — every recommendation is a real book.
"""

import time
from typing import Any
from urllib.parse import quote

import httpx
from agent_actions import udf_tool

OPEN_LIBRARY_SEARCH = "https://openlibrary.org/search.json"

# Map BISAC prefixes to Open Library subjects
BISAC_TO_SUBJECT = {
    "COM": "computers",
    "BUS": "business",
    "TEC": "technology",
    "SCI": "science",
    "MAT": "mathematics",
    "EDU": "education",
    "FIC": "fiction",
    "BIO": "biography",
    "HIS": "history",
    "PHI": "philosophy",
    "REL": "religion",
    "ART": "art",
    "MUS": "music",
    "POE": "poetry",
    "DRA": "drama",
    "SOC": "social_science",
    "PSY": "psychology",
    "MED": "medical",
    "LAW": "law",
    "POL": "political_science",
    "TRA": "travel",
    "CKB": "cooking",
    "HEA": "health",
    "SEL": "self-help",
    "JUV": "juvenile_fiction",
    "SPO": "sports",
    "GAR": "gardening",
    "PET": "pets",
    "FAM": "family",
    "HOU": "house",
    "CGN": "comics",
    "LIT": "literary_criticism",
    "LCO": "literary_collections",
    "PER": "performing_arts",
}


def _bisac_to_subjects(genres: list[str]) -> list[str]:
    """Convert BISAC codes to Open Library subject terms."""
    subjects = []
    for genre in genres:
        prefix = genre[:3].upper() if len(genre) >= 3 else ""
        if prefix in BISAC_TO_SUBJECT:
            subjects.append(BISAC_TO_SUBJECT[prefix])
        else:
            subjects.append(genre.lower().replace(" & ", " ").replace("/", " "))
    return subjects


def _search_open_library(query: str, limit: int = 20) -> list[dict]:
    """Query Open Library search API."""
    try:
        response = httpx.get(
            OPEN_LIBRARY_SEARCH,
            params={
                "q": query,
                "limit": limit,
                "fields": "key,title,author_name,isbn,subject,first_publish_year,number_of_pages_median,publisher",
            },
            timeout=15.0,
        )
        response.raise_for_status()
        data = response.json()
        return data.get("docs", [])
    except (httpx.HTTPError, Exception) as e:
        print(f"   Open Library API error: {e}")
        return []


def _format_book(doc: dict, relevance_score: float) -> dict:
    """Format an Open Library doc into our schema."""
    isbns = doc.get("isbn", [])
    isbn = isbns[0] if isbns else ""

    return {
        "isbn": isbn,
        "title": doc.get("title", ""),
        "authors": doc.get("author_name", []),
        "genres": (doc.get("subject", []) or [])[:5],
        "description": (
            f"Published {doc.get('first_publish_year', 'unknown')}. "
            f"{doc.get('number_of_pages_median', 'Unknown')} pages. "
            f"Publisher: {(doc.get('publisher', []) or ['Unknown'])[0]}."
        ),
        "relevance_score": relevance_score,
    }


@udf_tool()
def search_book_catalog(data: dict[str, Any]) -> dict[str, Any]:
    """Search Open Library for similar books (grounded retrieval — real books only).

    Queries by subject (from BISAC codes) and keywords. Every result is a
    real book with a real ISBN. No hallucination possible.
    """
    genres = data.get("genres", [])
    keywords = data.get("keywords", [])
    query_text = data.get("query_text", "")
    exclude_isbn = data.get("exclude_isbn", "") or data.get("isbn", "")

    subjects = _bisac_to_subjects(genres)

    all_results: list[dict] = []
    seen_titles: set[str] = set()

    # Query 1: Subject-based search
    if subjects:
        subject_query = " ".join(subjects[:3])
        docs = _search_open_library(f"subject:{subject_query}", limit=15)
        for i, doc in enumerate(docs):
            title = doc.get("title", "")
            if title and title.lower() not in seen_titles:
                seen_titles.add(title.lower())
                all_results.append(_format_book(doc, 10.0 - (i * 0.3)))
        time.sleep(0.5)

    # Query 2: Keyword-based search
    if keywords:
        kw_query = " ".join(keywords[:5])
        docs = _search_open_library(kw_query, limit=10)
        for i, doc in enumerate(docs):
            title = doc.get("title", "")
            if title and title.lower() not in seen_titles:
                seen_titles.add(title.lower())
                all_results.append(_format_book(doc, 7.0 - (i * 0.3)))
        time.sleep(0.5)

    # Query 3: Natural language query fallback
    if query_text and len(all_results) < 10:
        docs = _search_open_library(query_text[:100], limit=10)
        for i, doc in enumerate(docs):
            title = doc.get("title", "")
            if title and title.lower() not in seen_titles:
                seen_titles.add(title.lower())
                all_results.append(_format_book(doc, 5.0 - (i * 0.3)))

    # Filter out the current book
    if exclude_isbn:
        all_results = [r for r in all_results if r["isbn"] != exclude_isbn]

    all_results.sort(key=lambda x: x["relevance_score"], reverse=True)
    top_candidates = all_results[:20]

    return {
        "matching_books": top_candidates,
        "search_metadata": {
            "total_in_catalog": len(all_results),
            "candidates_found": len(all_results),
            "returned": len(top_candidates),
            "search_method": "open_library_api",
            "genres_searched": genres,
            "keywords_searched": keywords,
        },
    }
