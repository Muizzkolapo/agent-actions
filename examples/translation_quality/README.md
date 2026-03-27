# Translation Quality

An [agent-actions](https://github.com/Muizzkolapo/agent-actions) example that produces high-quality translations through parallel strategy execution, deterministic best-candidate selection, and back-translation validation to detect meaning drift.

## Install

```bash
pip install agent-actions
```

## Run

```bash
# Copy the environment file and add your API key
cp .env.example .env

# Run the workflow
agac run -a translation_quality
```

Input texts are read from `agent_io/staging/texts.json`. The final translation with quality metadata is written to `agent_io/target/format_output/`.

## What It Does

- Analyzes the source text to identify domain, tone, key terminology, and cultural references before any translation begins — this context steers all downstream steps and is paired with a domain glossary from seed data.
- Runs three parallel translation strategies simultaneously — literal (preserves source structure), idiomatic (prioritizes natural target-language flow), and domain-adapted (uses glossary terms and conventions) — with each translator working in isolation from the others.
- Selects the best candidate translation using a deterministic comparison tool that scores each version on completeness and reported confidence, then fans in the results.
- Back-translates the selected best translation to the source language without seeing the original text, preventing the model from copying rather than translating, to enable a faithful round-trip test.
- Validates quality by comparing the original text against the back-translation to detect meaning drift, omissions, and tone shifts — producing a quality score and flagging specific issues before packaging the final output.
