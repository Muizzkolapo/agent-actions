# Research Brief: Agent Actions Whitepaper Validation

**Give this document to our researcher. They should verify every claim below and return findings with sources.**

---

## Objective

We're publishing a whitepaper for Agent Actions, a declarative framework for multi-step LLM workflows. Before publication, we need independent verification that our claims are accurate, our citations are real, and our framing reflects the current state of the field (March 2026).

The whitepaper makes claims in five areas. For each, we need the researcher to verify what we've written, flag anything wrong, and provide current data we can cite.

---

## Area 1: LLM Pricing (Current as of March 2026)

**What we claim:**
- Flagship models cost $2.50–$5.00 per 1M input tokens
- Budget models cost $0.10–$0.25 per 1M input tokens
- Batch APIs offer 50% cost savings across all major providers
- The cost difference between flagship and budget models is roughly 10–20x

**What we need verified:**
1. Current pricing for: GPT-4o, GPT-4o-mini, GPT-5.x (if available), Claude Opus 4.6, Claude Sonnet 4.6, Claude Haiku, Gemini 3.x Pro, Gemini Flash, Mistral Large 3, Mistral Small 3.1, Llama 4 (via Groq/Together)
2. Batch API pricing confirmation for OpenAI, Anthropic, Google, Groq
3. Are any of these models deprecated or renamed since we wrote the paper?
4. What's the actual cost ratio between the most expensive and cheapest models as of today?

**Sources to check:** openai.com/api/pricing, anthropic.com/pricing, ai.google.dev/pricing, groq.com/pricing, together.ai/pricing

---

## Area 2: LLM Reliability & Structured Output

**What we claim:**
- A well-prompted frontier model fails roughly 5% of the time without constrained decoding
- Provider-level structured output modes (introduced 2024–2025) solved syntactic JSON compliance
- Semantic accuracy failures (correct format, wrong values) still occur at 1–5% of calls
- Cascading failures in multi-step pipelines are a documented problem

**What we need verified:**
1. What does JSONSchemaBench (Geng et al., arXiv 2501.10868) report for structured output compliance rates? What models? What conditions?
2. What does StructuredRAG (Shorten et al., arXiv 2408.11061) report?
3. OpenAI's August 2024 structured outputs announcement — what compliance rates did they claim?
4. Anthropic's November 2025 structured outputs — any published compliance data?
5. The paper "Where LLM Agents Fail" (Zhu et al., arXiv 2509.25370) — does it actually discuss cascading failures? What specific findings? Does it contain any percentage figures?
6. Are there other papers on multi-step LLM pipeline failure modes we should cite?

**Key risk:** We previously cited "73% of task failures from cascading errors" — this figure may have come from an AI-generated blog summary (maxpool.dev), not the actual paper. We've removed it, but need to confirm what the paper actually says.

---

## Area 3: Task Decomposition Research

**What we claim:**
- Decomposed LLM pipelines outperform monolithic prompting
- Small models on focused tasks can match large models on combined tasks
- Specific citations: DSPy (NeurIPS 2023), ACONIC (arXiv 2510.07772), ADaPT (Allen AI), Google Research EMNLP 2025, Select-Then-Decompose (arXiv 2510.17922)

**What we need verified:**
1. For each paper cited: Does it exist? Are the findings accurately described? Are the numbers right?
2. DSPy: Did decomposed 770M/13B pipelines really match expert-prompted GPT-3.5? Was the 25–65% improvement figure accurate?
3. ACONIC: 10–40 percentage point gains — is this right?
4. ADaPT: 28–33% absolute improvement over monolithic ReAct — verified?
5. Google Research "Small Models, Big Results" — is this a real EMNLP 2025 paper? What are the actual findings?
6. Andrew Ng's quote about agentic workflows focusing on one thing at a time — source? (We cite his tweet from March 2024)
7. Are there newer papers (2025–2026) on task decomposition we should add?

---

## Area 4: Global South & AI Access Economics

**What we claim:**
- API costs that seem reasonable in the US are prohibitive in developing countries
- Average monthly developer salaries: Nigeria ~$300, Bangladesh ~$300, Kenya ~$800, Colombia ~$2,000, USA ~$8,000
- A single 10,000-record flagship pipeline ($75) costs a Nigerian developer ~25% of monthly salary
- UNIDO, GSMA, UNCTAD have documented AI pricing as a disproportionate barrier
- GSMA reports GPU costs at 75% of GDP per capita in Kenya
- PwC projects 84% of AI's economic value captured by China, North America, and Europe

**What we need verified:**
1. Developer salary data for each country — what are current sources saying? We cited WorldSalaries, PayScale, Mywage.org. Are these reliable? Is Glassdoor reliable for these markets?
2. The UNIDO claim about pricing barriers in the Global South — exact source and quote?
3. The GSMA GPU/GDP per capita claim — exact source? Is this about inference costs or hardware purchase?
4. The PwC "Sizing the Prize" 84% figure — is this from the original report? What year? Still cited?
5. UNCTAD Technology and Innovation Report 2025 — does it exist? What does it say about AI access?
6. Are there more recent (2025–2026) reports on AI access inequality we should cite?

---

## Area 5: CO2 & Environmental Impact

**What we claim:**
- Flagship models (>100B params): ~30–160g CO2 per 1M tokens
- Budget models (<30B params): ~3–10g CO2 per 1M tokens
- Energy ratio between large and small models: 8–60x
- We cite Luccioni et al. (FAccT 2024), Epoch AI (2025), DitchCarbon

**What we need verified:**
1. Luccioni et al. "Power Hungry Processing" (FAccT 2024) — what are the actual per-inference energy figures? Which models? Does it cover inference (not just training)?
2. Epoch AI's 2025 analysis — what specific publication? What figures?
3. DitchCarbon estimates — are these peer-reviewed or commercial estimates?
4. IEA's 2025 report on AI energy — what does it say about inference costs specifically?
5. Google's August 2025 Gemini sustainability report — what CO2 figures? How do they compare to our estimates?
6. Are our ranges (30–160g for large, 3–10g for small) defensible given current literature?
7. Is there a better way to frame this that's accurate without overstating precision?

---

## Area 6: Hacker News & Blog Quotes

We quote several sources. For each, we need: does the quote exist at the stated source? Is it accurate?

| # | Quote | Claimed Source | Verify |
|---|-------|---------------|--------|
| 1 | "Five layers of abstraction just to change a minute detail" | HN item #40750034 | URL, author, context |
| 2 | "Asking even a top-notch LLM to output well-formed JSON simply fails sometimes" | HN item #40549804 | URL, author, context |
| 3 | "A malformed JSON response is obvious...time bomb" | nmn.gl/blog/on-structured-outputs | Author, date |
| 4 | "One SaaS company had 47 copies of their standard summarization prompt" | v2solutions.com | Author, date, context |
| 5 | "The most important part of making OpenAI's batch processing API work is building a reliable polling system" | sinaptia.dev | Author, date |
| 6 | "Unlike traditional code, prompts don't throw errors..." | educative.io/blog | Author, date |

---

## Area 7: Open-Source Model Landscape (March 2026)

**What we reference:**
- Qwen 3's 4B parameter model rivals previous generation's 72B
- Llama 4 Scout: 17B active / 109B total, 10M context
- Mistral Small 3.1 at 24B outperforms last year's flagships

**What we need verified:**
1. Qwen 3 — is the 4B vs. 72B claim from official benchmarks? Which benchmarks? Is Qwen 3.5 out?
2. Llama 4 Scout — are these specs accurate? Any newer Llama releases?
3. Mistral Small 3.1 — 24B params, outperforms GPT-4o Mini on what benchmarks?
4. DeepSeek R1 — should we reference this? What's the current status?
5. Any other notable open-source models released late 2025 / early 2026 we're missing?

---

## Deliverable

For each area, return:
1. **Confirmed** — claim is accurate, here's the source
2. **Needs update** — claim was true but data has changed, here's current data
3. **Wrong** — claim is incorrect, here's what's actually true
4. **Unverifiable** — can't find a reliable source, recommend removing or softening

Include URLs and publication dates for every source. We need to cite these in the whitepaper.

**Timeline:** We need this before the whitepaper goes live. The paper's core arguments are sound — we're validating the specific numbers and citations, not the thesis.
