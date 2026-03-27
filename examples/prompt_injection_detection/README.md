# Prompt Injection Detection

An [agent-actions](https://github.com/Muizzkolapo/agent-actions) example that screens incoming prompts through a multi-layer detection pipeline combining statistical tools and LLM reasoning to produce a BLOCK, REVIEW, or PASS decision with forensic reporting.

## Install

```bash
pip install agent-actions
```

## Run

```bash
# Copy the environment file and add your API key
cp .env.example .env

# Run the workflow
agac run -a prompt_injection_detection
```

Input prompts are read from `agent_io/staging/prompts.json`. Output reports land in `agent_io/target/` under the final report action directory.

## What It Does

- Runs four statistical detection tools in parallel: DLP regex scanning, prompt Frechet distance scoring, topic Jensen-Shannon Divergence, and Bayesian ELBO anomaly scoring — each against known attack pattern seed data.
- Simultaneously runs an independent LLM semantic threat analyzer to detect social engineering, role manipulation, and data extraction attempts that statistical layers cannot perceive.
- Aggregates the four statistical scores into a weighted verdict, then uses an LLM analyst to interpret what the signals mean for the specific prompt.
- A chief-arbiter LLM synthesizes both the semantic analysis and the statistical interpretation into a final judgment with authority to override either stream.
- Computes a composite risk score from the meta-detector and statistical aggregate to produce a final BLOCK, REVIEW, or PASS decision — then generates a guarded forensic report (block report for BLOCK decisions, clearance/review report for all others).
