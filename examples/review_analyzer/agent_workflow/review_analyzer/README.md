# Product Review Analyzer

A context engineering showcase: 6 actions, 3 vendors, parallel consensus scoring, pre-check quality gates, and progressive context disclosure — all declared in YAML.

This example demonstrates why Agent Actions is a **context engineering framework**, not a workflow automation tool. Every action gets its own model, its own context window, its own schema, and its own pre-check gate.

## Workflow Diagram

```
                    ┌──────────────────────────┐
                    │     extract_claims        │
                    │   (Groq — llama-3.3-70b)  │  ← Cheap model for extraction
                    │                          │     Drops star_rating to avoid bias
                    └────────────┬─────────────┘
                                 │
                    ┌────────────┴─────────────┐
                    │     score_quality         │
                    │  (OpenAI — gpt-4o-mini)   │  ← 3 independent parallel scorers
                    │    [versions: 1, 2, 3]    │     Each sees claims + rubric
                    │    scorer can't see others │     but NOT each other's scores
                    └────────────┬─────────────┘
                                 │
                    ┌────────────┴─────────────┐
                    │    aggregate_scores       │
                    │        (Tool)             │  ← Deterministic weighted consensus
                    │   version_consumption:    │     No LLM — math doesn't hallucinate
                    │     pattern: merge        │
                    └────────────┬─────────────┘
                                 │
                    ┌────────────┴─────────────┐
                    │     guard: score >= 6     │  ← Pre-check gate
                    │   Low quality? SKIP.      │     LLM never fires for junk reviews
                    │   No tokens burned.       │     Cost control at the record level
                    └──────┬───────────┬───────┘
                           │           │
              ┌────────────┴──┐  ┌─────┴──────────────┐
              │  generate_    │  │  extract_product_   │  ← Parallel branches
              │  response     │  │  insights           │     Independent dependencies
              │ (Anthropic —  │  │ (OpenAI —           │
              │  claude-sonnet│  │  gpt-4o-mini)       │
              │  )            │  │                     │
              └───────┬───────┘  └─────────┬───────────┘
                      │                    │
                    ┌─┴────────────────────┴──┐
                    │    format_output         │  ← Fan-in from both branches
                    │       (Tool)             │     Packages final structure
                    └─────────────────────────┘
```

## What This Example Demonstrates

Each action showcases a specific Agent Actions capability that you can't replicate in n8n, Make, or Zapier:

| Action | Pattern | What It Shows |
|---|---|---|
| `extract_claims` | Multi-vendor, context drop | Groq (cheap) for extraction. Drops `star_rating` so scoring isn't anchored by the user's number. Passthrough carries `review_id` at zero tokens. |
| `score_quality` | Parallel voting, context isolation | 3 scorers run independently. Each sees claims + rubric but NEVER each other's scores. Two lines of YAML = 3 parallel LLM calls. |
| `aggregate_scores` | Version merge, deterministic tool | Fan-in merges 3 parallel outputs. No LLM — weighted consensus computed in Python. |
| `generate_response` | Guard, multi-vendor, progressive disclosure | Guard blocks LLM for score < 6. Uses Anthropic Claude (best reasoning). Sees review + score but NOT individual scorer reasoning. |
| `extract_product_insights` | Parallel branch, seed data | Runs alongside `generate_response`. Uses rubric categories from seed data to classify feedback. |
| `format_output` | Fan-in, deterministic tool | Packages both parallel branches into final output. |

## Context Flow (What Each Step Sees)

This is the key insight. In n8n, every node sees everything. In Agent Actions:

```
extract_claims sees:
  ✅ review_text, review_title, product_name, product_category
  ❌ star_rating (dropped — avoids anchoring bias)
  ❌ verified_purchase (dropped — irrelevant to extraction)
  → Passes through: review_id, reviewer_name, review_date (zero tokens)

score_quality sees:
  ✅ extracted claims, product aspects, sentiment signals, review_text, rubric
  ❌ star_rating (still excluded)
  ❌ review_id, reviewer_name (irrelevant to scoring)
  ❌ other scorers' outputs (context isolation for independent judgment)

generate_response sees:
  ✅ review_text, review_title, claims, aspects, sentiment, consensus_score
  ✅ aggregate strengths and weaknesses
  ❌ individual scorer reasoning (clean context = better output)
  → Passes through: review_id, reviewer_name, product_name (zero tokens)
```

Every field excluded is **tokens saved** and **noise removed**. Every passthrough field is **metadata preserved** without LLM cost.

## Data

### Included: Synthetic Reviews (15 records)

The included `staging/reviews.json` contains 15 purpose-built product reviews designed to exercise every pipeline pattern:

| Review | Product | Rating | Why It's Interesting |
|---|---|---|---|
| R001 | CloudWalk Running Shoes | 4★ | Detailed, balanced — high quality, passes guard |
| R002 | BrewMaster Coffee Maker | 1★ | Strong negative with specifics — tests empathetic response |
| R003 | ZenDesk Standing Desk | 5★ | Rich detail, long usage — should score highest |
| R004 | AuraSound Earbuds | 3★ | Mixed: good hardware, bad software — tests nuanced analysis |
| R005 | GreenGrow Herb Garden | 5★ | Specific claims with timeframes — high authenticity |
| R006 | FitTrack Smartwatch | 2★ | Informal tone, unverified — tests lower scoring |
| R007 | NovaCool Portable AC | 4★ | Quantitative claims (92F→74F, $30/month) — high specificity |
| R008 | PageTurn E-Reader | 5★ | Comparison to competitor (Kindle) — tests claim extraction |
| R009 | ChefPro Instant Pot | 4★ | Identifies design flaw (steam valve) — tests product insights |
| R010 | LumiGlow Smart Bulbs | 3★ | Reliability issue pattern — tests feedback categorization |
| R011 | TrailBlazer Backpack | 5★ | Extreme use case (Patagonia trek) — high credibility |
| R012 | BrewMaster Coffee Maker | 1★ | ALL CAPS, emotional — should score lower on specificity |
| R013 | ErgoFlex Office Chair | 4★ | Assembly frustration but product praise — tests mixed handling |
| R014 | SonicClean Robot Vacuum | 3★ | Good hardware, bad software pattern (like R004) |
| R015 | CloudWalk Running Shoes | 5★ | **Fake review** — generic superlatives, unverified, bot-like name. Should be caught by authenticity scoring and filtered by guard. |

### Alternative: Open-Source Datasets

You can replace the synthetic data with real-world datasets:

**Small (ready to use):**
- [Product Review Sentiment 40](https://huggingface.co/datasets/elvanalabs/product-review-sentiment-40) — 40 records, JSON, review text + sentiment label. Simple but only 2 fields — you'd need to add product metadata.

**Medium (sample and reshape):**
- [Amazon Reviews 2023](https://huggingface.co/datasets/McAuley-Lab/Amazon-Reviews-2023) — Millions of real reviews with ratings, text, helpfulness votes, and product metadata. Sample 50-100 records from a single category (e.g., Electronics) and reshape to match the staging schema.
- [Amazon Beauty Reviews](https://huggingface.co/datasets/jhan21/amazon-beauty-reviews-dataset) — ~700K reviews up to 2023 in a single product category.

**Different domains (same workflow patterns):**
- [Customer Support Tickets](https://huggingface.co/datasets/Tobi-Bueck/customer-support-tickets) — Swap review analysis for ticket triage. Same patterns: extract → score → filter → respond.
- [Resume Screening Dataset](https://huggingface.co/datasets/AzharAli05/Resume-Screening-Dataset) — Application evaluation with the same parallel voting and guard patterns.
- [AI Resume Screening 2025](https://www.kaggle.com/datasets/mdtalhask/ai-powered-resume-screening-dataset-2025) — Includes role, skills, experience fields.

To use any of these, reshape records to match the staging schema:

```json
{
  "review_id": "...",
  "product_name": "...",
  "product_category": "...",
  "reviewer_name": "...",
  "review_date": "YYYY-MM-DD",
  "star_rating": 1-5,
  "review_title": "...",
  "review_text": "...",
  "verified_purchase": true/false
}
```

## Running the Workflow

```bash
# Navigate to the example
cd examples/review_analyzer

# Set up API keys (uses 3 vendors)
cp .env.example .env
# Edit .env with your keys: OPENAI_API_KEY, ANTHROPIC_API_KEY, GROQ_API_KEY

# Analyze the workflow schema (no API calls)
agac schema -a review_analyzer

# Run the workflow
agac run -a review_analyzer

# Or run in batch mode for 50% cost savings
agac run -a review_analyzer  # run_mode: batch is already set in defaults
```

### Single-Vendor Mode

Don't have 3 API keys? Change the workflow to use one vendor:

```yaml
# In agent_config/review_analyzer.yml, remove vendor overrides:
# - Delete model_vendor/model_name/api_key from extract_claims
# - Delete model_vendor/model_name/api_key from generate_response
# The workflow defaults (openai/gpt-4o-mini) will apply everywhere
```

## Output

The `format_output` tool produces one record per review:

```json
{
  "review_id": "R003",
  "product_name": "ZenDesk Standing Desk",
  "product_category": "Office Furniture",
  "reviewer_name": "Priya K.",
  "review_date": "2024-10-22",
  "analysis": {
    "quality_score": 8.7,
    "is_split_decision": false,
    "claims_extracted": 8,
    "aspects_covered": ["motor noise", "transition speed", "cable management", "assembly", "durability"],
    "sentiment": "positive",
    "red_flags": []
  },
  "merchant_response": {
    "response_text": "Priya, hearing that the desk has held up after 3 months of daily use is exactly the feedback we love — especially the detail about the cable management tray. You're right that the preset programming could be more intuitive; we're redesigning the control panel UI for the next revision. Thanks for the thorough review.",
    "response_tone": "grateful"
  },
  "product_insights": {
    "feedback_items": [
      {
        "category": "Ease of Use / Setup",
        "issue": "Control panel preset programming is unintuitive",
        "severity": "minor",
        "verbatim_evidence": "took me a few days to figure out the preset programming"
      }
    ],
    "improvement_priority": "Ease of Use / Setup",
    "positive_differentiators": ["whisper-quiet motor", "8-second transitions", "bamboo top durability"]
  }
}
```

Reviews scoring below 6 (like R015, the fake review) produce:

```json
{
  "review_id": "R015",
  "product_name": "CloudWalk Pro Running Shoes",
  "analysis": {
    "quality_score": 2.1,
    "is_split_decision": false,
    "claims_extracted": 0,
    "aspects_covered": [],
    "sentiment": "positive",
    "red_flags": ["Generic superlatives", "No specific claims", "Bot-like reviewer name", "Unverified purchase"]
  },
  "merchant_response": null,
  "product_insights": null
}
```

The guard prevented `generate_response` and `extract_product_insights` from firing. No tokens burned on a fake review.

## Seed Data

`seed_data/evaluation_rubric.json` contains:

- **Scoring criteria** with weights: helpfulness (0.35), specificity (0.30), authenticity (0.35)
- **Quality threshold**: 6 (used by guards)
- **Product feedback categories**: 8 categories for insight classification

Change the rubric to change what "quality" means — the workflow structure stays the same.

## Tools

| Tool | Purpose | Input | Output |
|---|---|---|---|
| `aggregate_quality_scores` | Weighted consensus from 3 parallel scorers | Versioned `score_quality_1/2/3` outputs | Consensus score, spread, strengths, weaknesses, red flags |
| `format_analysis_output` | Package final output from parallel branches | All upstream outputs | Structured analysis record |

## Customization

| Change | What to Edit |
|---|---|
| Quality threshold | `seed_data/evaluation_rubric.json` → `quality_threshold` |
| Scoring weights | `seed_data/evaluation_rubric.json` → `scoring_criteria.*.weight` |
| Number of scorers | `agent_config/review_analyzer.yml` → `score_quality.versions.range` |
| Guard condition | `agent_config/review_analyzer.yml` → `generate_response.guard.condition` |
| Response style | `prompt_store/review_analyzer.md` → `Generate_Response` prompt |
| Feedback categories | `seed_data/evaluation_rubric.json` → `product_feedback_categories` |
| Model for any step | `agent_config/review_analyzer.yml` → action-level `model_vendor`/`model_name` |
| Switch to single vendor | Remove per-action vendor overrides; workflow defaults apply |

## File Structure

```
review_analyzer/
├── .env.example                              # API key template (3 vendors)
├── agent_actions.yml                         # Project config
├── agent_workflow/review_analyzer/
│   ├── README.md                             # This file
│   ├── agent_config/
│   │   └── review_analyzer.yml               # Workflow definition (6 actions)
│   ├── agent_io/staging/
│   │   └── reviews.json                      # 15 synthetic product reviews
│   └── seed_data/
│       └── evaluation_rubric.json            # Scoring criteria + feedback categories
├── prompt_store/
│   └── review_analyzer.md                    # 4 LLM prompts
├── schema/review_analyzer/
│   ├── extract_claims.yml                    # Step 1 output schema
│   ├── score_quality.yml                     # Step 2 output schema
│   ├── aggregate_scores.yml                  # Step 3 output schema
│   ├── generate_response.yml                 # Step 4 output schema
│   ├── extract_product_insights.yml          # Step 5 output schema
│   └── format_output.yml                     # Step 6 output schema
└── tools/review_analyzer/
    ├── aggregate_quality_scores.py           # Weighted consensus voting
    └── format_analysis_output.py             # Final output packaging
```
