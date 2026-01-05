| Pattern             | Description                                             | Example Use Case                                                                              |
  |---------------------|---------------------------------------------------------|-----------------------------------------------------------------------------------------------|
  | Diamond/Fan-in      | Split → parallel branches → merge                       | Current book enrichment: validate → [seo, recs, level] → score                                |
  | Multi-enrichment    | Single source enriched by multiple specialized actions  | Document processing: [extract_entities, extract_sentiment, extract_topics] → unified_analysis |
  | Parallel Validation | Multiple validators run independently, results combined | [schema_check, content_check, security_check] → approval_decision                             |
  | Ensemble/Voting     | Multiple LLMs/approaches, consensus merge               | [gpt4_answer, claude_answer, gemini_answer] → best_answer                                     |
  | Map-Reduce          | Fan-out to parallel workers, reduce to aggregation      | chunk_document → [process_chunk_1..N] → aggregate_results                                     |
  | Conditional Merge   | Only merge branches that ran (with guards)              | [fast_path, slow_path] → combine (if both ran)                                                |
`