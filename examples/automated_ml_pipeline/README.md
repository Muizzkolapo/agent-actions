# Automated ML Pipeline

An [agent-actions](https://github.com/Muizzkolapo/agent-actions) example that runs an end-to-end machine learning pipeline from data quality assessment through feature engineering, parallel model training, evaluation, selection, and conditional production deployment.

## Install

```bash
pip install agent-actions
```

## Run

```bash
# Copy the environment file and add your API keys
cp .env.example .env

# Run the workflow
agac run -a automated_ml_pipeline
```

Input data lives in `agent_workflow/automated_ml_pipeline/agent_io/staging/ml_dataset.json` (a telecom customer churn dataset). Seed data — feature definitions, a model registry, and deployment config — is in `agent_workflow/automated_ml_pipeline/seed_data/`. Output is written to `agent_workflow/automated_ml_pipeline/agent_io/target/`.

## What It Does

- Assesses data quality and halts records that fall below a 0.7 quality threshold before any further processing.
- Recommends and applies feature engineering transformations, then trains three ML model variants in parallel.
- Evaluates each model in parallel and selects the best-performing champion using a deterministic tool action.
- Generates model explainability artifacts and assesses deployment readiness, blocking deployment if the readiness score is below 0.8.
- Produces a comprehensive pipeline report covering all stages, metrics, and the final deployment decision.
