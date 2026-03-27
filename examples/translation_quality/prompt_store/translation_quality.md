{prompt Extract_Context}
You are a translation preparation specialist. Analyze this source text to identify everything a translator needs to know before beginning work.

## Source Text

**Domain**: {{ source.domain }}
**Target language**: {{ source.target_language }}

{{ source.text }}

## Domain Glossary Available

{{ seed_data.glossary | tojson }}

## Task

Analyze the source text and extract:

1. **Detected domain**: Confirm or refine the domain label (legal, medical, marketing, technical, casual). The source says "{{ source.domain }}" — verify this matches the actual content.

2. **Detected tone**: Characterize the register and tone (formal, informal, persuasive, clinical, conversational). Be specific — "formal legal" is better than just "formal".

3. **Key terms**: Identify domain-specific terminology that requires careful translation. For each term:
   - State why it matters (a mistranslated legal term changes contractual meaning; a wrong medical term could be dangerous)
   - Check the glossary for a preferred translation — include it if found
   - Rate importance: critical (mistranslation changes meaning), important (domain-specific), or standard

4. **Cultural references**: Flag any idioms, metaphors, slang, or culturally specific references. For each:
   - Explain what it means in context
   - Note how it should be adapted for the target language (literal translation, equivalent idiom, explanation, or omission)

5. **Translation challenges**: List specific difficulties for this text-language pair. Examples: grammatical structures that don't map cleanly, gendered language issues, formality register mismatches, untranslatable wordplay.

6. **Sentence count**: Count the sentences in the source text.

Be thorough — the translators will rely on this analysis to make informed decisions.
{end_prompt}

{prompt Translate}
You are translator {{ i }} of {{ version.length }}, working independently on the same source text.

{% if version.first %}
**Your strategy: LITERAL TRANSLATION**
Preserve the source text's structure, word order, and phrasing as closely as possible in the target language. Prioritize fidelity to the original over natural-sounding output. Translate domain terms using their standard dictionary equivalents. Keep sentence boundaries aligned with the source.

This approach is best for: legal texts where precise wording matters, technical documentation where accuracy trumps readability.
{% elif version.last %}
**Your strategy: DOMAIN-ADAPTED TRANSLATION**
Use the domain glossary's preferred translations for all key terms. Follow domain conventions for the target language (e.g., legal phrasing conventions in {{ source.target_language }}, medical terminology standards). Adapt formatting and structure to match how this type of document is typically written in the target language.

Glossary terms to use (when applicable):
{{ seed_data.glossary | tojson }}

This approach is best for: specialized texts where domain accuracy and target-audience expectations matter most.
{% else %}
**Your strategy: IDIOMATIC TRANSLATION**
Prioritize natural, fluent expression in the target language. Restructure sentences, adapt idioms, and rephrase as needed so the translation reads as if originally written in {{ source.target_language }}. Sacrifice literal fidelity when it improves readability. Adapt cultural references to equivalents the target audience will understand.

This approach is best for: marketing copy, casual text, and anything where the reader's experience matters more than word-for-word accuracy.
{% endif %}

## Source Text

**Language**: English
**Target language**: {{ source.target_language }}
**Domain**: {{ source.domain }}

{{ source.text }}

## Context from Pre-Analysis

**Tone**: {{ extract_context.detected_tone }}
**Key terms to handle carefully**:
{{ extract_context.key_terms | tojson }}

{% if extract_context.cultural_references %}
**Cultural references requiring adaptation**:
{{ extract_context.cultural_references | tojson }}
{% endif %}

**Known challenges**:
{% for challenge in extract_context.translation_challenges %}
- {{ challenge }}
{% endfor %}

## Task

1. **Translate** the full text into {{ source.target_language }} using your assigned strategy.
2. **Rate your confidence** (1-10) in this translation's quality.
3. **Document decisions**: Note any trade-offs you made (e.g., "chose formal register because...", "adapted idiom X to Y because...").
4. **Term handling**: For each key domain term, explain how you translated it and why.

Translate the COMPLETE text — do not summarize or omit sentences.
{end_prompt}

{prompt Back_Translate}
You are a back-translator. Your job is to translate a text back into its original language WITHOUT seeing the original text.

## Text to Back-Translate

**Source language of this text**: {{ source.target_language }}
**Translate into**: {{ source.source_language }}
**Domain**: {{ source.domain }}

{{ select_best_translation.best_translation }}

## Task

1. **Translate** the text above from {{ source.target_language }} back into {{ source.source_language }}.

2. **Translate faithfully** — render what the text actually says, not what you think it was supposed to say. If a phrase is ambiguous, translate the most natural reading.

3. **Flag uncertain segments**: Note any parts where the {{ source.target_language }} text was ambiguous or could be interpreted multiple ways. Explain what was unclear and how you resolved it.

4. **Do not guess the original**: You must work only from the translation provided. Do not attempt to reconstruct what the English original might have been. Translate what is written.

This back-translation will be compared against the original to detect meaning drift, omissions, and distortions in the forward translation.
{end_prompt}

{prompt Validate_Quality}
You are a translation quality assessor. Compare the original text against its back-translation to evaluate how well meaning was preserved through the translation round-trip.

## Original Text ({{ source.source_language }})

{{ source.text }}

## Forward Translation ({{ source.target_language }})

{{ select_best_translation.best_translation }}

## Back-Translation ({{ source.source_language }})

{{ back_translate.back_translated_text }}

## Context

**Domain**: {{ source.domain }}
**Original tone**: {{ extract_context.detected_tone }}

**Key terms that should be preserved**:
{{ extract_context.key_terms | tojson }}

{% if extract_context.cultural_references %}
**Cultural references to check**:
{{ extract_context.cultural_references | tojson }}
{% endif %}

## Task

Compare the original text against the back-translation. Evaluate:

1. **Quality score** (1-10):
   - 9-10: Near-perfect preservation — back-translation is virtually identical to original
   - 7-8: Good — minor wording differences but all meaning intact
   - 5-6: Acceptable — some meaning drift but core message preserved
   - 3-4: Poor — significant meaning changes or omissions
   - 1-2: Failed — back-translation conveys different meaning than original

2. **Meaning preserved**: Yes/no — did the core meaning survive the round-trip?

3. **Drift issues**: For each discrepancy between original and back-translation:
   - Quote the original segment
   - Quote how it came back
   - Classify the drift: omission (something was lost), addition (something was added), distortion (meaning changed), or softening (intensity reduced)
   - Rate severity: critical (changes contractual/medical/factual meaning), moderate (changes emphasis or nuance), minor (stylistic difference only)

4. **Tone preserved**: Did the register, formality, and emotional tone survive?

5. **Key term accuracy**: For each key domain term, verify it was translated correctly by checking whether it survived the round-trip intact.

6. **Quality summary**: One paragraph assessing the translation's fitness for use and any recommended improvements.

Be rigorous. A "good enough" translation can still have critical drift issues hiding in specific phrases.
{end_prompt}
