# Customer Issues → FAQ Generator

Transforms batches of support tickets into publishable FAQ entries. Extracts issues, classifies topics with parallel consensus, clusters related tickets, gates on frequency, deduplicates against existing FAQs, and generates structured Q&A pairs.

**Data source:** 20 real English support tickets from [Tobi-Bueck/customer-support-tickets](https://huggingface.co/datasets/Tobi-Bueck/customer-support-tickets) (CC-BY-NC-4.0), sampled across 8 support queues.

## Workflow Diagram

```
                    ┌──────────────────────────┐
                    │      extract_issue        │
                    │    (OpenAI gpt-4o-mini)   │  ← Per-record: distill ticket
                    │     granularity: Record   │     into problem + resolution
                    └────────────┬─────────────┘
                                 │
                    ┌────────────┴─────────────┐
                    │      classify_topic       │
                    │    (OpenAI gpt-4o-mini)   │  ← 3 independent voters
                    │    [versions: 1, 2, 3]    │     Each sees issue, not others
                    └────────────┬─────────────┘
                                 │
                    ┌────────────┴─────────────┐
                    │  aggregate_classification │
                    │         (Tool)            │  ← Majority-rule consensus
                    │   version_consumption:    │
                    │     pattern: merge        │
                    └────────────┬─────────────┘
                                 │
                    ┌────────────┴─────────────┐
                    │    cluster_by_topic       │
                    │         (Tool)            │  ← FILE granularity: sees ALL
                    │   granularity: File       │     records, groups by topic,
                    │                          │     counts frequency
                    └────────────┬─────────────┘
                                 │
                    ┌────────────┴─────────────┐
                    │  guard: cluster_size >= 3 │  ← Only FAQ-worthy clusters
                    │  Single-ticket issues?    │     No tokens on noise
                    │  SKIP.                    │
                    └────────────┬─────────────┘
                                 │
                    ┌────────────┴─────────────┐
                    │    generate_faq_draft     │
                    │  (Anthropic claude-sonnet)│  ← Best writing for
                    │                          │     customer-facing output
                    └────────────┬─────────────┘
                                 │
                    ┌────────────┴─────────────┐
                    │    deduplicate_faqs       │
                    │    (OpenAI gpt-4o-mini)   │  ← Checks against seed_data
                    │                          │     existing published FAQs
                    └────────────┬─────────────┘
                                 │
                    ┌────────────┴─────────────┐
                    │  guard: status != "dup"   │  ← Skip if already published
                    └────────────┬─────────────┘
                                 │
                    ┌────────────┴─────────────┐
                    │    format_faq_output      │
                    │         (Tool)            │  ← Package for publication
                    └──────────────────────────┘
```

## What This Example Demonstrates

This example showcases patterns the review_analyzer doesn't:

| Pattern | How It's Used Here | Why It Matters |
|---|---|---|
| **Record → File granularity shift** | `extract_issue` runs per-record, `cluster_by_topic` sees ALL records at once | Some operations need the full picture. Granularity controls this declaratively. |
| **Frequency-based guard** | `guard: cluster_size >= 3` | Not just quality gating — quantity gating. One-off tickets aren't FAQ material. |
| **Seed data as dedup reference** | Existing FAQs loaded so the pipeline doesn't regenerate published content | Seed data isn't just context — it's institutional knowledge. |
| **LLM for dedup** (not just tools) | `deduplicate_faqs` uses an LLM to judge semantic overlap, not string matching | Real dedup needs understanding, not `==` |
| **Two guards in one pipeline** | `cluster_size >= 3` then `status != "duplicate"` | Progressive filtering: frequency first, then novelty |
| **Open-source real data** | 20 actual support tickets from HuggingFace | Not synthetic — real messy data that needs real processing |

## Context Flow

```
extract_issue sees:
  ✅ subject, body, answer, type, tags
  ❌ priority (dropped — irrelevant to FAQ content)
  → Passes through: ticket_id, queue, tags

classify_topic (x3) sees:
  ✅ core_problem, resolution_summary, product_area, faq_categories (from seed)
  ❌ raw ticket body (already distilled)
  ❌ other voters' classifications (context isolation)

cluster_by_topic sees:
  ✅ ALL records at once (File granularity)
  ✅ consensus_category, extract_issue fields, ticket_id

generate_faq_draft sees:
  ✅ cluster_topic, cluster_size, representative problems + resolutions
  ✅ faq_guidelines from seed data
  ❌ individual ticket bodies
  ❌ classification reasoning

deduplicate_faqs sees:
  ✅ generated faq_question, faq_answer, faq_category
  ✅ existing published FAQs from seed data
  ❌ cluster details, ticket IDs
```

## Data

### Included: Real Support Tickets (20 records)

Sampled from [Tobi-Bueck/customer-support-tickets](https://huggingface.co/datasets/Tobi-Bueck/customer-support-tickets) on HuggingFace (61,800 English/German tickets, CC-BY-NC-4.0).

Distribution across queues:

| Queue | Tickets | Expected Behavior |
|---|---|---|
| Technical Support | 4 | Should cluster → generate FAQ |
| Billing and Payments | 3 | Should cluster → generate FAQ |
| Product Support | 3 | Should cluster → generate FAQ |
| IT Support | 3 | Should cluster → generate FAQ |
| Customer Service | 3 | Should cluster → generate FAQ |
| Returns and Exchanges | 2 | Below threshold → filtered by guard |
| Sales and Pre-Sales | 1 | Below threshold → filtered by guard |
| Service Outages | 1 | Below threshold → filtered by guard |

### Alternative Data Sources

**Same domain, different scale:**
- [Kaggle Customer Support Tickets](https://www.kaggle.com/datasets/suraj520/customer-support-ticket-dataset) — CC0, includes ticket description + resolution, satisfaction rating, priority. Different field names — reshape to match staging schema.
- [Bitext Customer Support LLM Dataset](https://huggingface.co/datasets/bitext/Bitext-customer-support-llm-chatbot-training-dataset) — 26K intent-tagged utterances. Good for higher volume testing.
- [IT Helpdesk Synthetic Tickets](https://huggingface.co/datasets/Console-AI/IT-helpdesk-synthetic-tickets) — Focused on IT support specifically.

**Different domain, same patterns:**
- Product reviews → FAQ about common complaints (use review_analyzer output as input)
- GitHub issues → FAQ about common bugs/setup problems
- Forum posts → FAQ from community questions

To use alternative data, reshape records to match:

```json
{
  "ticket_id": "T001",
  "subject": "Issue subject line",
  "body": "Customer's description of the problem...",
  "answer": "Support team's response/resolution...",
  "type": "Incident|Request|Problem|Change",
  "queue": "Technical Support",
  "priority": "high|medium|low",
  "tags": ["tag1", "tag2"]
}
```

## Running

```bash
cd examples/faq_generator

# Set up API keys
cp .env.example .env
# Edit .env: OPENAI_API_KEY, ANTHROPIC_API_KEY

# Analyze workflow (no API calls)
agac schema -a faq_generator

# Run
agac run -a faq_generator
```

### Single-Vendor Mode

Remove `model_vendor`/`model_name`/`api_key` from `generate_faq_draft` to use OpenAI for everything.

## Seed Data

`seed_data/existing_faqs.json` contains:

- **3 published FAQs** — password reset, payment methods, data export. The pipeline should detect these as already-covered topics.
- **8 FAQ categories** — the taxonomy classifiers must use
- **FAQ guidelines** — min cluster size, question style, answer length, tone

Modify existing FAQs to change what gets flagged as duplicate. Add categories to expand the taxonomy.

## File Structure

```
faq_generator/
├── .env.example
├── agent_actions.yml
├── agent_workflow/faq_generator/
│   ├── README.md
│   ├── agent_config/
│   │   └── faq_generator.yml                 # 7 actions
│   ├── agent_io/staging/
│   │   └── tickets.json                      # 20 real support tickets
│   └── seed_data/
│       └── existing_faqs.json                # Published FAQs + taxonomy
├── prompt_store/
│   └── faq_generator.md                      # 4 LLM prompts
├── schema/faq_generator/
│   ├── extract_issue.yml
│   ├── classify_topic.yml
│   ├── aggregate_classification.yml
│   ├── cluster_by_topic.yml
│   ├── generate_faq_draft.yml
│   ├── deduplicate_faqs.yml
│   └── format_faq_output.yml
└── tools/faq_generator/
    ├── aggregate_topic_votes.py              # Majority-rule voting
    ├── cluster_tickets_by_topic.py           # FILE granularity clustering
    └── format_faq_entry.py                   # Final output packaging
```

## Comparison with review_analyzer

| Aspect | review_analyzer | faq_generator |
|---|---|---|
| Granularity | Record only | Record → File shift |
| Guard logic | Quality threshold (score >= 6) | Frequency threshold (cluster >= 3) + novelty (not duplicate) |
| Seed data role | Scoring rubric | Deduplication reference + taxonomy + guidelines |
| Dedup approach | N/A | LLM semantic comparison against existing FAQs |
| Data source | Synthetic | Real open-source (HuggingFace) |
| Output | Per-review analysis | Aggregated FAQ entries from many tickets |
| Multi-vendor | 3 vendors | 2 vendors |
