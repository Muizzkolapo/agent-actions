# Review Analyzer

An [agent-actions](https://github.com/Muizzkolapo/agent-actions) example that processes product reviews through a multi-model pipeline — extracting claims, scoring quality via parallel consensus, drafting merchant responses, and surfacing actionable product insights.

## Install

```bash
pip install agent-actions
```

## Run

```bash
# Copy the environment file and add your API keys
cp .env.example .env

# Run the workflow
agac run -a review_analyzer
```

Input reviews are read from `agent_io/staging/reviews.json`. Enriched output is written to `agent_io/target/format_output/`.

## What It Does

- Extracts factual claims, product aspects, and sentiment signals from each review using a fast Groq model, deliberately hiding the star rating to prevent anchoring bias in downstream scoring.
- Scores review quality three times in parallel using independent LLM scorers (each unaware of the others' scores), then merges results into a deterministic weighted consensus score via a tool action.
- Guards all downstream LLM calls with a quality threshold — reviews scoring below 6 are filtered out, burning no tokens on low-signal content.
- Generates a professional merchant response using Anthropic Claude (for nuanced reasoning) and extracts actionable product improvement insights in parallel — both conditioned on the consensus quality gate.
- Packages the merchant response, product insights, and extracted claims into a final structured output via a deterministic formatting tool.
