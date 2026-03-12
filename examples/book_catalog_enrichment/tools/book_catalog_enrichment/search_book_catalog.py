"""Search book catalog for similar books.

This is an abstraction layer for catalog search.
Currently implements JSON file search.
Can be swapped to Vector DB (ChromaDB/Pinecone) or SQL without workflow changes.
"""

import json
import os
from typing import TypedDict

from agent_actions import udf_tool


class SearchBookCatalogInput(TypedDict, total=False):
    """Input schema for search_book_catalog.

    Source: node_6a_generate_search_criteria output
    Destination: node_6b_retrieve_candidates output
    """

    # Search criteria from LLM
    query_text: str
    genres: list[str]
    keywords: list[str]
    target_audience: str
    exclude_isbn: str

    # Passthrough fields from upstream
    isbn: str
    title: str
    authors: list[str]
    marketing_description: str
    bisac_codes: list[str]


class SearchMetadata(TypedDict, total=False):
    """Metadata about the search operation."""

    total_in_catalog: int
    candidates_found: int
    returned: int
    search_method: str
    genres_searched: list[str]
    keywords_searched: list[str]
    error: str


class MatchingBook(TypedDict, total=False):
    """A book matching the search criteria."""

    isbn: str
    title: str
    authors: list[str]
    genres: list[str]
    description: str
    relevance_score: float


class SearchBookCatalogOutput(TypedDict, total=False):
    """Output schema for search_book_catalog."""

    matching_books: list[MatchingBook]
    search_metadata: SearchMetadata


# Path to seed data catalog (relative to workflow)
CATALOG_PATH = os.path.join(
    os.path.dirname(__file__),
    "../../agent_workflow/book_catalog_enrichment/seed_data/book_catalog.json",
)


def _load_catalog() -> list[dict]:
    """Load book catalog from seed data."""
    # Normalize path
    catalog_path = os.path.normpath(CATALOG_PATH)

    if not os.path.exists(catalog_path):
        # Try alternate path resolution
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
        # Partial match on prefix (e.g., COM051 matches COM051000)
        elif any(bg.startswith(genre[:6]) for bg in book_genres if len(genre) >= 6):
            score += 5.0

    # Keyword matching
    for keyword in keywords:
        keyword_lower = keyword.lower()
        # Exact keyword match
        if keyword_lower in [k.lower() for k in book_keywords]:
            score += 3.0
        # Keyword in description
        elif keyword_lower in book_description:
            score += 1.0

    return score


@udf_tool()
def search_book_catalog(data: dict) -> dict:
    """Search catalog for similar books.

    This is the ABSTRACTION LAYER for catalog search.
    Current implementation: JSON file search with keyword/genre matching.
    Future: Vector DB (ChromaDB/Pinecone) or SQL database.

    The workflow YAML doesn't change when backend changes.

    Args:
        data: Search criteria from generate_search_criteria step

    Returns:
        matching_books: List of books from catalog (real data, not hallucinated)
        search_metadata: Search statistics
    """
    # Extract search criteria
    genres = data.get("genres", [])
    keywords = data.get("keywords", [])
    exclude_isbn = data.get("exclude_isbn", "") or data.get("isbn", "")

    # Load catalog
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

    # Score and rank books
    scored_books = []
    for book in catalog:
        # Exclude current book
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

    # Sort by relevance score (descending)
    scored_books.sort(key=lambda x: x["relevance_score"], reverse=True)

    # Return top 20 candidates for LLM to rank
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
