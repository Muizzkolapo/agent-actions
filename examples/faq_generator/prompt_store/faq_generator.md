{prompt Extract_Issue}
Extract the core problem and resolution from a customer support ticket.

## INPUT DATA

**Subject**: {{ source.subject }}

**Ticket Body**: {{ source.body }}

**Support Answer**: {{ source.answer }}

**Ticket Type**: {{ source.type }}

**Tags**: {{ source.tags }}

## TASK

Distill this raw support ticket into a structured problem/solution pair. Focus on what the customer actually needs — strip away conversational noise, greetings, and tangential details.

Specifically:

1. **Core Problem**: What is the customer trying to do, and what is blocking them? State the problem from the customer's perspective in one clear sentence.
2. **Resolution Summary**: How was the issue resolved? Include the specific fix, workaround, or answer provided. If unresolved, state what was attempted.
3. **Product Area**: Identify the specific product feature, module, or system component involved (e.g., "billing", "authentication", "API integrations", "onboarding").
4. **Was It Resolved?**: Determine whether the ticket reached a genuine resolution. A ticket is resolved only if the customer's problem was actually addressed — not just acknowledged or escalated.
5. **Customer Intent**: What was the customer ultimately trying to accomplish? This may differ from the surface-level question they asked.

## OUTPUT FORMAT

```json
{
  "core_problem": "Clear one-sentence description of the customer's problem",
  "resolution_summary": "What was done to resolve it, or what was attempted",
  "product_area": "specific feature or system area",
  "is_resolved": true | false,
  "resolution_type": "fix | workaround | information | escalated | unresolved",
  "customer_intent": "What the customer was ultimately trying to do"
}
```

## GUIDELINES

- If the ticket body is vague, infer the problem from context clues in the answer and tags
- Prefer the customer's own words when describing the problem
- If the answer just says "closing ticket" or similar without a real fix, mark as unresolved
- A workaround counts as resolved, but note it as resolution_type "workaround"

{end_prompt}

{prompt Classify_Topic}
You are classifier {{ i }} of {{ version.length }} in a FAQ topic classification ensemble.

{% if version.first %}
**Your focus**: CUSTOMER INTENT. What is the customer trying to accomplish? Classify based on the goal behind the question, not the technical details. Think about what FAQ category a customer would look under when searching for help.
{% elif version.last %}
**Your focus**: RESOLUTION TYPE. What kind of answer does this need? Classify based on whether this is a how-to, a troubleshooting issue, an account/billing matter, a known limitation, or a feature explanation. Think about the shape of the answer, not just the question.
{% else %}
**Your focus**: PRODUCT AREA. Which system or feature is this about? Classify based on the specific product component involved. Think about how a product team would organize their documentation.
{% endif %}

## TICKET ANALYSIS

**Core Problem**: {{ extract_issue.core_problem }}

**Resolution Summary**: {{ extract_issue.resolution_summary }}

**Product Area**: {{ extract_issue.product_area }}

## AVAILABLE CATEGORIES

You must classify this ticket into exactly one of the following FAQ categories:

{% for category in seed_data.existing_faqs.faq_categories %}
- {{ category }}
{% endfor %}

## TASK

Classify this ticket into the single most appropriate FAQ category from the list above.

1. **Selected Category**: Choose the best-fit category. If multiple seem relevant, pick the one that a customer would most naturally look under.
2. **Confidence Score**: Rate your confidence from 0.0 to 1.0.
3. **Reasoning**: Explain why this category fits, referencing specific evidence from the ticket analysis.
4. **Runner-Up Category**: If confidence is below 0.8, name the second-best category.

## OUTPUT FORMAT

```json
{
  "category": "Selected category from the list above",
  "confidence": 0.0-1.0,
  "reasoning": "Why this category is the best fit, citing specific evidence",
  "runner_up_category": "Second-best category if confidence < 0.8, otherwise null"
}
```

## IMPORTANT

- You MUST select from the provided categories — do not invent new ones
- Base your classification on the problem and resolution, not just keywords
- If the ticket truly does not fit any category, choose the closest match and set confidence below 0.5

{end_prompt}

{prompt Generate_FAQ_Draft}
Write a customer-facing FAQ entry by synthesizing multiple related support tickets into one clear question and answer.

## CLUSTER DATA

**Topic**: {{ cluster_by_topic.cluster_topic }}

**Number of Tickets in Cluster**: {{ cluster_by_topic.cluster_size }}

**Representative Problems**:
{{ cluster_by_topic.representative_problems }}

**Representative Resolutions**:
{{ cluster_by_topic.representative_resolutions }}

## FAQ GUIDELINES

{{ seed_data.existing_faqs.faq_guidelines }}

## TASK

Synthesize the clustered tickets above into a single, polished FAQ entry. You are writing for customers, not for support agents.

1. **FAQ Question**: Write the question the way a customer would actually ask it. Use natural, plain language. Avoid jargon or internal terminology.

2. **FAQ Answer**: Write a clear, direct answer that:
   - Leads with the solution or key information (don't bury it)
   - Includes step-by-step instructions if the resolution involves multiple actions
   - Covers the most common variation of this problem (not every edge case)
   - Follows the tone and length guidelines from the FAQ guidelines above

3. **Alternative Phrasings**: Generate 2-3 other ways a customer might search for this same issue. Think about different vocabulary, different framings, and common misspellings or shorthand.

4. **Applicability Note**: If this FAQ only applies under certain conditions (e.g., specific plan tier, specific platform), state those conditions clearly.

## OUTPUT FORMAT

```json
{
  "faq_question": "The primary FAQ question in customer-friendly language",
  "faq_answer": "Complete answer following the guidelines",
  "alternative_phrasings": [
    "Alternative way a customer might ask this",
    "Another search phrase for the same issue",
    "Third variation of the question"
  ],
  "applicability_note": "Any conditions or limitations, or null if universally applicable",
  "source_ticket_count": "Number of tickets that informed this FAQ"
}
```

## GUIDELINES

- Do NOT just copy the best ticket's resolution — synthesize across all tickets in the cluster
- If different tickets had different resolutions, present the most common or most reliable one first, then mention alternatives
- Keep the question short (one sentence) and the answer concise but complete
- Use second person ("you") when addressing the customer

{end_prompt}

{prompt Deduplicate_FAQs}
Check whether a newly generated FAQ overlaps with existing published FAQs.

## NEW FAQ

**Question**: {{ generate_faq_draft.faq_question }}

**Answer**: {{ generate_faq_draft.faq_answer }}

**Category**: {{ generate_faq_draft.faq_category }}

## EXISTING PUBLISHED FAQs

{{ seed_data.existing_faqs.published_faqs }}

## TASK

Compare the new FAQ above against every existing published FAQ. Determine whether this new FAQ should be published, used to update an existing FAQ, or discarded as a duplicate.

Classify the new FAQ as one of:

- **new**: No existing FAQ covers this topic. The question addresses a genuinely different issue or a meaningfully different aspect of the product. Publish it.
- **update**: An existing FAQ covers the same general topic, but the new FAQ contains additional information, a better answer, updated steps, or covers a variation not addressed by the existing one. The existing FAQ should be updated or supplemented.
- **duplicate**: An existing FAQ already fully covers this question and answer. The customer would find the same information from the existing FAQ. Do not publish.

## COMPARISON CRITERIA

For each existing FAQ, assess:

1. **Topic Overlap**: Do they address the same underlying issue?
2. **Answer Coverage**: Does the existing FAQ's answer fully address the new FAQ's question?
3. **Information Gap**: Does the new FAQ contain information not present in the existing FAQ?
4. **Freshness**: Could the new FAQ reflect updated steps, UI changes, or policy changes?

## OUTPUT FORMAT

```json
{
  "classification": "new | update | duplicate",
  "matching_faq_id": "ID of the most similar existing FAQ, or null if new",
  "overlap_score": 0.0-1.0,
  "reasoning": "Explain the classification decision with specific references to the existing FAQ",
  "merge_suggestion": "If 'update', describe what information from the new FAQ should be added to the existing one. Otherwise null."
}
```

## IMPORTANT

- Be CONSERVATIVE with "duplicate" — only use it if the existing FAQ fully covers the issue. If the new FAQ adds any meaningful nuance, new steps, or addresses a related-but-distinct scenario, classify as "update" or "new".
- Semantic similarity matters more than keyword overlap. Two FAQs can use different words but cover the same issue.
- If the existing FAQ is outdated or incomplete, the new FAQ is an "update" even if the topic is the same.

{end_prompt}
