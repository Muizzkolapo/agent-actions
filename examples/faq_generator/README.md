# FAQ Generator

An [agent-actions](https://github.com/Muizzkolapo/agent-actions) example that transforms batches of customer support tickets into publishable FAQ entries using consensus topic classification, frequency-based gating, and deduplication against existing content.

## Install

```bash
pip install agent-actions
```

## Run

```bash
# Copy the environment file and add your API keys
cp .env.example .env

# Run the workflow
agac run -a faq_generator
```

Input data lives in `agent_workflow/faq_generator/agent_io/staging/tickets.json` (sample support tickets with subjects, bodies, and support answers). Existing published FAQs used for deduplication are in `agent_workflow/faq_generator/seed_data/`. Output is written to `agent_workflow/faq_generator/agent_io/target/`.

## What It Does

- Extracts the core problem and resolution from each support ticket, dropping customer PII fields before any downstream processing.
- Classifies each ticket's topic using three independent parallel voters, then resolves the consensus category via majority rule using a deterministic tool action.
- Groups all tickets by their consensus topic at file granularity and computes cluster sizes, so frequency information is available for the next stage.
- Drafts a FAQ question and answer for each topic cluster using Anthropic Claude, but only for clusters with 3 or more tickets — single-ticket issues are filtered as noise.
- Checks each generated FAQ against the existing published FAQ catalog from seed data, marking entries as new, update, or duplicate, and discards duplicates before formatting the final publishable output.
