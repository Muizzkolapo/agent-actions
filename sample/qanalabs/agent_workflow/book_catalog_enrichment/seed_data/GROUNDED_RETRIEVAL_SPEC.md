# Grounded Retrieval Pattern - Design Spec

> **Purpose**: Prevent LLM hallucination by grounding recommendations in real catalog data.
> **Status**: Implemented (JSON backend)
> **Future**: Vector DB (ChromaDB/Pinecone) or SQL (PostgreSQL)

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  WORKFLOW (unchanged regardless of backend)                  │
│                                                             │
│  validate_description                                       │
│         │                                                   │
│         ▼                                                   │
│  ┌──────────────────┐                                       │
│  │ generate_search_ │  LLM generates search parameters      │
│  │ criteria         │  Output: {query_text, genres,         │
│  └────────┬─────────┘         keywords, exclude_isbn}       │
│           │                                                 │
│           ▼                                                 │
│  ┌──────────────────┐                                       │
│  │ retrieve_        │  TOOL: Queries catalog                │
│  │ candidates       │  Output: {matching_books: [...]}      │
│  └────────┬─────────┘  ← ABSTRACTION LAYER                  │
│           │                                                 │
│           ▼                                                 │
│  ┌──────────────────┐                                       │
│  │ generate_        │  LLM ranks REAL books only            │
│  │ recommendations  │  Output: {similar_books: [...]}       │
│  └──────────────────┘                                       │
└─────────────────────────────────────────────────────────────┘
                        │
       ┌────────────────┼────────────────┐
       │                │                │
  ┌────▼────┐     ┌─────▼─────┐    ┌────▼────┐
  │  JSON   │     │  Vector   │    │   SQL   │
  │ (current)│     │ (future) │    │ (future)│
  └─────────┘     └───────────┘    └─────────┘
```

---

## Contract: Tool Input/Output

### Input Schema (`SearchBookCatalogInput`)

```python
class SearchBookCatalogInput(TypedDict, total=False):
    # Search criteria from LLM
    query_text: str           # Natural language query
    genres: List[str]         # BISAC codes to filter
    keywords: List[str]       # Keywords for matching
    target_audience: str      # Reader profile
    exclude_isbn: str         # Current book to exclude

    # Passthrough fields (preserved through pipeline)
    isbn: str
    title: str
    authors: List[str]
    marketing_description: str
    bisac_codes: List[str]
```

### Output Schema (`SearchBookCatalogOutput`)

```python
class SearchBookCatalogOutput(TypedDict, total=False):
    matching_books: List[dict]    # Candidates for LLM to rank
    search_metadata: dict         # Search statistics
```

### `matching_books` Item Structure

```json
{
  "isbn": "978-0-13-468599-1",
  "title": "Clean Code",
  "authors": ["Robert C. Martin"],
  "genres": ["COM051000", "COM051230"],
  "description": "A guide to writing clean code...",
  "relevance_score": 15.0
}
```

### `search_metadata` Structure

```json
{
  "total_in_catalog": 30,
  "candidates_found": 12,
  "returned": 12,
  "search_method": "json_file",
  "genres_searched": ["COM051000"],
  "keywords_searched": ["programming", "best practices"]
}
```

---

## Implementation: JSON Backend (Current)

**File**: `tools/book-catalog-enrichment/search_book_catalog.py`

**Algorithm**:
1. Load catalog from `seed_data/book_catalog.json`
2. Filter out `exclude_isbn`
3. Score each book by genre + keyword match
4. Sort by relevance score descending
5. Return top 20 candidates

**Scoring**:
- Exact genre match: +10 points
- Genre prefix match: +5 points
- Exact keyword match: +3 points
- Keyword in description: +1 point

---

## Implementation: Vector DB (Future)

**Candidate**: ChromaDB, Pinecone, Qdrant, Weaviate

**Changes Required**:
1. Replace `_load_catalog()` with vector DB client
2. Replace `_calculate_relevance_score()` with embedding similarity
3. Add embedding generation for `query_text`

**Pseudocode**:

```python
import chromadb

def search_book_catalog(data: dict) -> dict:
    client = chromadb.Client()
    collection = client.get_collection("books")

    # Vector search
    results = collection.query(
        query_texts=[data.get('query_text', '')],
        n_results=20,
        where={
            "genre": {"$in": data.get('genres', [])},
            "isbn": {"$ne": data.get('exclude_isbn', '')}
        }
    )

    # Transform to contract format
    matching_books = [
        {
            "isbn": meta["isbn"],
            "title": meta["title"],
            "authors": meta["authors"],
            "genres": meta["genres"],
            "description": doc,
            "relevance_score": 1 - distance  # Convert distance to score
        }
        for doc, meta, distance in zip(
            results['documents'][0],
            results['metadatas'][0],
            results['distances'][0]
        )
    ]

    return {
        "matching_books": matching_books,
        "search_metadata": {
            "search_method": "vector_chromadb",
            "total_in_catalog": collection.count(),
            ...
        }
    }
```

**Setup Script** (one-time):

```python
# scripts/index_catalog_to_chromadb.py
import chromadb
import json

client = chromadb.Client()
collection = client.create_collection("books")

with open("seed_data/book_catalog.json") as f:
    catalog = json.load(f)

collection.add(
    documents=[b["description"] for b in catalog],
    metadatas=[{k: v for k, v in b.items() if k != "description"} for b in catalog],
    ids=[b["isbn"] for b in catalog]
)
```

---

## Implementation: SQL (Future)

**Candidate**: PostgreSQL with pg_trgm for fuzzy matching

**Changes Required**:
1. Replace file load with SQL connection
2. Replace scoring with SQL query
3. Add full-text search or trigram similarity

**Pseudocode**:

```python
import psycopg2

def search_book_catalog(data: dict) -> dict:
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    cur = conn.cursor()

    # SQL with genre filter and keyword search
    cur.execute("""
        SELECT isbn, title, authors, genres, description,
               similarity(description, %s) as relevance_score
        FROM books
        WHERE isbn != %s
          AND genres && %s::text[]
        ORDER BY relevance_score DESC
        LIMIT 20
    """, (
        data.get('query_text', ''),
        data.get('exclude_isbn', ''),
        data.get('genres', [])
    ))

    matching_books = [
        {
            "isbn": row[0],
            "title": row[1],
            "authors": row[2],
            "genres": row[3],
            "description": row[4],
            "relevance_score": row[5]
        }
        for row in cur.fetchall()
    ]

    return {
        "matching_books": matching_books,
        "search_metadata": {"search_method": "sql_postgres", ...}
    }
```

---

## Files Reference

| Component | Path |
|-----------|------|
| Tool Implementation | `tools/book-catalog-enrichment/search_book_catalog.py` |
| Input Schema | `schema/search_criteria.yml` |
| Catalog Data | `agent_workflow/.../seed_data/book_catalog.json` |
| Search Prompt | `prompt_store/book_catalog_enrichment.md` → `Generate_Search_Criteria` |
| Rank Prompt | `prompt_store/book_catalog_enrichment.md` → `Rank_Recommendations` |
| Workflow Config | `agent_workflow/.../agent_config/book_catalog_enrichment.yml` |

---

## Key Design Decisions

1. **Tool as Abstraction Layer**: Workflow YAML never changes when backend changes
2. **Top 20 Candidates**: Balance between giving LLM options and token efficiency
3. **Exclude Self**: Always filter out current book from recommendations
4. **Relevance Score**: Included in output for debugging/ranking transparency
5. **Search Metadata**: Track search method for observability

---

## Testing Checklist

- [ ] JSON backend returns results for valid genres
- [ ] Empty catalog returns empty `matching_books`
- [ ] `exclude_isbn` properly filters current book
- [ ] Score calculation prioritizes genre over keywords
- [ ] LLM only recommends books from `matching_books` (no hallucination)
- [ ] Vector backend produces same output contract
- [ ] SQL backend produces same output contract
