{prompt Extract_Raw_QA}
You are extracting **staff/senior engineer level** testable knowledge from technical documentation for the {{ seed.exam_syllabus.exam_name }}.

## EXAM CONTEXT

**Exam**: {{ seed.exam_syllabus.exam_name }}
**Platform**: {{ seed.exam_syllabus.platform_name }}

{{ seed.exam_syllabus.audience_profile.description }}

**Target Responsibilities**:
{% for resp in seed.exam_syllabus.audience_profile.responsibilities %}
- {{ resp }}
{% endfor %}

**Assumed Prerequisites** (do NOT test these basics):
{% for req in seed.exam_syllabus.audience_profile.required_knowledge %}
- {{ req }}
{% endfor %}



## OUTPUT FORMAT

Extract **3-5 challenging Q&A pairs**. Return ONLY this exact structure:

```json
{
  "questions": [
    {
      "question_text": "What happens if a client reuses a request ID within the same session?",
      "answer_text": "The behavior is undefined/error - IDs MUST NOT be previously used within the same session.",
      "source_quote": "The request ID MUST NOT have been previously used...",
      "difficulty_reason": "Tests understanding of session state and ID uniqueness requirements"
    }
  ]
}
```

**STRICT OUTPUT CONTRACT:**
- Return ONLY `questions` array at root level
- Each question object has EXACTLY 4 fields: `question_text`, `answer_text`, `source_quote`, `difficulty_reason`
- NO extra fields like `_comments`, `_version`, `_schema`, `items`, `metadata`, `question_metadata`
- NO duplicate representations of the same data

## RULES

1. **NO BASIC RECALL**: Skip "What is X?" BUT DO test architectural reasoning:
   - ❌ "What is MCP?" (definition recall)
   - ✅ "Why does MCP separate client/server roles?" (design reasoning)
   - ✅ "What breaks if request IDs aren't unique?" (failure mode analysis)
2. **EDGE CASES**: Prioritize constraints, limitations, error conditions
3. **SPECIFICITY**: Include exact values, error codes, parameter names
4. **IMPLICATIONS**: Focus on what the requirement MEANS for implementation

## DIVERSITY REQUIREMENT

Extract 3-5 questions that test DIFFERENT mental models. Each question must diagnose a distinct concept:

**Required coverage (pick ONE question per category):**
1. **Protocol mechanics** - State management, message ordering, connection lifecycle
2. **Architecture** - Role separation, design tradeoffs, component boundaries
3. **Trust boundaries** - Consent, data flow, security implications
4. **Feature constraints** - What breaks when features interact incorrectly
5. **Failure modes** - Edge cases, error conditions, undefined behavior

**Anti-pattern**: Multiple questions testing the same concept (e.g., 3 questions about user consent)

**Quality test**: Would answering all questions reveal a complete mental model of this page's core concepts?

## SKIP THESE (NOT GENERAL CONCEPTS)

❌ **Example-specific content**: Questions about specific example implementations (weather servers, todo apps, etc.)
❌ **Tutorial walkthroughs**: Step-by-step example code that doesn't teach general protocol rules
❌ **Third-party API details**: Error messages/behaviors specific to external services (NWS API, GitHub API, etc.)
❌ **Sample code quirks**: Implementation details that are example-specific, not protocol requirements
❌ **Prerequisite basics**: Content that explains assumed knowledge (see prerequisites above)
❌ **Off-objective content**: Knowledge not aligned with the learning objectives listed above



## QUALITY TESTS
Before including a Q&A, verify:
1. **Generalization Test**: Would this apply to ANY {{ seed.exam_syllabus.platform_name }} implementation, not just this example?
2. **Objective Alignment Test**: Does this test one of the learning objectives listed above?
3. **Responsibility Test**: Would answering this help someone perform the target responsibilities?
{end_prompt}

{prompt Canonicalize_QA}
You are deduplicating and canonicalizing Q&A pairs from multiple extraction iterations.{{ seed.exam_syllabus.exam_name }}.

## TASK

You have received Q&A pairs from 3 parallel extraction runs. Many questions are semantically similar or identical but phrased differently. Your job is to:

1. **Gather all questions** - Collect from all three extraction iteration arrays
2. **Identify semantic duplicates** - Questions that test the same knowledge even if worded differently
3. **Create canonical versions** - Merge duplicates into the best single representation
4. **Preserve unique questions** - Keep questions that test distinct knowledge

## INPUT

You'll receive Q&A objects nested in three arrays from the extraction iterations:

```json
{
  "extract_raw_qa_3_questions": [ /* array of Q&A objects */ ],
  "extract_raw_qa_2_questions": [ /* array of Q&A objects */ ],
  "extract_raw_qa_1_questions": [ /* array of Q&A objects */ ]
}
```

**First, gather ALL questions from these three arrays into a single collection, then deduplicate across them.**

## OUTPUT FORMAT

Return ONLY this exact structure with a `canonical_questions` array:

```json
{
  "canonical_questions": [
    {
      "question_text": "What happens if a client reuses a request ID within the same session?",
      "answer_text": "The behavior is undefined/error - IDs MUST NOT be previously used within the same session.",
      "source_quote": "The request ID MUST NOT have been previously used...",
      "difficulty_reason": "Tests understanding of session state and ID uniqueness requirements",
      "merged_count": 2,
      "canonicalize_reasoning": "Merged 2 similar questions: 'What happens if a client reuses a request ID?' and 'Can request IDs be reused within the same session?'. Both test the same protocol rule about ID uniqueness. Chose first version's answer for completeness, added 'within the same session' context from second version for clarity."
    }
  ]
}
```

**STRICT OUTPUT CONTRACT:**
- Return ONLY `canonical_questions` array at root level
- Each question object must have EXACTLY 6 fields: `question_text`, `answer_text`, `source_quote`, `difficulty_reason`, `merged_count`, `canonicalize_reasoning`
- NO extra fields or metadata

## CANONICALIZATION RULES

1. **Question Text**: Choose the clearest, most specific phrasing. Add context if needed (e.g., "within the same session").

2. **Answer Text**: Merge information from all versions. Keep the most comprehensive answer that includes:
   - The core answer
   - Important edge cases
   - Specific details (error codes, parameter names, exact values)

3. **Source Quote**: Use the most relevant and complete quote that supports the answer.

4. **Difficulty Reason**: Keep or merge the best explanation of why this tests senior-level knowledge.

5. **Merged Count**: Set to the number of similar questions merged (1 if unique, 2+ if merged).

6. **Canonicalize Reasoning**: Provide a clear justification explaining:
   - **If merged (count ≥ 2)**: Which questions were merged and why they're semantically similar. What made this the best canonical version? What was taken from each source?
   - **If unique (count = 1)**: Why this question is distinct from others and wasn't merged.

## SIMILARITY DETECTION

Questions are **semantically similar** if they:
- Test the same protocol rule or behavior
- Would have the same or highly overlapping answers
- Differ only in phrasing, not content

**Example duplicates:**
- "What happens if a request ID is reused?" ≈ "Can request IDs be reused?"
- "What is the purpose of capability flags?" ≈ "Why are capability flags needed?"

**Example NOT duplicates:**
- "What happens if a server lacks a capability?" ≠ "What happens if a client lacks a capability?"

## QUALITY CHECKS

- **No information loss**: Canonical version should capture all important details from merged questions
- **Clarity improvement**: Canonical version should be clearer than individual versions
- **Correct merging**: Only merge questions that truly test the same knowledge

## REASONING EXAMPLES

**Merged questions (count = 2):**
```
"canonicalize_reasoning": "Merged 2 questions about request ID reuse. Both test the same protocol constraint but with different phrasing. Combined the specificity of 'within the same session' from version 2 with the clearer question structure from version 1."
```

**Unique question (count = 1):**
```
"canonicalize_reasoning": "Unique question about server capability negotiation. While there are other capability-related questions, this specifically tests server-side behavior, not client-side, making it semantically distinct."
```

{end_prompt}

{prompt Filter_Learning_Quality}
Your job is to vote on whether each question promotes **deep conceptual understanding**, not surface-level memorization.

## TASK

Review each question and vote to **keep** or **filter** based on whether it helps students build genuine understanding of fundamental concepts.

## INPUT

You'll receive canonical Q&A pairs:

```json
{
  "canonical_questions": [
    {
      "question_text": "...",
      "answer_text": "...",
      "source_quote": "...",
      "difficulty_reason": "...",
      "merged_count": 2,
      "canonicalize_reasoning": "..."
    }
  ]
}
```

## LEARNING QUALITY CRITERIA

**KEEP questions that:**
1. **Test "Why" and "How"** - Require understanding cause and effect, not just facts
2. **Reveal Mental Models** - Answering correctly means the student understands the underlying concept
3. **Test Implications** - "What happens if...", "What breaks when...", "Why must..."
4. **Connect Concepts** - Link multiple ideas, showing how things relate
5. **Challenge Assumptions** - Make students think beyond the obvious

**FILTER OUT questions that:**
1. **Pure Recall** - "What is X?", "List the Y", "Define Z"
2. **Trivia** - Specific values, names, dates that don't test understanding
3. **Surface Details** - API specifics, syntax, exact wording without conceptual depth
4. **Yes/No without reasoning** - Binary questions that don't require explanation

## SCORING RUBRIC (1-10)

**9-10: Exceptional Learning Question**
- Forces deep reasoning about why/how systems work
- Correct answer proves true conceptual understanding
- Example: "What happens if you reuse a request ID and why does this violate the protocol's stateful design?"

**7-8: Strong Learning Question**
- Tests understanding of implications and consequences
- Requires connecting multiple concepts
- Example: "Why must hosts obtain explicit consent before exposing user data?"

**5-6: Moderate Learning Question**
- Tests some conceptual understanding but leans toward recall
- Could be improved to test deeper reasoning

**1-4: Weak Learning Question**
- Primarily tests memorization or trivia
- Answering correctly doesn't prove understanding
- FILTER OUT (do not include in output)

## OUTPUT FORMAT

Return a vote for EACH question (both keep and filter votes):

```json
{
  "votes": [
    {
      "question_text": "What happens if a client reuses a request ID within the same session?",
      "vote": "keep",
      "learning_quality_score": 9,
      "vote_reasoning": "This question tests deep understanding of session state management and ID uniqueness constraints. Students must reason about why reusing IDs violates stateful protocol design, demonstrating comprehension of both the rule and its architectural purpose. Score 9: Exceptional learning question."
    },
    {
      "question_text": "What is the format of a request ID?",
      "vote": "filter",
      "learning_quality_score": 3,
      "vote_reasoning": "Pure memorization of format details without testing conceptual understanding. Knowing the format doesn't prove understanding of why IDs exist or their role in the protocol. Score 3: Weak learning question - filter out."
    }
  ]
}
```

## VOTING GUIDELINES

For each question, provide:
- **vote**: "keep" (score 7+) or "filter" (score 1-6)
- **learning_quality_score**: 1-10 score
- **vote_reasoning**: Explain your vote decision clearly

**Keep votes (7+):** Explain what concept it tests beyond facts, why getting it right proves understanding

**Filter votes (1-6):** Explain why it's memorization/trivia and doesn't test deep understanding

## STRICT REQUIREMENTS

- Vote on ALL questions (don't skip any)
- Be consistent with scoring rubric above
- Provide clear reasoning for each vote

{end_prompt}

{prompt Aggregate_Votes}
You are aggregating votes from 3 independent reviewers on educational question quality. Your job is to determine which questions pass based on majority voting.

## TASK

Review votes from all 3 reviewers and keep only questions that received **majority "keep" votes** (2 or 3 out of 3).

## INPUT

You'll receive:
1. **Votes from 3 reviewers** - Each reviewer voted on all questions
2. **Original canonical questions** - Full question details

The votes will be in arrays like:
```json
{
  "filter_learning_quality_1_votes": [ /* voter 1 votes */ ],
  "filter_learning_quality_2_votes": [ /* voter 2 votes */ ],
  "filter_learning_quality_3_votes": [ /* voter 3 votes */ ]
}
```

And original questions:
```json
{
  "canonical_questions": [ /* full question objects */ ]
}
```

## AGGREGATION RULES

1. **Count votes for each question** - Tally keep vs filter votes across all 3 reviewers
2. **Majority wins** - Keep questions with 2+ "keep" votes, filter questions with 2+ "filter" votes
3. **Ties (impossible with 3 voters)** - N/A, will always have majority
4. **Calculate average score** - Average the learning_quality_score from all voters

## OUTPUT FORMAT

Return ONLY questions that received majority "keep" votes:

```json
{
  "high_quality_questions": [
    {
      "question_text": "What happens if a client reuses a request ID within the same session?",
      "answer_text": "The behavior is undefined and may lead to errors...",
      "source_quote": "The request ID MUST NOT have been previously used...",
      "difficulty_reason": "Challenges the understanding of proper ID management...",
      "merged_count": 1,
      "canonicalize_reasoning": "Unique question regarding request ID reuse...",
      "vote_summary": "3 keep, 0 filter",
      "avg_quality_score": 8.7,
      "consensus_reasoning": "All 3 reviewers agreed this tests deep understanding of session state management. Voter 1 (score 9): Tests ID uniqueness and stateful design. Voter 2 (score 8): Requires reasoning about protocol constraints. Voter 3 (score 9): Demonstrates comprehension of state integrity."
    }
  ]
}
```

## CONSENSUS REASONING

For each kept question, synthesize all voter reasoning:
- Start with vote summary (e.g., "All 3 reviewers agreed..." or "2 of 3 reviewers found...")
- Include key points from each voter's reasoning
- Show what conceptual understanding the question tests (synthesized from all votes)

Example:
```
"2 of 3 reviewers voted to keep. Voter 1 (score 8): Tests understanding of privacy principles and consent mechanisms. Voter 2 (score 7): Requires reasoning about trust in distributed systems. Voter 3 (score 6): Leans toward recall but tests some implications. Consensus: Tests relationship between consent and system trust."
```

## STRICT REQUIREMENTS

- Only include questions with 2+ "keep" votes
- Include all original question fields (question_text, answer_text, source_quote, difficulty_reason, merged_count, canonicalize_reasoning)
- Add vote_summary, avg_quality_score, and consensus_reasoning
- Sort by avg_quality_score (highest first)

{end_prompt}

{prompt Generate_Answer_From_Source}
You are answering a technical question by analyzing the original source documentation.

## YOUR ROLE

You are Answerer, read the question and the source material, then generate:
1. A comprehensive, accurate answer based ONLY on the source content
2. A direct quote from the source that best supports your answer

## INPUT

**Question**: {{ select_approved_questions.question_text }}

**Source Material**:
This would be in the page_content field

## YOUR TASK

1. **Read the source carefully** - Understand the technical content
2. **Find relevant information** - Locate the parts that answer the question
3. **Write a clear answer** - Explain the answer comprehensively (2-4 sentences)
4. **Extract a supporting quote** - Find the most relevant direct quote from the source

## OUTPUT FORMAT

Return ONLY this exact JSON structure:

```json
{
  "answer_text":  "Your comprehensive answer here (2-4 sentences)",
  "source_quote": "Direct quote from source that supports the answer"
}
```

## REQUIREMENTS

- **Answer must be grounded in source**: Only use information present in the source material
- **Answer must be complete**: Fully address the question, not just partial information
- **Quote must be exact**: Use exact text from source, no paraphrasing
- **Quote must be relevant**: The quote should directly support your answer
- **Be independent**: Don't try to match other answerers - give your own analysis

{end_prompt}

{prompt Consolidate_Answer_From_Source}
You are consolidating two independent answers and validating them against the original source.

## YOUR ROLE

You are the Consolidator. Compare both answers and their quotes, verify alignment with the source,
then produce a single best answer and a single best quote that fully supports it.

## INPUT

**Question**: {{ select_approved_questions.question_text }}

**Answerer 1**:
- Answer: {{ generate_answer_from_source_1.answer_text }}
- Quote: {{ generate_answer_from_source_1.source_quote }}

**Answerer 2**:
- Answer: {{ generate_answer_from_source_2.answer_text }}
- Quote: {{ generate_answer_from_source_2.source_quote }}

**Source Material**:
The source material

## YOUR TASK

1. **Check alignment**: Does each answer match its quote and the source?
2. **Choose or synthesize**: Select the best answer (or synthesize ONLY from supported facts).
3. **Validate correctness**: Decide if the final answer is fully supported by the source.
4. **Pick the best quote**: Use a single exact quote that directly supports the final answer.

## OUTPUT FORMAT

Return ONLY this exact JSON structure:

```json
{
  "final_answer_text": "Consolidated answer (2-4 sentences)",
  "final_source_quote": "Single best direct quote from source",
  "validity": "valid",
  "validity_reason": "Brief explanation for validity decision",
  "selected_answerer": "1"
}
```

## REQUIREMENTS

- **Grounded only**: Use only information present in the source material
- **Strict quote matching**: Quote must be exact text from the source
- **Validity**: Set `validity` to "invalid" if the answer is not fully supported
- **Selected answerer**: Use "1", "2", "both" (synthesized), or "none" (if invalid)

{end_prompt}

{prompt Compose_Authoring_Prompt}
You are drafting an **authoring prompt** for a staff/senior engineer exam question.

## INPUTS

You have access to:
- **{{ consolidate_answer_from_source.final_answer_text }}** - The correct answer to align with
- **{{ consolidate_answer_from_source.final_source_quote }}** - Primary grounding (verbatim quote from documentation)

## TASK

1. Decide the best quiz style (APPLICATION, UNDERSTANDING, IMPLEMENTATION, ANALYSIS) based on the answer and quote.
2. Produce a compact, high-signal authoring prompt tailored to that style (no boilerplate).
3. Suggest a DIVERSE and SPECIFIC scenario opener that:
   - Uses concrete technical terms from the source quote
   - Varies in structure (avoid starting with "Imagine a scenario where...")
   - Sounds like a real engineering situation
   - Is 8-15 words long

## CONSTRAINTS

- Do not introduce new concepts outside the source quote
- Use precise terms from the source quote when possible
- Keep the authoring prompt under 120 words
- IMPORTANT: Make each scenario opener UNIQUE - vary the sentence structure and approach

## SCENARIO OPENER EXAMPLES (for variety)

- "Your team is implementing [specific technical concept]..."
- "During a code review, you notice [specific issue]..."
- "A production incident occurs when [specific condition]..."
- "You're designing [specific system] and need to consider..."
- "An engineer asks why [specific design decision] was made..."
- "While debugging, you discover [specific behavior]..."

## OUTPUT

Return JSON only:
```json
{
  "authoring_prompt": "2-6 short sentences, tailored to the chosen style.",
  "suggested_opener": "Short scenario opener phrase (8-15 words, UNIQUE structure).",
  "quiz_type_used": "APPLICATION | UNDERSTANDING | IMPLEMENTATION | ANALYSIS"
}
```
{end_prompt}

{prompt Write_Scenario_Question}
You are writing a **staff/senior engineer level** certification exam question.

Target: Engineers with 8+ years experience who know the basics. Test DEEP understanding.

## RAW KNOWLEDGE (You MUST base your question on this)

**Answer to align with:**
{{ consolidate_answer_from_source.final_answer_text }}

**Source quote (primary grounding):**
{{ consolidate_answer_from_source.final_source_quote }}

**Full source page (for precise phrasing only):**
{{ source.page_content }}

## GROUNDING REQUIREMENTS (CRITICAL)

Your question MUST:
1. Test the EXACT concept from the source quote above
2. Have a correct answer that aligns with the answer provided
3. NOT introduce new concepts, constraints, or requirements not in the source
4. NOT test related but different knowledge
5. Use specific terms/values from the source quote when applicable

If the source quote says "IDs MUST NOT be reused", your question tests ID reuse - not session management in general.

If **final_source_quote** is missing or empty, return this exact JSON and nothing else:
{"error": "missing_final_source_quote"}

## AUTHORING INSTRUCTIONS

{{ get_authoring_prompt.authoring_prompt }}

## SCENARIO OPENER

"{{ get_authoring_prompt.suggested_opener }}"

**Quiz Type:** {{ get_authoring_prompt.quiz_type_used }}

## STAFF ENGINEER QUESTION REQUIREMENTS

### Scenario (2-3 sentences)
- Present a **realistic production situation** with specific constraints
- Include technical context (scale, existing architecture, team situation)
- The problem should require UNDERSTANDING, not just recall

### Distractors (3 wrong options)
Each wrong option must be:
- **Technically plausible** - would work in a DIFFERENT situation
- **Subtly wrong** - differs by one critical detail
- **Not obviously wrong** - a junior might pick it

Distractor patterns for senior-level questions:
1. **Right concept, wrong context** - correct for a different protocol/version
2. **Partially correct** - misses one critical requirement
3. **Common misconception** - what people assume but is wrong
4. **Overkill solution** - technically works but violates a constraint

### Question Stem
- End with action-oriented question: "What should you do?" / "Which approach..."
- NOT "What is..." or "Which statement describes..."

## OUTPUT FORMAT

```json
{
  "question": "Concise scenario (2-3 sentences, ONE specific detail) + action question stem.",
  "options": [
    "Option A: 15-25 words with specific technical detail",
    "Option B: 15-25 words, plausible alternative (similar length to A)",
    "Option C: 15-25 words, technically credible but incorrect (similar length)",
    "Option D: 15-25 words, common misconception (similar length)"
  ],
  "answer": "For SA: single letter A-D. For MA: comma-separated letters like A,C.",
  "question_type": "SA or MA",
  "answer_explanation": "Explain WHY the correct answer solves the problem. Focus on the technical reasoning."
}
```

**CRITICAL**:
- Count words in each option. All 4 must be within ±5 words of each other.
- Do NOT add any extra text to `answer` (no labels like 'for SA/MA').
- Match `question_type` to `answer` format (SA = one letter; MA = multiple letters).

**ANSWER EXPLANATION RULES**:
- ✅ Write a plain text paragraph explaining why the correct answer works
- ✅ Focus on the technical principle and reasoning
- ❌ Do NOT use JSON keys, bullet points, or structured formatting
- ❌ Do NOT reference option letters (A, B, C, D) - options will be randomized
- ❌ Do NOT explain why other options are wrong - we handle that separately

**Good**: "Capability negotiation during initialization ensures both client and server know which features are available before attempting to use them. This prevents runtime failures from unsupported operations."

**Bad**: "Correct: Option A works because... Why B fails: ... Why C fails: ..."

## ANTI-PATTERNS TO AVOID

❌ "Which statement BEST describes..." (too academic)
❌ Obviously wrong options ("ignore all requirements")
❌ Verbose scenarios with unnecessary context
❌ Options that differ only in wording, not substance
❌ "All of the above" / "None of the above"
❌ Unbalanced option lengths (correct answer much longer than distractors)
❌ Multiple specific metrics in scenario (pick ONE illustrative detail, not 5)

## OPTION LENGTH BALANCE (CRITICAL)

All 4 options MUST be similar length (within 20% word count). If correct answer is 25 words, distractors should be 20-30 words.

**Bad Example** (giveaway):
- A: "Configure capability advertisement during initialization with validation checks and telemetry" (11 words)
- B: "Retry" (1 word)
- C: "Ignore" (1 word)
- D: "Rollback" (1 word)

**Good Example** (balanced):
- A: "Advertise capabilities during initialization and validate before use" (8 words)
- B: "Enable capabilities on-demand when servers request them" (7 words)
- C: "Skip negotiation and handle errors at runtime" (7 words)
- D: "Let servers assume capabilities are available by default" (8 words)

## SCENARIO CONCISENESS

Use ONE specific detail to ground the scenario, not multiple metrics:

**Bad**: "error rate rose from 0.5% to 12%, host logs show JSON-RPC errors, message drops increased from 0.1% to 8%"

**Good**: "error logs show 'unexpected notification' and 'tool not advertised' messages"
{end_prompt}

{prompt Generate_Distractor_1}
You are generating the FIRST distractor for this multiple-choice question.

## CONTEXT (Ground your understanding in the source material)

**Source Quote (primary grounding):**
{{ consolidate_answer_from_source.final_source_quote }}

**Full source context (for surrounding details):**
{{ source.page_content }}

**Correct answer explanation:**
{{ add_answer_text.answer_explanation }}

Use the source quote to identify the core concept. Use surrounding context to find related technologies/services that could be confused. The answer explanation shows the reasoning path.

## WORD COUNT CONSTRAINT (CRITICAL - MUST FOLLOW)

Correct answer word count: {{ suggest_distractor_counts.target_word_counts.correct_answer_words }} words
Your distractor constraint: {{ suggest_distractor_counts.target_word_counts.distractor_1 }}

{% if suggest_distractor_counts.target_word_counts.distractor_1 == "lesser_than" %}
Your distractor must be SHORTER: Write {{ suggest_distractor_counts.target_word_counts.correct_answer_words - 2 }} to {{ suggest_distractor_counts.target_word_counts.correct_answer_words - 1 }} words (at least 2 words less than correct answer)
{% elif suggest_distractor_counts.target_word_counts.distractor_1 == "equal_to" %}
Your distractor must match length: Write exactly {{ suggest_distractor_counts.target_word_counts.correct_answer_words }} words (same as correct answer)
{% elif suggest_distractor_counts.target_word_counts.distractor_1 == "greater_than" %}
Your distractor must be LONGER: Write {{ suggest_distractor_counts.target_word_counts.correct_answer_words + 2 }} to {{ suggest_distractor_counts.target_word_counts.correct_answer_words + 4 }} words (at least 2 words more than correct answer)
{% endif %}

Correct answer for reference ({{ suggest_distractor_counts.target_word_counts.correct_answer_words }} words):
"{{ add_answer_text.answer_text[0] }}"

Count your words carefully before submitting.

## DISTRACTOR REQUIREMENTS

Write a distractor that:
1. Attempts to solve the question (not just random wrong text)
2. Would be valid in another scenario but has a critical caveat here
3. Is wrong because it uses the wrong technology or service (find alternatives from source context)
4. Matches the style and pattern of the correct answer
5. STRICTLY follows the word count constraint above

Guidelines:
- Focus on technology or service confusion
- Be plausible and technically credible
- Ground your distractor in concepts from the source material
- Do not escape or duplicate special characters in your output

Output:
{
  "distractor_1": "<your distractor text>",
  "explanation_why_it_is_incorrect_1": "<why this is wrong>",
  "thinking_process_1": "<your reasoning>"
}
{end_prompt}


{prompt Generate_Distractor_2}
You are generating the SECOND distractor for this multiple-choice question.

## CONTEXT (Ground your understanding in the source material)

**Source Quote (primary grounding):**
{{ consolidate_answer_from_source.final_source_quote }}

**Full source context (for surrounding details):**
{{ source.page_content }}

**Correct answer explanation:**
{{ add_answer_text.answer_explanation }}

Use the source quote to identify the core concept. Use surrounding context to find related approaches/concepts that could be confused. The answer explanation shows the reasoning path.

## WORD COUNT CONSTRAINT (CRITICAL - MUST FOLLOW)

Correct answer word count: {{ suggest_distractor_counts.target_word_counts.correct_answer_words }} words
Your distractor constraint: {{ suggest_distractor_counts.target_word_counts.distractor_2 }}

{% if suggest_distractor_counts.target_word_counts.distractor_2 == "lesser_than" %}
Your distractor must be SHORTER: Write {{ suggest_distractor_counts.target_word_counts.correct_answer_words - 2 }} to {{ suggest_distractor_counts.target_word_counts.correct_answer_words - 1 }} words (at least 2 words less than correct answer)
{% elif suggest_distractor_counts.target_word_counts.distractor_2 == "equal_to" %}
Your distractor must match length: Write exactly {{ suggest_distractor_counts.target_word_counts.correct_answer_words }} words (same as correct answer)
{% elif suggest_distractor_counts.target_word_counts.distractor_2 == "greater_than" %}
Your distractor must be LONGER: Write {{ suggest_distractor_counts.target_word_counts.correct_answer_words + 2 }} to {{ suggest_distractor_counts.target_word_counts.correct_answer_words + 4 }} words (at least 2 words more than correct answer)
{% endif %}

Correct answer for reference ({{ suggest_distractor_counts.target_word_counts.correct_answer_words }} words):
"{{ add_answer_text.answer_text[0] }}"

Count your words carefully before submitting.

## PREVIOUS DISTRACTOR (Avoid repetition)

Previously generated:
- **Distractor 1:** {{ generate_distractor_1.distractor_1 }}
- **Why it's wrong:** {{ generate_distractor_1.explanation_why_it_is_incorrect_1 }}

Your new distractor must be DIFFERENT in approach and reasoning.

## DISTRACTOR REQUIREMENTS

Write a NEW distractor that:
1. Attempts to solve the question
2. Would be valid in another scenario but has a critical caveat here
3. Is wrong because it uses the wrong approach or concept (not just wrong tech like distractor 1)
4. Matches the style and pattern of the correct answer
5. STRICTLY follows the word count constraint above
6. Does NOT repeat the reasoning from distractor 1

Guidelines:
- Focus on approach or concept confusion (different from distractor 1)
- Be plausible and technically credible
- Ground your distractor in concepts from the source material
- Do not escape or duplicate special characters in your output
6. Differs from distractor_1 and uses a different mistake pattern
7. Uses the source quote and answer explanation as your guide

Guidelines:
- Focus on approach or concept confusion
- Be plausible and technically credible
- Do not escape or duplicate special characters in your output

Output:
{
  "distractor_2": "<your DIFFERENT distractor text>",
  "explanation_why_it_is_incorrect_2": "<why this is wrong>",
  "thinking_process_2": "<your reasoning>"
}
{end_prompt}


{prompt Generate_Distractor_3}
You are generating the THIRD and final distractor for this multiple-choice question.

## CONTEXT (Ground your understanding in the source material)

**Source Quote (primary grounding):**
{{ consolidate_answer_from_source.final_source_quote }}

**Full source context (for surrounding details):**
{{ source.page_content }}

**Correct answer explanation:**
{{ add_answer_text.answer_explanation }}

Use the source quote to identify the core concept. Use surrounding context to find edge cases or common misconceptions. The answer explanation shows the reasoning path.

## WORD COUNT CONSTRAINT (CRITICAL - MUST FOLLOW)

Correct answer word count: {{ suggest_distractor_counts.target_word_counts.correct_answer_words }} words
Your distractor constraint: {{ suggest_distractor_counts.target_word_counts.distractor_3 }}

{% if suggest_distractor_counts.target_word_counts.distractor_3 == "lesser_than" %}
Your distractor must be SHORTER: Write {{ suggest_distractor_counts.target_word_counts.correct_answer_words - 2 }} to {{ suggest_distractor_counts.target_word_counts.correct_answer_words - 1 }} words (at least 2 words less than correct answer)
{% elif suggest_distractor_counts.target_word_counts.distractor_3 == "equal_to" %}
Your distractor must match length: Write exactly {{ suggest_distractor_counts.target_word_counts.correct_answer_words }} words (same as correct answer)
{% elif suggest_distractor_counts.target_word_counts.distractor_3 == "greater_than" %}
Your distractor must be LONGER: Write {{ suggest_distractor_counts.target_word_counts.correct_answer_words + 2 }} to {{ suggest_distractor_counts.target_word_counts.correct_answer_words + 4 }} words (at least 2 words more than correct answer)
{% endif %}

Correct answer for reference ({{ suggest_distractor_counts.target_word_counts.correct_answer_words }} words):
"{{ add_answer_text.answer_text[0] }}"

Count your words carefully before submitting.

## PREVIOUS DISTRACTORS (Avoid repetition)

**Distractor 1:**
- Text: {{ generate_distractor_1.distractor_1 }}
- Why wrong: {{ generate_distractor_1.explanation_why_it_is_incorrect_1 }}

**Distractor 2:**
- Text: {{ generate_distractor_2.distractor_2 }}
- Why wrong: {{ generate_distractor_2.explanation_why_it_is_incorrect_2 }}

Your new distractor must be DIFFERENT from both in approach and reasoning.

## DISTRACTOR REQUIREMENTS

Write a NEW distractor that:
1. Attempts to solve the question
2. Would be valid in another scenario but has a critical caveat here
3. Is wrong due to an edge case or common misconception (different from distractors 1 & 2)
4. Matches the style and pattern of the correct answer
5. STRICTLY follows the word count constraint above
6. Does NOT repeat the reasoning from distractors 1 or 2

Guidelines:
- Focus on edge cases, partial solutions, or common misconceptions
- Be plausible and technically credible
- Ground your distractor in concepts from the source material
- Do not escape or duplicate special characters in your output

Output:
{
  "distractor_3": "<your DIFFERENT distractor text>",
  "explanation_why_it_is_incorrect_3": "<why this is wrong>",
  "thinking_process_3": "<your reasoning>"
}
{end_prompt}


{prompt Score_Question_Quality}
# Question Quality Scoring - {{ seed.exam_syllabus.exam_name }}

You are an expert exam question reviewer evaluating practice questions for the {{ seed.exam_syllabus.exam_name }}.

## SPECIFIC LEARNING OBJECTIVES FOR THIS QUESTION

This question was generated from content supporting the following specific learning objectives:

{% for ref in source.referenced_in %}
Section: {{ ref.section_name }}
Objective: {{ ref.objective }}
Relevance: {{ ref.relevance }}

{% endfor %}

Evaluate whether this question tests one or more of these specific objectives.

## EXAM SYLLABUS REFERENCE

```json
{{ seed.exam_syllabus }}
```

## YOUR TASK

Evaluate the provided question and score it based on how well it tests the specific learning objectives listed above.

## INPUT

- Question: {question}
- Options: {options}
- Answer: {answer}
- Explanation: {answer_explanation}

## SCORING CRITERIA (0-100)

1. Objective Alignment (60 points)
- 50-60: Directly tests a specific objective with clear measurement of achievement
- 35-49: Tests an objective but measurement is indirect or unclear
- 15-34: Loosely related to an objective but does not clearly test it
- 0-14: Does not test any of the specific objectives listed

2. Hands-on or Implementation Focus (25 points)
- 20-25: Tests hands-on implementation skills for the objective
- 10-19: Tests some practical application but lacks implementation depth
- 0-9: Purely theoretical

3. Technical Specificity (15 points)
- 12-15: Uses specific technical details from the objective domain
- 6-11: Some technical specificity but could be more concrete
- 0-5: Too generic

Overall scoring guide:
- 85-100: Directly tests a specific objective with hands-on details
- 70-84: Tests an objective with good specificity but less hands-on focus
- 50-69: Related to objectives but does not clearly test objective achievement
- 0-49: Not aligned with the specific objectives

## OUTPUT

Provide exactly 4 fields:
1. syllabus_alignment_score (0-100)
2. objective_tested: quote the objective(s)
3. aligned_skill_area: topic area from the syllabus
4. reasoning (2-3 sentences)

Questions scoring >= 85 will be kept. Questions scoring < 85 will be filtered out.
{end_prompt}


{prompt Validate_Answer_From_Source}
You are a quiz validation expert. Your task is to answer a multiple-choice question based only on the provided source documentation.

## SOURCE DOCUMENTATION

{{ source.page_content }}

## QUESTION

{{ write_scenario_question.question }}

## OPTIONS

{% for option in reconstruct_options.options %}
{{ loop.index | string | replace('1', 'A') | replace('2', 'B') | replace('3', 'C') | replace('4', 'D') | replace('5', 'E') }}. {{ option }}
{% endfor %}

## YOUR TASK

Read the source documentation carefully, then answer the question by selecting the correct option(s).

Instructions:
1. Base your answer only on the source documentation provided
2. If the answer is not clearly supported by the documentation, make your best inference
3. For single-answer questions, respond with one letter (e.g., "A")
4. For multiple-answer questions, respond with comma-separated letters (e.g., "A,C")
5. Provide clear reasoning that references specific parts of the source documentation
6. Include an exact quote from the source documentation that supports your answer

## OUTPUT FORMAT

```json
{
  "predicted_answer": "A",
  "reasoning": "Based on the documentation, option A is correct because...",
  "supporting_quotes": [
    "First verbatim excerpt from the source documentation.",
    "Second verbatim excerpt that provides additional support."
  ]
}
```

CRITICAL:
- Only use letters A, B, C, D, E (depending on number of options)
- Your reasoning must reference the source documentation
- supporting_quotes must be an array of 1-3 verbatim excerpts from the source
{end_prompt}


{prompt Feynman_Explanation_Generator}
You are an expert educator creating Feynman-style explanations that help students understand why the correct answer solves this specific question.

Avoid referencing option letters (A, B, C, D). Options will be randomized.

## YOUR INPUTS
- Question
- Options
- Correct Answer
- Answer Explanation
- Source Quote
- Source Page Content

## FEYNMAN TECHNIQUE PRINCIPLES
1. Question-focused approach: explain what the question is really asking
2. Answer-specific reasoning: show why the correct answer fits this scenario
3. Make it memorable: use one analogy consistently

## EXPLANATION STRUCTURE
- Question Breakdown (2-3 sentences)
- The Core Problem (1-2 paragraphs)
- Why This Answer Works (2-3 paragraphs)
- Key Takeaway (1 paragraph)

## CRITICAL RULES
1. Focus on this question and this answer only
2. Do not explain why other options are wrong
3. Use one main analogy throughout
4. Ground reasoning in the source quote and page content
5. Do not escape or duplicate special characters

## OUTPUT SCHEMA

```json
{
  "question_explanation": "Clear breakdown of what the question scenario is asking using analogy",
  "answer_reasoning": "Detailed explanation of why the correct answer solves this specific problem",
  "key_concept_analogy": "The main analogy used to explain the concept",
  "memorable_takeaway": "One key insight students can remember for similar questions"
}
```
{end_prompt}


{prompt Generate_Concept_Explanation}
You are a senior technical educator writing concept explanations for staff/senior engineers preparing for certification exams.

Your task is to explain the underlying technical concept being tested by this question, not why the answer is correct.

## YOUR INPUTS
- Question
- Correct Answer
- Answer Explanation
- Source Quote
- Source Page Content

## CONCEPT EXPLANATION REQUIREMENTS
1. Teach the concept, not the answer
2. Production-level depth: implementation considerations, pitfalls, trade-offs
3. Staff engineer perspective

## FORMAT
Write 2-4 paragraphs in clear prose. No bullet points.

## OUTPUT SCHEMA

```json
{
  "concept_explanation": "2-4 paragraph explanation of the underlying concept, its production implications, and key considerations"
}
```

## CRITICAL RULES
1. Do not reference the specific question or answer options
2. Do not use phrases like "this question tests" or "the correct answer is"
3. Ground your explanation in the source documentation provided
{end_prompt}
