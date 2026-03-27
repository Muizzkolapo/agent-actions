# Translation Quality Pipeline

An iterative refinement showcase: 6 actions demonstrating parallel translation strategies, deterministic selection, back-translation validation, and quality scoring — all declared in YAML.

This example shows how Agent Actions handles **iterative refinement** as a first-class pattern. Three independent translators produce competing versions, a deterministic tool picks the best, a back-translator validates meaning preservation without seeing the original, and a quality judge scores the round-trip fidelity.

## Workflow Diagram

```
                    +---------------------------+
                    |     extract_context        |
                    |   (LLM — gpt-4o-mini)      |  <- Identify domain, tone, key terms
                    |                           |     Glossary lookup from seed_data
                    +-----------+---------------+
                                |
              +-----------------+-----------------+
              |                 |                 |
     +--------+------+ +-------+-------+ +-------+---------+
     | translate (1)  | | translate (2) | | translate (3)   |
     | LITERAL        | | IDIOMATIC     | | DOMAIN-ADAPTED  |
     | (LLM parallel) | | (LLM parallel)| | (LLM parallel)  |
     +--------+------+ +-------+-------+ +-------+---------+
              |                 |                 |
              +-----------------+-----------------+
                                |
                    +-----------+---------------+
                    |  select_best_translation   |
                    |        (Tool)              |  <- Deterministic scoring
                    |  version_consumption:      |     Completeness + confidence
                    |    pattern: merge          |
                    +-----------+---------------+
                                |
                    +-----------+---------------+
                    |     back_translate          |
                    |   (LLM — gpt-4o-mini)      |  <- Reverse translate to source
                    |                           |     Does NOT see original text
                    +-----------+---------------+
                                |
                    +-----------+---------------+
                    |    validate_quality         |
                    |   (LLM — gpt-4o-mini)      |  <- Compare original vs back-translation
                    |                           |     Score meaning preservation
                    +-----------+---------------+
                                |
                    +-----------+---------------+
                    |     format_output           |
                    |        (Tool)              |  <- Package final result
                    |                           |     with quality metadata
                    +---------------------------+
```

## What This Example Demonstrates

Each action showcases a specific Agent Actions capability:

| Action | Pattern | What It Shows |
|---|---|---|
| `extract_context` | Seed data injection, context preparation | Analyzes text BEFORE translation. Glossary lookup steers all three translators. |
| `translate` | Parallel versioned strategies, context isolation | 3 translators with different strategies run independently. `{% if version.first %}` controls strategy differentiation. Each sees context but NEVER other translations. |
| `select_best_translation` | Version merge, deterministic tool | Fan-in merges 3 parallel outputs. Scores by completeness and confidence — no LLM needed. |
| `back_translate` | Context drop (critical), iterative refinement | Translates back WITHOUT seeing the original. `drop: source.text` prevents cheating. This is the validation mechanism. |
| `validate_quality` | Full context comparison, quality scoring | The "judge" — sees original, translation, and back-translation. Detects meaning drift, omissions, tone shifts. |
| `format_output` | Fan-in, deterministic packaging | Packages everything into a structured output with quality metadata. |

## Pattern: Iterative Refinement + Back-Translation

The core insight: **you can validate a translation without knowing the target language**.

```
Original (EN) ──> Translate ──> Translation (ES)
                                       |
                                       v
                              Back-Translate ──> Back-Translation (EN)
                                                        |
                                                        v
                              Compare: Original (EN) vs Back-Translation (EN)
                                                        |
                                                        v
                              Drift? Omissions? Distortions? ──> Quality Score
```

If the back-translation closely matches the original, meaning was preserved through the round-trip. Divergences reveal translation problems:

- **Omissions**: Something in the original didn't survive
- **Additions**: The translator added meaning not in the original
- **Distortions**: Meaning changed (the most dangerous drift)
- **Softening**: Intensity or urgency was reduced

The parallel strategies (literal, idiomatic, domain-adapted) ensure different trade-offs are explored. The deterministic selector picks the best before validation begins.

## Context Flow (What Each Step Sees)

```
extract_context sees:
  OK source.text, source.target_language, source.domain
  OK seed_data.glossary (domain terminology)
  -> Passes through: text_id, source_language, target_language, domain, text

translate sees (each version independently):
  OK source.text, source.target_language, source.domain
  OK extract_context.detected_tone, key_terms, cultural_references, challenges
  OK seed_data.glossary (for domain-adapted strategy)
  NO other translators' outputs (context isolation)
  -> Passes through: text_id, source_language

select_best_translation sees:
  OK translate_1, translate_2, translate_3 (all three via version merge)
  OK source.text (for sentence counting)
  -> Passes through: extract_context.*, text_id, source_language, target_language, domain

back_translate sees:
  OK select_best_translation.best_translation (the translation to reverse)
  OK source.source_language, source.target_language, source.domain
  NO source.text (CRITICAL: hidden to prevent cheating)
  -> Passes through: best_translation, selected_strategy, text_id

validate_quality sees:
  OK source.text (original for comparison)
  OK select_best_translation.best_translation (forward translation)
  OK back_translate.back_translated_text (round-trip result)
  OK extract_context.key_terms, cultural_references, detected_tone
  -> Passes through: everything needed for format_output
```

The key design decision: `back_translate` CANNOT see the original text. This forces it to work purely from the translation, making the round-trip a genuine test of meaning preservation.

## Data

### Included: 8 Text Passages

The included `staging/texts.json` contains 8 purpose-built texts spanning 5 domains and 4 target languages:

| ID | Domain | Target | Why It's Interesting |
|---|---|---|---|
| T001 | Legal | es | Force majeure clause — domain terms with specific legal translations |
| T002 | Medical | fr | Patient report with contraindications — mistranslation could be dangerous |
| T003 | Technical | de | Cloud-native infrastructure — mix of translatable and preserve-as-is terms |
| T004 | Marketing | ja | Skincare copy with idioms — "million bucks", "no strings attached" |
| T005 | Casual | es | Party invitation with slang — "gonna be a blast", "scorching" |
| T006 | Legal | fr | Irrevocable license grant — dense legal phrasing |
| T007 | Marketing | de | Productivity suite with multiple idioms — "bull by the horns", "bee's knees", "ducks in a row" |
| T008 | Medical | ja | Emergency protocol — precision-critical dosing and procedures |

The mix tests: domain terminology accuracy (legal/medical), idiom adaptation (marketing/casual), technical term preservation (technical), and cross-script translation (Japanese).

### Domain Glossary

`seed_data/domain_glossary.json` provides preferred translations organized by domain and language pair:

- **Legal**: force majeure, indemnify, hereinafter, injunctive relief, etc.
- **Medical**: contraindicated, prognosis, comorbidity, anaphylactic reaction, etc.
- **Marketing**: style notes per language pair, term preferences (free trial, no strings attached)
- **Technical**: preserve-as-is list (Kubernetes, CI/CD, API), translated terms per language

## Running the Workflow

```bash
# Navigate to the example
cd examples/translation_quality

# Set up API key
cp .env.example .env
# Edit .env with your OPENAI_API_KEY

# Analyze the workflow schema (no API calls)
agac schema -a translation_quality

# Run the workflow
agac run -a translation_quality
```

## Output

The `format_output` tool produces one record per text:

```json
{
  "text_id": "T001",
  "source_language": "en",
  "target_language": "es",
  "domain": "legal",
  "translation": {
    "text": "El inquilino indemnizara y eximira de responsabilidad al propietario...",
    "strategy": "domain_adapted",
    "confidence": 8
  },
  "quality": {
    "score": 8.5,
    "meaning_preserved": true,
    "tone_preserved": true,
    "drift_count": 1,
    "critical_issues": 0
  },
  "back_translation": "The tenant shall indemnify and hold the landlord harmless...",
  "original_text": "The tenant shall indemnify and hold harmless the landlord...",
  "summary": "Strong translation with near-perfect meaning preservation. Minor word order difference in back-translation ('hold the landlord harmless' vs 'hold harmless the landlord') is stylistic, not semantic. All legal terms correctly rendered using domain-standard Spanish equivalents."
}
```

A text with drift issues might produce:

```json
{
  "text_id": "T007",
  "source_language": "en",
  "target_language": "de",
  "domain": "marketing",
  "translation": {
    "text": "Bereit, den Stier bei den Hornern zu packen?...",
    "strategy": "idiomatic",
    "confidence": 7
  },
  "quality": {
    "score": 6.5,
    "meaning_preserved": true,
    "tone_preserved": false,
    "drift_count": 3,
    "critical_issues": 0
  },
  "back_translation": "Ready to grab the bull by the horns?...",
  "original_text": "Ready to take the bull by the horns?...",
  "summary": "Core meaning preserved but tone shifted from playful casual to slightly formal German. Three idioms required adaptation: 'bee's knees' and 'ducks in a row' lost some of their colloquial energy. No critical drift — all factual content intact."
}
```

## Tools

| Tool | Purpose | Input | Output |
|---|---|---|---|
| `compare_translations` | Score and select best from 3 parallel strategies | Versioned `translate_1/2/3` outputs | Best translation, scores, reasoning |
| `format_translation_output` | Package final output with quality metadata | All upstream outputs | Structured translation record |

## Customization

| Change | What to Edit |
|---|---|
| Number of strategies | `agent_config/translation_quality.yml` -> `translate.versions.range` |
| Translation strategies | `prompt_store/translation_quality.md` -> `Translate` prompt version blocks |
| Glossary terms | `seed_data/domain_glossary.json` |
| Quality scoring weights | `tools/translation_quality/compare_translations.py` -> `_score_translation` |
| Add more languages | `staging/texts.json` -> add entries with new `target_language` values |
| Add quality guard | `agent_config/translation_quality.yml` -> add `guard` to `format_output` |
| Switch model | `agent_config/translation_quality.yml` -> action-level `model_name` override |

## File Structure

```
translation_quality/
|-- .env.example                                # API key template
|-- agent_actions.yml                           # Project config
|-- agent_workflow/translation_quality/
|   |-- README.md                               # This file
|   |-- agent_config/
|   |   +-- translation_quality.yml             # Workflow definition (6 actions)
|   |-- agent_io/staging/
|   |   +-- texts.json                          # 8 text passages across 5 domains
|   +-- seed_data/
|       +-- domain_glossary.json                # Domain terminology + style notes
|-- prompt_store/
|   +-- translation_quality.md                  # 4 LLM prompts (with version templating)
|-- schema/translation_quality/
|   |-- extract_context.yml                     # Step 1 output schema
|   |-- translate.yml                           # Step 2 output schema
|   |-- select_best_translation.yml             # Step 3 output schema
|   |-- back_translate.yml                      # Step 4 output schema
|   |-- validate_quality.yml                    # Step 5 output schema
|   +-- format_output.yml                       # Step 6 output schema
+-- tools/translation_quality/
    |-- compare_translations.py                 # Strategy comparison + selection
    +-- format_translation_output.py            # Final output packaging
```
