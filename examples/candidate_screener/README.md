# Candidate Screener

An [agent-actions](https://github.com/Muizzkolapo/agent-actions) example that screens job applications by parsing resumes, running three independent parallel assessments, computing a weighted composite score, and generating hire/no-hire recommendations for qualifying candidates.

## Install

```bash
pip install agent-actions
```

## Run

```bash
# Copy the environment file and add your API key
cp .env.example .env

# Run the workflow
agac run -a candidate_screener
```

Input data lives in `agent_workflow/candidate_screener/agent_io/staging/applications.json` (sample job applications with resumes and cover letters). Role requirements and company values used as seed data are in `agent_workflow/candidate_screener/seed_data/`. Output is written to `agent_workflow/candidate_screener/agent_io/target/`.

## What It Does

- Parses each resume and cover letter into structured candidate data (skills, experience, achievements, education).
- Runs three independent parallel assessments — technical skills match, depth of professional experience, and culture fit — each seeing only the fields relevant to its dimension.
- Computes a weighted composite score (0–10) from all three assessments using a deterministic tool action.
- Filters out candidates scoring below 6, then generates a detailed hire/no-hire recommendation with justification for those who pass.
