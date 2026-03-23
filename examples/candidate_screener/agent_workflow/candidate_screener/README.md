# Candidate Screener Workflow

Automated candidate screening system that parses resumes, runs three independent assessments in parallel, combines scores with configurable weights, and generates hire/no-hire recommendations.

## Overview

This workflow demonstrates the **Parallel Processing** pattern where multiple DIFFERENT assessments run independently on the same input, then fan-in to a combined score. Unlike an ensemble/voting pattern (where the same question is answered multiple times), each parallel branch here evaluates a completely distinct dimension of the candidate.

## Workflow Diagram

```
                    +-------------------------+
                    |      parse_resume       |
                    |         (LLM)           |
                    | Extract structured data |
                    +-----+-----+-----+------+
                          |     |     |
              +-----------+     |     +-----------+
              |                 |                 |
    +---------v-------+ +------v--------+ +------v---------+
    |  assess_skills  | |assess_experience| |assess_culture_ |
    |     (LLM)       | |    (LLM)       | |     fit (LLM)  |
    |                 | |                 | |                 |
    | Sees: skills,   | | Sees: roles,   | | Sees: achieve- |
    |  roles, role    | |  years, achieve-| |  ments, cover  |
    |  requirements   | |  ments, edu,   | |  letter, values|
    |                 | |  requirements  | |                 |
    | Does NOT see:   | | Does NOT see:  | | Does NOT see:  |
    |  experience or  | |  skills score  | |  skills or     |
    |  culture scores | |  or culture    | |  experience    |
    +---------+-------+ +------+---------+ +------+---------+
              |                |                  |
              +-------+--------+--------+---------+
                      |        FAN-IN   |
                      v                 v
              +-------+--------+--------+---------+
              |         combine_scores            |
              |            (Tool)                 |
              |  Weighted composite calculation   |
              |  skills*0.40 + exp*0.35 +         |
              |  culture*0.25                     |
              +----------------+------------------+
                               |
                     +---------v-----------+
                     | generate_recommend- |
                     |       ation         |
                     |      (LLM)          |
                     |  GUARD: score >= 6  |
                     |  (filtered if < 6)  |
                     +---------------------+
```

## What This Example Demonstrates

### Parallel Fan-In (Different Assessments, Not Voting)

The three assessment actions (`assess_skills`, `assess_experience`, `assess_culture_fit`) all depend on `parse_resume` and run in parallel, but each evaluates a **different dimension**:

- **Skills**: Technical skill match against role requirements
- **Experience**: Depth, relevance, and trajectory of work history
- **Culture Fit**: Alignment with company values and communication quality

This is fundamentally different from the voting/ensemble pattern (like `classify_severity` in the incident triage example) where the same question is answered multiple times for consensus.

### Context Isolation

Each assessor sees only what it needs:

| Action | Sees | Does NOT See |
|--------|------|-------------|
| `assess_skills` | skills, previous_roles, role_requirements | achievements, education, culture scores |
| `assess_experience` | previous_roles, experience_years, achievements, education | skill proficiency scores, culture scores |
| `assess_culture_fit` | achievements, cover_letter, company_values | skills list, experience years |

This isolation prevents cross-contamination — the skills assessor cannot be biased by knowing the experience score, and vice versa.

### Weighted Composite Scoring

The `combine_scores` tool action reads all three assessment outputs and computes a weighted composite:

```
composite = skills * 0.40 + experience * 0.35 + culture_fit * 0.25
```

Weights are configurable in `seed_data/role_requirements.json`.

### Guard-Based Filtering

The `generate_recommendation` action only runs for candidates with `composite_score >= 6`, filtering out weak candidates before spending LLM tokens on detailed recommendations.

## Data Description

### Staging Data (10 Candidates)

| Candidate | Role | Profile |
|-----------|------|---------|
| Sarah Chen | Senior SWE | Strong: 7yr, Stripe/Dropbox, distributed systems |
| Marcus Johnson | Senior SWE | Mid-range: 4yr, startup backend, growing |
| Priya Patel | Data Scientist | Strong: 5yr, Netflix/Airbnb, PhD, publications |
| Tom Bradley | Senior SWE | Weak: 1.5yr, bootcamp, agency work |
| Elena Rodriguez | Product Manager | Strong: 6yr, Datadog/Atlassian, MBA |
| James Kim | Data Scientist | Mid-range: transitioning from analytics |
| Aisha Williams | Senior SWE | Overqualified: 11yr, Google/AWS, Staff level |
| David Park | Product Manager | Mid-range: 3yr, startup PM |
| Rachel Foster | Data Scientist | Mid-range/strong: 4yr, Spotify/IBM Research |
| Kevin O'Brien | Senior SWE | Weak: 2yr, Rails maintenance |

### Seed Data

- `role_requirements.json`: Must-have/nice-to-have skills, scoring weights, and thresholds for 3 roles
- `company_values.json`: 6 company values with descriptions and behavioral signals

## Running the Workflow

```bash
# From the examples/candidate_screener/ directory

# 1. Set up environment
cp .env.example .env
# Edit .env with your OpenAI API key

# 2. Run the workflow
agac run -a candidate_screener
```

## File Structure

```
examples/candidate_screener/
├── .env.example                          # API key template
├── agent_actions.yml                     # Project configuration
├── agent_workflow/
│   └── candidate_screener/
│       ├── README.md                     # This file
│       ├── agent_config/
│       │   └── candidate_screener.yml    # Workflow definition (6 actions)
│       ├── agent_io/
│       │   └── staging/
│       │       └── applications.json     # 10 synthetic job applications
│       └── seed_data/
│           ├── role_requirements.json    # Role specs + scoring weights
│           └── company_values.json       # Company values for culture assessment
├── prompt_store/
│   └── candidate_screener.md             # Prompts for 4 LLM actions
├── schema/
│   └── candidate_screener/
│       ├── parse_resume.yml              # Resume extraction schema
│       ├── assess_skills.yml             # Skills assessment schema
│       ├── assess_experience.yml         # Experience assessment schema
│       ├── assess_culture_fit.yml        # Culture fit assessment schema
│       ├── combine_scores.yml            # Composite score schema
│       └── generate_recommendation.yml   # Final recommendation schema
└── tools/
    ├── __init__.py
    └── candidate_screener/
        ├── __init__.py
        └── calculate_composite_score.py  # Weighted composite calculation
```

## Customization

- **Scoring weights**: Adjust `scoring_weights` in `seed_data/role_requirements.json`
- **Passing threshold**: Change the guard condition in `generate_recommendation` (default: `composite_score >= 6`)
- **Role requirements**: Add new roles or modify must-have/nice-to-have lists
- **Company values**: Update `company_values.json` to match your organization
- **Tier thresholds**: Modify `TIER_THRESHOLDS` in `calculate_composite_score.py`
