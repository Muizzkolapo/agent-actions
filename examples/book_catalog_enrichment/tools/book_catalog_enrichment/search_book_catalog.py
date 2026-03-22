"""Search book catalog for similar books.

Abstraction layer for catalog search — currently JSON file search.
Can be swapped to Vector DB (ChromaDB/Pinecone) or SQL without workflow changes.
"""

import json
import os

from agent_actions import udf_tool

# Path to seed data catalog (relative to workflow)
CATALOG_PATH = os.path.join(
    os.path.dirname(__file__),
    "../../agent_workflow/book_catalog_enrichment/seed_data/book_catalog.json",
)


def _load_catalog() -> list[dict]:
    """Load book catalog from seed data."""
    catalog_path = os.path.normpath(CATALOG_PATH)

    if not os.path.exists(catalog_path):
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        catalog_path = os.path.join(
            base_dir,
            "agent_workflow/book_catalog_enrichment/seed_data/book_catalog.json",
        )

    if os.path.exists(catalog_path):
        with open(catalog_path, encoding="utf-8") as f:
            return json.load(f)

    return []


def _calculate_relevance_score(book: dict, genres: list[str], keywords: list[str]) -> float:
    """Calculate relevance score for a book based on search criteria."""
    score = 0.0

    book_genres = book.get("genres", [])
    book_keywords = book.get("keywords", [])
    book_description = book.get("description", "").lower()

    # Genre matching (high weight)
    for genre in genres:
        if genre in book_genres:
            score += 10.0
        elif any(bg.startswith(genre[:6]) for bg in book_genres if len(genre) >= 6):
            score += 5.0

    # Keyword matching
    for keyword in keywords:
        keyword_lower = keyword.lower()
        if keyword_lower in [k.lower() for k in book_keywords]:
            score += 3.0
        elif keyword_lower in book_description:
            score += 1.0

    return score


@udf_tool()
def search_book_catalog(data: dict) -> dict:
    """Search catalog for similar books (grounded retrieval — no hallucination).

    Current backend: JSON file search with keyword/genre matching.
    Future: swap to Vector DB or SQL without changing the workflow YAML.
    """
    genres = data.get("genres", [])
    keywords = data.get("keywords", [])
    exclude_isbn = data.get("exclude_isbn", "") or data.get("isbn", "")

    catalog = _load_catalog()

    if not catalog:
        return {
            "matching_books": [],
            "search_metadata": {
                "total_in_catalog": 0,
                "candidates_found": 0,
                "search_method": "json_file",
                "error": "Catalog not found or empty",
            },
        }

    scored_books = []
    for book in catalog:
        if book.get("isbn") == exclude_isbn:
            continue

        score = _calculate_relevance_score(book, genres, keywords)

        if score > 0:
            scored_books.append(
                {
                    "isbn": book.get("isbn"),
                    "title": book.get("title"),
                    "authors": book.get("authors", []),
                    "genres": book.get("genres", []),
                    "description": book.get("description", ""),
                    "relevance_score": score,
                }
            )

    scored_books.sort(key=lambda x: x["relevance_score"], reverse=True)
    top_candidates = scored_books[:20]

    return {
        "matching_books": top_candidates,
        "search_metadata": {
            "total_in_catalog": len(catalog),
            "candidates_found": len(scored_books),
            "returned": len(top_candidates),
            "search_method": "json_file",
            "genres_searched": genres,
            "keywords_searched": keywords,
        },
    }
