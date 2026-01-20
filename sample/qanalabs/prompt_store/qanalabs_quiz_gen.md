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

1. **NO BASIC RECALL**: Skip "What is X?" - focus on "What happens when...", "Why must...", "What breaks if..."
2. **EDGE CASES**: Prioritize constraints, limitations, error conditions
3. **SPECIFICITY**: Include exact values, error codes, parameter names
4. **IMPLICATIONS**: Focus on what the requirement MEANS for implementation

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


{prompt Classify_Question_Type}
{{ seed.exam_syllabus.exam_name }}
You are classifying a question-answer pair into one of four certification question types.

## THE QUESTION TO CLASSIFY

**Question**: {{ flatten_raw_questions.question_text }}
**Answer**: {{ flatten_raw_questions.answer_text }}

## QUESTION TYPES

Choose the BEST fit:

**APPLICATION** - Tests practical configuration/workflow selection
- "Which service should you use for X?"
- "What approach should you take when Y?"
- Best for: Feature selection, workflow decisions, tool choices

**UNDERSTANDING** - Tests conceptual comprehension
- "What is the purpose of X?"
- "Which statement best describes Y?"
- Best for: Definitions, purposes, characteristics, benefits

**IMPLEMENTATION** - Tests specific commands/parameters/steps
- "What command should you use?"
- "Which parameter configures X?"
- Best for: CLI commands, API calls, configuration syntax, step-by-step procedures

**ANALYSIS** - Tests diagnostic/troubleshooting reasoning
- "What is the most likely cause of X?"
- "How should you resolve this error?"
- Best for: Error analysis, performance issues, debugging scenarios

## OUTPUT

```json
{
  "quiz_type": "APPLICATION|UNDERSTANDING|IMPLEMENTATION|ANALYSIS",
  "classification_reason": "Brief explanation of why this type fits best"
}
```

Choose the type that will produce the most effective exam question for this knowledge.
{end_prompt}


{prompt Write_Scenario_Question}
You are writing a **staff/senior engineer level** certification exam question.

Target: Engineers with 8+ years experience who know the basics. Test DEEP understanding.

## RAW KNOWLEDGE (You MUST base your question on this)

Your context includes:
- **question_text**: The core concept/question to test
- **answer_text**: The correct answer that your question must align with
- **source_quote**: Verbatim quote from documentation - your question MUST be grounded in this
- **difficulty_reason**: Why this tests senior-level understanding
- **quiz_type**: The question format (SA/MA/etc)

## GROUNDING REQUIREMENTS (CRITICAL)

Your question MUST:
1. Test the EXACT concept from the Core Concept and Source Quote above
2. Have a correct answer that aligns with the Correct Answer provided
3. NOT introduce new concepts, constraints, or requirements not in the source
4. NOT test related but different knowledge
5. Use specific terms/values from the Source Quote when applicable

If the Source Quote says "IDs MUST NOT be reused", your question tests ID reuse - not session management in general.

## AUTHORING INSTRUCTIONS

{{ get_authoring_prompt.authoring_prompt }}

## SCENARIO OPENER

"{{ get_authoring_prompt.suggested_opener }}"

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
  "answer": "A for SA, or A,C for MA (comma-separated)",
  "question_type": "SA or MA",
  "answer_explanation": "Explain WHY the correct answer solves the problem. Focus on the technical reasoning."
}
```

**CRITICAL**: Count words in each option. All 4 must be within ±5 words of each other.

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



{prompt Fact_extraction}
Extract **atomic, testable facts** about {{ seed.exam_syllabus.platform_name }} that help with **implementation, configuration, or troubleshooting**.

## LEARNING OBJECTIVES CONTEXT

This content supports the following specific learning objectives:

{% for ref in source.referenced_in %}
**Section**: {{ ref.section_name }}
**Objective**: {{ ref.objective }}
**Relevance**: {{ ref.relevance }}

{% endfor %}

⚠️ **CRITICAL**: Extract facts that **directly support these objectives**. Each fact must help learners achieve at least one of the objectives listed above.

## TARGET AUDIENCE PROFILE

**Exam**: {{ seed.exam_syllabus.exam_name }}

{{ seed.exam_syllabus.audience_profile.description }}

**Target Responsibilities**:
{% for resp in seed.exam_syllabus.audience_profile.responsibilities %}
- {{ resp }}
{% endfor %}

**Assumed Prerequisites** (assume learners already have this knowledge):
{% for req in seed.exam_syllabus.audience_profile.required_knowledge %}
- {{ req }}
{% endfor %}

⚠️ **CRITICAL PREREQUISITE HANDLING**:
- **DO NOT EXPLAIN** what prerequisites are (e.g., ❌ "SQL is a query language", ❌ "Git is version control")
- **DO EXTRACT** advanced facts that APPLY prerequisite knowledge to {{ seed.exam_syllabus.platform_name }}
  - Example: If prerequisite is "SQL proficiency" → ✅ Extract "{{ seed.exam_syllabus.platform_name }} query optimizer uses statistics for join order selection"
  - Example: If prerequisite is "Git workflows" → ✅ Extract "{{ seed.exam_syllabus.platform_name }} requires signed commits for production deployments"
- **FOCUS** on how prerequisites are APPLIED within {{ seed.exam_syllabus.platform_name }} context
- **PRIORITIZE** facts that help professionals perform target responsibilities

## Keep (✅)

  * Config details (auth headers, params, roles, SKUs)
  * Implementation (APIs, SDKs, endpoints, CLI/ARM/Bicep)
  * Constraints (quotas, limits, regions, preview/restrictions)
  * Procedures (steps for setup/deployment)
  * Cost/performance factors (scaling, pricing units)
  * Security/errors (codes, retry logic, compliance rules)
  * Protocol requirements (MUST/SHOULD directives with technical details)

## Skip (❌)

  * Marketing/benefits
  * Generic "can be used to…" statements
  * Industry use cases without service/API specifics
  * Documentation locations, URLs, or navigation paths
  * Website structure or UI elements
  * Version numbers or release dates without technical impact
  * General descriptions without actionable technical details
  * **Introductory/basic concepts** (what is X, basic definitions, getting started)
  * **Entry-level explanations** suitable for beginners or juniors
  * **Fundamental prerequisites** that mid/senior professionals already know
  * **Basic terminology** without advanced implementation details
  * **Overview content** that doesn't go beyond surface level
  * **Facts not aligned with the learning objectives** listed above

## Rules

  1. Must name a specific `{{ seed.exam_syllabus.platform_name }}` service, API, or feature.
  2. Include concrete detail (param, limit, SKU, region, header, method, code).
  3. One fact = one claim, standalone.
  4. Prefer facts with numbers/parameters/error codes.
  5. 3–10 facts max, or skip with reason.
  6. **Test each fact**: Could this create a technical implementation question?
  7. **Avoid meta-facts**: Facts about documentation, websites, or where to find information
  8. **Prerequisite Test**: Does this fact EXPLAIN what a prerequisite is? If yes, SKIP it. Does it show ADVANCED APPLICATION of prerequisite knowledge? If yes, KEEP it.
  9. **Responsibility Alignment**: Does this fact help someone perform one of the target responsibilities? If no, skip it.
  10. **Production Relevance**: Focus on facts relevant to enterprise/production systems and architect-level decisions.
  11. **Objective Alignment Test**: For each fact, ask "Does this directly help someone achieve one of the objectives listed above?" If no, skip it.

## Examples

### ✅ Good Facts - Should:
  - Support one or more target responsibilities:
{% for resp in seed.exam_syllabus.audience_profile.responsibilities %}
    - {{ resp }}
{% endfor %}
  - Include specific {{ seed.exam_syllabus.platform_name }} configuration, implementation, or constraint details
  - Contain concrete technical details (numbers, limits, syntax, procedures, error codes)
  - Focus on production/enterprise-level usage, not tutorials

### ❌ Bad Facts - Should NOT:
  - **EXPLAIN** what prerequisites are (e.g., defining what these concepts mean):
{% for req in seed.exam_syllabus.audience_profile.required_knowledge %}
    - ❌ Don't explain: {{ req }}
{% endfor %}
  - Define basic terminology or acronyms (e.g., "X stands for...", "X is a...")
  - Reference documentation locations, URLs, or UI navigation
  - Provide generic statements without {{ seed.exam_syllabus.platform_name }}-specific details

**HOWEVER**, DO extract facts showing ADVANCED APPLICATION of prerequisite knowledge:
{% for req in seed.exam_syllabus.audience_profile.required_knowledge %}
  - ✅ Extract advanced {{ req }} usage within {{ seed.exam_syllabus.platform_name }} context
{% endfor %}

## Output

```json
{
  "candidate_facts_list": [
    {
      "fact": "string ≤150 chars with technical detail",
      "quote": "short verbatim evidence",
      "technical_level": "configuration|implementation|constraint|procedure|integration",
      "supports_objective": "Which specific objective from the list above this fact supports"
    }
  ]
}
```

Skip format:

```json
{
  "candidate_facts_list": [],
  "skip_reason": "No testable {{ seed.exam_syllabus.platform_name }} technical details aligned with learning objectives and appropriate for target audience (e.g., only prerequisite explanations found)"
}
```

{end_prompt}



{prompt Canonicalize_Facts}
You are a fact canonicalization agent. Your task is to identify duplicate or near-duplicate facts within the extracted candidate facts list and produce a single canonical version for each group of duplicates.

## INPUT STRUCTURE:
- `candidate_facts_list`: Array of facts extracted from a single source document
- Each fact contains:
  - `fact`: The technical statement
  - `quote`: Supporting evidence
  - `technical_level`: Type of content
  - `supports_objective`: Which learning objective it supports

## YOUR TASK:

### 1. Identify Semantic Duplicates
Review all facts and identify groups where multiple facts express **the same core information**:
- **Exact duplicates**: Identical or nearly identical wording
- **Paraphrased duplicates**: Same information, different wording
- **Partial overlaps**: One fact is a subset/superset of another

### 2. Create Canonical Facts
For each group of duplicates:
- **Select or synthesize** the best canonical version that:
  - Contains the most complete information
  - Uses the clearest, most precise wording
  - Preserves technical accuracy
  - Stays within 250 character limit

### 3. Preserve Metadata
For the canonical fact:
- Choose the most comprehensive `quote` from the group
- Keep the `technical_level` from the most specific fact
- Merge `supports_objective` if duplicates support multiple objectives

## DECISION RULES:

**MERGE these as duplicates:**
- ✅ "dbt uses OAuth for authentication" + "OAuth authentication is used in dbt" → SAME FACT
- ✅ "IP whitelist controls access" + "Access is controlled via IP whitelist" → SAME FACT
- ✅ "Jobs can be scheduled" + "You can schedule jobs to run at specific times" → SAME FACT (second is more detailed, keep it)

**KEEP these as separate:**
- ❌ "OAuth requires Client ID" + "OAuth requires Client Secret" → DIFFERENT FACTS
- ❌ "Development environment uses custom branch" + "Production environment uses main branch" → DIFFERENT FACTS
- ❌ "CI jobs use deferral" + "Production jobs use deferral" → DIFFERENT FACTS

## OUTPUT FORMAT:

Return the deduplicated facts using the same `candidate_facts_list` schema as input:

```json
{
  "candidate_facts_list": [
    {
      "fact": "Canonical/deduplicated version of the fact",
      "quote": "Best supporting quote from merged group",
      "technical_level": "configuration",
      "supports_objective": "Objective identifier"
    }
  ]
}
```

**Important**:
- Output uses the SAME `candidate_facts_list` schema as the input
- If NO duplicates found, return all facts unchanged
- Prioritize **accuracy** over aggressive merging - when in doubt, keep facts separate

{end_prompt}



{prompt Cluster_Validation_Agent}
  You are a validation agent responsible for verifying whether facts in a similarity group should remain together or be split based on their semantic uniqueness.

  ## Input Structure:
  - `grouped_facts`: A list where each fact includes:
    - `semantic_unique_id`: UUID identifying semantically identical facts (facts with the same ID are exact duplicates)
    - `fact`: Concise technical statement
    - `quote`: Supporting quote from source material
    - `technical_level`: One of ["constraint", "implementation", "performance", "configuration", "procedure", "integration"]
  - `similarity_group_id`: UUID for the current similarity-based grouping
  - `num_similar_facts`: Count of facts in this group
  - `exam_name`: Target certification exam

  ## Your Task:
  1. **Semantic Analysis**: Determine if all facts in `grouped_facts` belong together based on:
     - Topic coherence: Do facts cover the same specific concept/feature?
     - Semantic uniqueness: Facts with different `semantic_unique_id` should have genuinely different meanings
     - Technical relationship: Are facts related as parts of the same workflow/system?

  2. **If facts belong together** (cohesive single concept):
     - Set `should_keep_cluster: true`
     - Leave `new_clusters: []` as empty array
     - Provide reasoning explaining why they form a coherent cluster

  3. **If facts should be split** (multiple distinct concepts):
     - Set `should_keep_cluster: false`
     - Create `new_clusters` array grouping facts by `semantic_unique_id`
     - Each new cluster should contain `semantic_unique_id` values that belong together
     - Provide reasoning explaining the semantic differences

  ## Output Schema:
  ```json
  {
    "should_keep_cluster": <true | false>,
    "reasoning": "<detailed explanation of semantic analysis>",
    "new_clusters": [
      {
        "cluster_name": "descriptive_name_1",
        "semantic_unique_ids": ["uuid1", "uuid2"]
      },
      {
        "cluster_name": "descriptive_name_2",
        "semantic_unique_ids": ["uuid3"]
      }
    ]
  }
  ```

  ## Guidelines:

  * **Keep together**: Facts about the same specific feature/service with complementary details
  * **Split apart**: Facts covering different features, services, or unrelated constraints
  * **Semantic uniqueness matters**: Different `semantic_unique_id` values indicate distinct facts - verify they truly differ in meaning
  * **Technical level is a signal**: Mixed levels (e.g., "constraint" + "performance") may indicate different concepts
  * **Be detailed in reasoning**: Explain what makes facts similar or different semantically

  ## Output Only:

  Respond with valid JSON matching the schema. No explanations outside the JSON structure.


{end_prompt}







{prompt Summary_Generator}
You are an expert creating self-contained educational summaries for {{ seed.exam_syllabus.exam_name }} quiz questions.

## LEARNING OBJECTIVES CONTEXT

This content supports the following specific learning objectives:

{% for ref in source.referenced_in %}
**Section**: {{ ref.section_name }}
**Objective**: {{ ref.objective }}
**Relevance**: {{ ref.relevance }}

{% endfor %}

⚠️ **CRITICAL**: Your summary must directly address these objectives. Structure your content to help learners achieve each objective listed above.

## TARGET AUDIENCE PROFILE

**Exam**: {{ seed.exam_syllabus.exam_name }}

{{ seed.exam_syllabus.audience_profile.description }}

**Target Responsibilities**:
{% for resp in seed.exam_syllabus.audience_profile.responsibilities %}
- {{ resp }}
{% endfor %}

**Assumed Prerequisites** (learners already have this knowledge):
{% for req in seed.exam_syllabus.audience_profile.required_knowledge %}
- {{ req }}
{% endfor %}

⚠️ **CRITICAL PREREQUISITE HANDLING**:
- **DO NOT EXPLAIN** what prerequisites are (no "SQL is...", "Git allows...", "OAuth is...")
- **DO INCLUDE** advanced application of prerequisites within {{ seed.exam_syllabus.platform_name }} context
  - Example: If prerequisite is "SQL proficiency" → ✅ "Use CTEs for complex query optimization in {{ seed.exam_syllabus.platform_name }}"
  - Example: If prerequisite is "Git workflows" → ✅ "Configure branch protection rules for {{ seed.exam_syllabus.platform_name }} deployments"
- **FRAME** content around target responsibilities (designing, implementing, managing, administering)
- **FOCUS** on production/enterprise-level application, not basic tutorials

## INPUTS:
- **Page Content**: source.page_content - the source document to summarize (do not add external information)
- **Learning Objectives**: source.referenced_in (the specific objectives this content addresses)

Read the page content carefully and extract the key technical information that supports the learning objectives.

## CORE RULES:

1. **Objective-Aligned**: Your summary must support the learning objectives listed above. Structure content to help learners achieve each stated objective.

2. **Self-Contained**: Write as THE definitive reference students will use. Never reference "the tutorial", "the documentation", "the example", "the page", or any external source.

3. **Direct & Concise**:
   - `summary`: 2-4 paragraphs synthesizing the facts into a comprehensive, self-contained educational narrative. Include key concepts, technical details, implementation specifics, procedures, and constraints. This single field serves as the definitive reference for quiz generation.
   - `code_snippets`: Only actual code from page_content (empty array if none exists)

4. **Writing Style**:
   - ❌ FORBIDDEN: "The tutorial shows...", "According to...", "The example demonstrates...", "As shown in...", "Use this when...", "First, understand that..."
   - ❌ FORBIDDEN: DEFINING what prerequisites are (e.g., "SQL is a query language", "Git is version control", "OAuth is authentication")
   - ❌ FORBIDDEN: Generic statements without {{ seed.exam_syllabus.platform_name }}-specific details
   - ✅ REQUIRED: Direct, responsibility-level statements with specific technical details
   - ✅ REQUIRED: Frame content around target responsibilities from audience profile
   - ✅ REQUIRED: Show ADVANCED APPLICATION of prerequisite knowledge within {{ seed.exam_syllabus.platform_name }} context

5. **Technical Level Adaptation** (based on grouped_facts technical_level):
   - **configuration**: Setup, parameters, settings needed
   - **implementation**: Step-by-step procedures, syntax, code
   - **constraint**: Limitations, requirements, prerequisites
   - **procedure**: Sequential steps, workflows
   - **integration**: How components work together

6. **Code Rules**:
   - Extract VERBATIM from page_content only
   - Empty array if no actual code exists
   - No pseudo-code or invented examples

7. **CRITICAL - Special Characters**: Do NOT escape or duplicate special characters (braces, brackets, quotes) in your output. Write technical syntax naturally.

## OUTPUT FORMAT

Return a JSON object with exactly 2 fields:

```json
{
  "summary": "A comprehensive, self-contained educational summary (2-4 paragraphs) that synthesizes all the grouped facts into a coherent narrative. Include key concepts, technical details, implementation specifics, and any relevant procedures or constraints. Frame content around the target responsibilities (designing, implementing, managing, administering). Use action-oriented language. Include specific technical details needed to perform the responsibilities. Assume all prerequisite knowledge from the audience profile.",
  "code_snippets": ["Array of actual code snippets extracted VERBATIM from page_content only. Empty array if no actual code exists. No pseudo-code or invented examples."]
}
```

## WRITING GUIDELINES

- Frame content around the target responsibilities (designing, implementing, managing, administering, etc.)
- Use action-oriented language matching the responsibility level
- Include specific technical details needed to perform the responsibilities
- Assume all prerequisite knowledge from the audience profile

## TONE EXAMPLES

❌ **Too Basic** (Explaining Prerequisites):
- Defining prerequisite concepts or technologies
- Explaining what basic terms mean
- "X is a [technology] that allows you to..."

✅ **Responsibility-Level** (Assumes Prerequisites):
- Focus on how to implement, configure, design, or manage
- Specific technical details for the target responsibilities
- Enterprise/production-level decision-making
- "To implement [responsibility], configure [specific technical detail]..."

Write as an expert architect teaching other architects. Present facts confidently. The summary should be comprehensive enough to serve as the sole reference for generating quiz questions.
{end_prompt}






{prompt Review_Code_Snippets}
You are a code snippet reviewer. Your task is to review the code_snippets array and determine which snippets contain ACTUAL executable code vs documentation/text.

KEEP snippets that contain:
- Actual code blocks (JSON, Python, JavaScript, Bash, YAML, SQL, etc.)
- Complete functions, classes, or code structures
- Configuration files (JSON, YAML, XML)
- API requests/responses with actual data
- Command-line examples that are executable

REMOVE snippets that are:
- Just field descriptions (e.g., "* `field`: Description text")
- Bullet point lists without executable code
- Plain text documentation
- Log messages or error messages (unless showing actual code context)
- Single-line field/property descriptions
- Markdown formatting without code substance

EXAMPLES:

KEEP:
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "completion/complete"
}
```

KEEP:
```python
def calculate_total(items):
    return sum(item.price for item in items)
```

REMOVE:
"* `role`: Either "user" or "assistant" to indicate the speaker"

REMOVE:
"* `completion`: Object containing:\n  + `values`: Array of suggestions"

REMOVE:
"Field description: The name of the user"

Return:
- code_snippets: Array containing ONLY snippets with actual code
- removed_snippets: Array of snippets that were removed
- removal_reasoning: Brief explanation of why snippets were removed
{end_prompt}


















{prompt Score_Summary_Quality}
You are an expert certification exam content reviewer evaluating educational summaries for the {{ seed.exam_syllabus.exam_name }}

## SPECIFIC LEARNING OBJECTIVES FOR THIS CONTENT

This content was created to support the following specific learning objectives:

{% for ref in source.referenced_in %}
**Section**: {{ ref.section_name }}
**Objective**: {{ ref.objective }}
**Relevance**: {{ ref.relevance }}

{% endfor %}

⚠️ **CRITICAL**: Evaluate how well the summary addresses THESE SPECIFIC OBJECTIVES, not just general exam topics.

## TARGET AUDIENCE PROFILE

{{ seed.exam_syllabus.audience_profile.description }}

**Target Responsibilities**:
{% for resp in seed.exam_syllabus.audience_profile.responsibilities %}
- {{ resp }}
{% endfor %}

**Assumed Prerequisites**:
{% for req in seed.exam_syllabus.audience_profile.required_knowledge %}
- {{ req }}
{% endfor %}

⚠️ **CRITICAL**: Penalize summaries that EXPLAIN what prerequisites are. Summaries CAN use prerequisites but should show ADVANCED APPLICATION within {{ seed.exam_syllabus.platform_name }} context, not basic definitions.

## EXAM SYLLABUS REFERENCE

You will also use the following official exam syllabus for broader context:

```json
{{ seed.exam_syllabus.exam_name }}
```

## YOUR TASK

Evaluate the provided summary and assign a quality score from 0-100 based on how well it helps learners achieve the specific objectives AND appropriateness for the target audience.

## INPUT DATA

- **Summary**: The comprehensive educational summary synthesizing the grouped facts
- **Code Snippets**: Code snippets extracted from the page content (if any)

## SCORING CRITERIA (0-100 points)

### 1. Objective Alignment (35 points) - MOST IMPORTANT
- Does the summary directly address the SPECIFIC objectives listed above?
- Does the content help learners achieve each stated objective?
- Is the summary focused on the objectives and their implementation?
- **Scoring Guide**:
  - 30-35: Directly and comprehensively addresses ALL specific objectives listed
  - 20-29: Addresses most specific objectives with good coverage
  - 10-19: Partially addresses some objectives but misses key elements
  - 0-9: Minimal alignment with the specific objectives

### 2. Implementation Specificity (30 points)
- Contains actual code snippets that help achieve the objectives
- Includes specific service names, parameters, commands needed for the objectives
- Provides configuration details, syntax, or procedures relevant to objectives
- Actionable content that enables learners to complete the objectives
- **Scoring Guide**:
  - 25-30: Rich code examples + specific configurations directly supporting objectives
  - 15-24: Some code OR detailed technical specifications for objectives
  - 5-14: Generic technical content without objective-specific details
  - 0-4: Purely conceptual, no implementation details for objectives

### 3. Technical Depth & Audience Appropriateness (20 points)
- Level of detail appropriate for achieving the objectives AND the target audience
- Goes beyond basic definitions to enable objective completion
- Addresses advanced scenarios, edge cases relevant to objectives
- **CRITICAL**: Does NOT DEFINE what prerequisites are - but CAN show advanced application of them
- **CRITICAL**: Written for target responsibility level, not beginners
- **Scoring Guide**:
  - 16-20: Advanced application of prerequisite knowledge; responsibility-level details; production-focused
  - 10-15: Appropriate depth; uses prerequisites correctly; minor over-explanations
  - 4-9: Defines prerequisites OR too basic for target audience
  - 0-3: Explains what prerequisites are (e.g., "SQL is...", "Git allows...") - completely inappropriate

### 4. Completeness (15 points)
- Covers all aspects needed to achieve the objectives
- Includes necessary context, prerequisites, and implementation steps
- Provides sufficient detail for learners to apply knowledge
- **Scoring Guide**:
  - 13-15: Complete coverage enabling full objective achievement
  - 8-12: Mostly complete with minor gaps
  - 4-7: Significant gaps in coverage
  - 0-3: Incomplete or insufficient for objective achievement

## QUALITY TIERS

Based on the final score:
- **high** (≥65): Excellent objective-aligned material, keep for question generation
- **borderline** (45-64): Partial objective alignment, requires human review
- **low** (<45): Insufficient for achieving stated objectives, filter out

## OUTPUT REQUIREMENTS

Provide your evaluation as structured JSON with:

1. **quality_score**: Total score (0-100) - sum of the 4 components below
2. **quality_tier**: "high" (>=65), "borderline" (45-64), or "low" (<45)
3. **primary_skill_area**: Main exam topic area this aligns with (use topics from the syllabus)
4. **objective_alignment**: Score 0-35 points
5. **implementation_specificity**: Score 0-30 points
6. **technical_depth**: Score 0-20 points
7. **completeness**: Score 0-15 points
8. **reasoning**: Brief explanation (2-3 sentences) explicitly referencing how the summary addresses (or fails to address) the specific objectives listed above

## EVALUATION GUIDELINES

**KEEP summaries that:**
- Directly enable learners to achieve the specific objectives listed
- Include implementation details needed to complete the objectives
- Provide code, commands, or configuration examples supporting objectives
- Enable creation of questions testing the stated objectives

**FLAG AS BORDERLINE summaries that:**
- Partially address objectives but lack complete coverage
- Are conceptually relevant but missing implementation details for objectives
- Cover objectives but at insufficient depth

**SCORE LOW summaries that:**
- Don't address the specific objectives listed
- Lack technical specificity needed to achieve objectives
- Are too generic or basic to support objective completion
- Miss key elements required for the stated objectives

## IMPORTANT NOTES

- Your PRIMARY evaluation criterion is: "Does this summary help learners achieve the specific objectives listed at the top?"
- Reference the specific objectives (not just general exam topics) when explaining alignment
- Quote which objectives are addressed and which are missed
- Prioritize objective-specific implementation details over general concepts
- Be objective and evidence-based in your scoring

Respond with valid JSON matching the schema. Be thorough in your reasoning, specifically citing the objectives.
{end_prompt}






{prompt Review_Borderline_Summary}
You are a certification exam content quality reviewer for the {{ seed.exam_syllabus.exam_name }}.

Your task is to review summaries that scored in the borderline range (45-64) and make a final keep/drop decision based on objective alignment.

## SPECIFIC LEARNING OBJECTIVES FOR THIS CONTENT

This content was created to support the following specific learning objectives:

{% for ref in source.referenced_in %}
**Section**: {{ ref.section_name }}
**Objective**: {{ ref.objective }}
**Relevance**: {{ ref.relevance }}

{% endfor %}

⚠️ **CRITICAL**: Your decision should be based on whether this summary helps learners achieve THESE SPECIFIC OBJECTIVES.

## EXAM SYLLABUS REFERENCE

```json
{{ seed.exam_syllabus.platform_name }}
```

## YOUR INPUTS:

### From Summary Generator:
- **Summary**: The comprehensive educational summary synthesizing the grouped facts
- **Code Snippets**: Code snippets extracted from the page content (if any)

### From Quality Scoring:
- **Quality Score**: The quality score of the content (45-64 range - borderline)
- **Objective Alignment Score**: How well it addressed the specific objectives
- **Primary Skill Area**: alignment with primary skill area
- **Initial Reasoning**: reasoning behind decision

## DECISION CRITERIA:

**KEEP if the summary:**
1. **Addresses specific objectives** - Directly helps learners achieve at least 2 of the objectives listed above
2. **Implementation specificity** - Contains commands, parameters, configuration details, or code needed for the objectives
3. **Objective-critical knowledge** - Tests skills needed to complete the stated objectives
4. **Actionable content** - Can generate questions testing the specific objectives

**DROP if the summary:**
1. **Misses key objectives** - Fails to address the main objectives it was supposed to cover
2. **Too generic** - Concepts not specific enough to achieve the stated objectives
3. **Background only** - Theoretical knowledge without implementation details needed for objectives
4. **Insufficient depth** - Doesn't provide enough detail to enable objective achievement

## OUTPUT REQUIREMENTS:

1. **final_decision**: "keep" or "drop"
2. **objectives_addressed**: List which specific objectives from the list above are adequately addressed
3. **objectives_missed**: List which specific objectives from the list above are missed or inadequately covered
4. **reasoning**: 2-3 sentences explaining your decision with specific references to which objectives are met/missed
5. **confidence**: Your confidence level (0-100) in this decision

## EXAMPLES:

**KEEP Example:**
Summary about "Setting up additional dbt projects" with cross-project ref() syntax →
- Addresses the "Setting up additional dbt projects" objective with implementation details
- Has concrete commands and configuration for the objective
- Decision: KEEP

**DROP Example:**
Summary about "Understanding environment types" but only has generic environment definitions →
- Misses the "Understanding environment types" objective depth
- No specific implementation for how environment types work
- Decision: DROP

## EVALUATION APPROACH:

For each objective listed at the top:
1. Does the summary provide actionable information to achieve it?
2. Are there specific technical details supporting the objective?
3. Can this summary enable question creation testing that objective?

If the answer is "yes" for at least 2 objectives, lean toward KEEP.
If the answer is "no" for most objectives, lean toward DROP.

Respond with valid JSON only. No additional commentary.
{end_prompt}




{prompt Score_Question_Quality}
# Question Quality Scoring - {{ seed.exam_syllabus.exam_name }}

You are an expert exam question reviewer evaluating practice questions for the {{ seed.exam_syllabus.exam_name }}.

## SPECIFIC LEARNING OBJECTIVES FOR THIS QUESTION

This question was generated from content supporting the following specific learning objectives:

{% for ref in source.referenced_in %}
**Section**: {{ ref.section_name }}
**Objective**: {{ ref.objective }}
**Relevance**: {{ ref.relevance }}

{% endfor %}

⚠️ **CRITICAL**: Evaluate whether this question tests one or more of THESE SPECIFIC OBJECTIVES, not just general exam topics.

## EXAM SYLLABUS REFERENCE

```json
{{ seed.exam_syllabus }}
```

## YOUR TASK

Evaluate the provided question and score it based on how well it tests the specific learning objectives listed above.

## INPUT

- **Question**: {question}
- **Options**: {options}
- **Answer**: {answer}
- **Explanation**: {answer_explanation}

## SCORING CRITERIA (0-100)

Score based on:

### 1. Objective Alignment (60 points) - MOST IMPORTANT
Does the question directly test one or more of the specific objectives listed above?
- **50-60**: Directly tests a specific objective with clear measurement of achievement
- **35-49**: Tests an objective but measurement is indirect or unclear
- **15-34**: Loosely related to an objective but doesn't clearly test it
- **0-14**: Doesn't test any of the specific objectives listed

### 2. Hands-on/Implementation Focus (25 points)
Does it test practical skills needed to achieve the objectives?
- **20-25**: Tests hands-on implementation skills for the objective
- **10-19**: Tests some practical application but lacks implementation depth
- **0-9**: Purely theoretical, doesn't test practical skills

### 3. Technical Specificity (15 points)
Does it use specific features, configurations, or procedures mentioned in the objectives?
- **12-15**: Uses specific technical details from the objective domain
- **6-11**: Some technical specificity but could be more concrete
- **0-5**: Too generic, lacks technical specificity

**Overall Scoring Guide**:
- **85-100**: Directly tests a specific objective with hands-on implementation details
- **70-84**: Tests an objective with good specificity but less hands-on focus
- **50-69**: Related to objectives but doesn't clearly test objective achievement
- **0-49**: Not aligned with the specific objectives

## OUTPUT

Provide exactly 4 fields:

1. **syllabus_alignment_score** (0-100): Overall alignment score
2. **objective_tested**: Which specific objective(s) from the list above does this question test? Quote the objective(s).
3. **aligned_skill_area**: Which topic area from the syllabus does this question test?
4. **reasoning** (2-3 sentences): Why this score? Explain how the question does (or doesn't) test the specific objective(s).

**Questions scoring >= 85 will be kept. Questions scoring < 85 will be filtered out.**

Be strict and objective - only questions that clearly test the specific learning objectives should score >= 85.

## EVALUATION APPROACH:

1. Identify which objective(s) from the list this question attempts to test
2. Evaluate whether answering correctly demonstrates achievement of that objective
3. Check if the question uses specific technical details from the objective domain
4. Score based on how directly and measurably it tests objective achievement

{end_prompt}


{prompt Score_Question_Alignment}
# Question Syllabus Alignment Scoring - {{ seed.exam_syllabus.exam_name }}

You are an expert exam question reviewer evaluating practice questions for the
{{ seed.exam_syllabus.exam_name }}. Score how well the question aligns to the
official exam syllabus objectives.

## EXAM SYLLABUS REFERENCE

```json
{{ seed.exam_syllabus }}
```

## INPUT

- **Question**: {{ write_scenario_question.question }}
- **Options**: {{ reconstruct_options.options }}
- **Answer**: {{ write_scenario_question.answer }}
- **Explanation**: {{ write_scenario_question.answer_explanation }}

## SCORING CRITERIA (0-100)

### 1. Objective Alignment (60 points) - MOST IMPORTANT
Does the question directly test one or more syllabus objectives?
- **50-60**: Directly tests a specific objective with clear measurement of achievement
- **35-49**: Tests an objective but measurement is indirect or unclear
- **15-34**: Loosely related but doesn't clearly test objective achievement
- **0-14**: Not aligned to any objective

### 2. Hands-on/Implementation Focus (25 points)
Does it test practical skills needed to achieve the objectives?
- **20-25**: Clearly tests hands-on implementation skills
- **10-19**: Some practical application but lacks depth
- **0-9**: Purely theoretical or generic

### 3. Technical Specificity (15 points)
Does it use specific features, configurations, or procedures from the syllabus?
- **12-15**: Specific technical details
- **6-11**: Some specificity but could be more concrete
- **0-5**: Too generic

**Overall Scoring Guide**:
- **85-100**: Strong, direct alignment to a specific objective with hands-on focus
- **70-84**: Good alignment but less hands-on or specificity
- **50-69**: Weak alignment
- **0-49**: Not aligned

## OUTPUT (JSON ONLY)

Return exactly these 4 fields:

1. **syllabus_alignment_score_{{ seed.judge_num }}** (0-100)
2. **aligned_skill_area_{{ seed.judge_num }}** (string)
3. **objective_tested_{{ seed.judge_num }}** (string; quote the objective)
4. **alignment_reasoning_{{ seed.judge_num }}** (2-3 sentences)

Be strict. Only score >= 85 if the question clearly tests a specific objective
with practical depth.

{end_prompt}













{prompt Generate_Distractor_1}
You are generating the FIRST distractor for this multiple-choice question.

## WORD COUNT CONSTRAINT (CRITICAL - MUST FOLLOW)

**Correct answer word count**: {{ suggest_distractor_counts.target_word_counts.correct_answer_words }} words
**Your distractor constraint**: {{ suggest_distractor_counts.target_word_counts.distractor_1 }}

{% if suggest_distractor_counts.target_word_counts.distractor_1 == "lesser_than" %}
⚠️ **YOUR DISTRACTOR MUST BE SHORTER**: Write {{ suggest_distractor_counts.target_word_counts.correct_answer_words - 2 }} to {{ suggest_distractor_counts.target_word_counts.correct_answer_words - 1 }} words (at least 2 words less than correct answer)
{% elif suggest_distractor_counts.target_word_counts.distractor_1 == "equal_to" %}
⚠️ **YOUR DISTRACTOR MUST MATCH LENGTH**: Write exactly {{ suggest_distractor_counts.target_word_counts.correct_answer_words }} words (same as correct answer)
{% elif suggest_distractor_counts.target_word_counts.distractor_1 == "greater_than" %}
⚠️ **YOUR DISTRACTOR MUST BE LONGER**: Write {{ suggest_distractor_counts.target_word_counts.correct_answer_words + 2 }} to {{ suggest_distractor_counts.target_word_counts.correct_answer_words + 4 }} words (at least 2 words more than correct answer)
{% endif %}

**Correct answer for reference** ({{ suggest_distractor_counts.target_word_counts.correct_answer_words }} words):
"{{ add_answer_text.answer_text[0] }}"

Count your words carefully before submitting!

## DISTRACTOR REQUIREMENTS

Write a distractor that:
1. Is honestly trying to solve the question (not just using wrong words)
2. Would be valid in another scenario but has critical caveats in THIS question
3. Is wrong because it uses the WRONG TECHNOLOGY or SERVICE
4. Matches the style and pattern of answer_text
5. **STRICTLY follows the word count constraint above**
6. Uses the summary and grouped_facts as your guide

Guidelines:
- Focus on technology/service confusion (e.g., uses Service A when Service B is needed)
- Be plausible and technically credible
- Think step by step
- CRITICAL: Do NOT escape or duplicate special characters (braces, brackets, quotes) in your output. Write technical syntax naturally.

Output:
{
  "distractor_1": "<your distractor text>",
  "explanation_why_it_is_incorrect_1": "<why this is wrong>",
  "thinking_process_1": "<your reasoning>"
}
{end_prompt}


{prompt Generate_Distractor_2}
You are generating the SECOND distractor for this multiple-choice question.

## WORD COUNT CONSTRAINT (CRITICAL - MUST FOLLOW)

**Correct answer word count**: {{ suggest_distractor_counts.target_word_counts.correct_answer_words }} words
**Your distractor constraint**: {{ suggest_distractor_counts.target_word_counts.distractor_2 }}

{% if suggest_distractor_counts.target_word_counts.distractor_2 == "lesser_than" %}
⚠️ **YOUR DISTRACTOR MUST BE SHORTER**: Write {{ suggest_distractor_counts.target_word_counts.correct_answer_words - 2 }} to {{ suggest_distractor_counts.target_word_counts.correct_answer_words - 1 }} words (at least 2 words less than correct answer)
{% elif suggest_distractor_counts.target_word_counts.distractor_2 == "equal_to" %}
⚠️ **YOUR DISTRACTOR MUST MATCH LENGTH**: Write exactly {{ suggest_distractor_counts.target_word_counts.correct_answer_words }} words (same as correct answer)
{% elif suggest_distractor_counts.target_word_counts.distractor_2 == "greater_than" %}
⚠️ **YOUR DISTRACTOR MUST BE LONGER**: Write {{ suggest_distractor_counts.target_word_counts.correct_answer_words + 2 }} to {{ suggest_distractor_counts.target_word_counts.correct_answer_words + 4 }} words (at least 2 words more than correct answer)
{% endif %}

**Correct answer for reference** ({{ suggest_distractor_counts.target_word_counts.correct_answer_words }} words):
"{{ add_answer_text.answer_text[0] }}"

Count your words carefully before submitting!

## PREVIOUS DISTRACTOR

⚠️ IMPORTANT: You can see distractor_1 that was already generated.

Your distractor MUST be DIFFERENT from distractor_1.

Previously generated:
- distractor_1: {{generate_distractor_1.distractor_1}}
- Why it's wrong: {{generate_distractor_1.explanation_why_it_is_incorrect_1}}

## DISTRACTOR REQUIREMENTS

Write a NEW distractor that:
1. Is honestly trying to solve the question
2. Would be valid in another scenario but has critical caveats in THIS question
3. Is wrong because it uses the WRONG APPROACH or CONCEPT (not just wrong technology)
4. Matches the style and pattern of answer_text
5. **STRICTLY follows the word count constraint above**
6. **DIFFERS from distractor_1** - takes a different angle
7. Uses the summary and grouped_facts as your guide

Guidelines:
- Focus on approach/concept confusion (e.g., right technology, wrong method)
- Don't repeat the mistake pattern from distractor_1
- Be plausible and technically credible
- Think step by step
- CRITICAL: Do NOT escape or duplicate special characters (braces, brackets, quotes) in your output. Write technical syntax naturally.

Output:
{
  "distractor_2": "<your DIFFERENT distractor text>",
  "explanation_why_it_is_incorrect_2": "<why this is wrong>",
  "thinking_process_2": "<your reasoning>"
}
{end_prompt}


{prompt Generate_Distractor_3}
You are generating the THIRD and final distractor for this multiple-choice question.

## WORD COUNT CONSTRAINT (CRITICAL - MUST FOLLOW)

**Correct answer word count**: {{ suggest_distractor_counts.target_word_counts.correct_answer_words }} words
**Your distractor constraint**: {{ suggest_distractor_counts.target_word_counts.distractor_3 }}

{% if suggest_distractor_counts.target_word_counts.distractor_3 == "lesser_than" %}
⚠️ **YOUR DISTRACTOR MUST BE SHORTER**: Write {{ suggest_distractor_counts.target_word_counts.correct_answer_words - 2 }} to {{ suggest_distractor_counts.target_word_counts.correct_answer_words - 1 }} words (at least 2 words less than correct answer)
{% elif suggest_distractor_counts.target_word_counts.distractor_3 == "equal_to" %}
⚠️ **YOUR DISTRACTOR MUST MATCH LENGTH**: Write exactly {{ suggest_distractor_counts.target_word_counts.correct_answer_words }} words (same as correct answer)
{% elif suggest_distractor_counts.target_word_counts.distractor_3 == "greater_than" %}
⚠️ **YOUR DISTRACTOR MUST BE LONGER**: Write {{ suggest_distractor_counts.target_word_counts.correct_answer_words + 2 }} to {{ suggest_distractor_counts.target_word_counts.correct_answer_words + 4 }} words (at least 2 words more than correct answer)
{% endif %}

**Correct answer for reference** ({{ suggest_distractor_counts.target_word_counts.correct_answer_words }} words):
"{{ add_answer_text.answer_text[0] }}"

Count your words carefully before submitting!

## PREVIOUS DISTRACTORS

⚠️ IMPORTANT: You can see BOTH previously generated distractors.

Your distractor MUST be DIFFERENT from BOTH distractor_1 AND distractor_2.

Previously generated:
**Distractor 1:**
- distractor_1: {{ generate_distractor_1.distractor_1 }}
- Why wrong: {{generate_distractor_1.explanation_why_it_is_incorrect_1}}

**Distractor 2:**
- distractor_2: {{ generate_distractor_2.distractor_2 }}
- Why wrong: {{ generate_distractor_2.explanation_why_it_is_incorrect_2 }}

## DISTRACTOR REQUIREMENTS

Write a NEW distractor that:
1. Is honestly trying to solve the question
2. Would be valid in another scenario but has critical caveats in THIS question
3. Is wrong due to EDGE CASE or COMMON MISCONCEPTION
4. Matches the style and pattern of answer_text
5. **STRICTLY follows the word count constraint above**
6. **DIFFERS from both distractor_1 AND distractor_2** - explores a third angle
7. Uses the summary and grouped_facts as your guide

Guidelines:
- Focus on edge cases, partial solutions, or common misconceptions
- Don't repeat mistake patterns from distractor_1 or distractor_2
- Ensure all 3 distractors test different aspects
- Be plausible and technically credible
- Think step by step
- CRITICAL: Do NOT escape or duplicate special characters (braces, brackets, quotes) in your output. Write technical syntax naturally.

Output:
{
  "distractor_3": "<your DIFFERENT distractor text>",
  "explanation_why_it_is_incorrect_3": "<why this is wrong>",
  "thinking_process_3": "<your reasoning>"
}
{end_prompt}








{prompt Generate_Concept_Explanation}
You are a senior technical educator writing concept explanations for staff/senior engineers preparing for certification exams.

Your task is to explain the **underlying technical concept** being tested by this question - not why the answer is correct, but what the concept IS and why it matters in production systems.

## YOUR INPUTS:
- **Question**: The scenario-based question
- **Correct Answer**: The correct answer text
- **Answer Explanation**: Why this answer is correct
- **Source Quote**: Original documentation excerpt

## CONCEPT EXPLANATION REQUIREMENTS:

### 1. **Teach the Concept, Not the Answer**
- Explain the core technical concept being tested
- Cover how it works under the hood
- Discuss when and why you'd use it in production
- Include edge cases and gotchas experienced engineers encounter

### 2. **Production-Level Depth**
- Go beyond surface-level explanations
- Include implementation considerations
- Mention common pitfalls and how to avoid them
- Reference real-world scenarios where this matters

### 3. **Staff Engineer Perspective**
- Write for someone with 8+ years experience
- Assume familiarity with basic concepts
- Focus on nuances and trade-offs
- Include architectural considerations

## FORMAT:
Write 2-4 paragraphs that a senior engineer would find valuable for deepening their understanding. No bullet points - write in clear, flowing prose that reads like a senior engineer explaining the concept to a colleague.

## OUTPUT SCHEMA:

```json
{
  "concept_explanation": "2-4 paragraph explanation of the underlying concept, its production implications, and key considerations for experienced engineers"
}
```

## CRITICAL RULES:
1. Do NOT reference the specific question or answer options
2. Do NOT use phrases like "this question tests" or "the correct answer is"
3. Focus purely on teaching the concept itself
4. Write as if this is standalone educational content
5. Ground your explanation in the source documentation provided

{end_prompt}

{prompt Feynman_Explanation_Generator}
You are an expert educator specializing in creating Feynman-style explanations that help students understand quiz questions and why specific answers are correct. Avoid referencing option identifier like option A or according to option B and all phrasing like this, we will randomize locations so you might be referencing the wrong option.

Your task is to explain the specific question scenario and why the correct answer solves it, using simple analogies and clear reasoning.

## YOUR INPUTS:
- **Question**: Question
- **Options**: The options
- **Correct Answer**: The correct answer
- **Answer Explanation**: concise explanation of the answer
- **Summary**: The comprehensive educational summary from which the question was generated

## FEYNMAN TECHNIQUE PRINCIPLES:

### 1. **Question-Focused Approach**
- Start by explaining what the question is really asking
- Break down the scenario into understandable parts
- Use simple analogies to clarify the problem
- Reference the summary to understand the full context

### 2. **Answer-Specific Reasoning**
- Explain exactly why the correct answer works for this specific question
- Use the analogy to show how the solution fits the problem
- Connect the reasoning to technical principles from the summary
- Reference code_snippets when they help illustrate the concept

### 3. **Make It Memorable**
- Use vivid analogies that students can remember during exams
- Create mental models that stick
- Focus on the "aha moment" of understanding
- Ground explanations in the summary to ensure accuracy

## EXPLANATION STRUCTURE:

### **Question Breakdown** (2-3 sentences)
Start with a relatable analogy that captures what the question scenario is really about.

### **The Core Problem** (1-2 paragraphs)
- Explain the specific challenge presented in the question using the analogy
- Break down technical requirements into simple terms
- Show why this particular situation matters

### **Why This Answer Works** (2-3 paragraphs)
- Explain exactly how the correct answer solves the specific problem
- Use the analogy to make the solution logic clear
- Connect to the technical principles being tested

### **Key Takeaway** (1 paragraph)
- Provide one memorable insight that helps answer similar questions
- Connect back to the learning objective
- Give students a mental shortcut for future problems

## CRITICAL RULES:

1. **QUESTION-SPECIFIC**: Focus on explaining THIS question and THIS answer - not general concepts
2. **NO DISTRACTOR DISCUSSION**: Do NOT explain why other options are wrong
3. **CONSISTENT ANALOGY**: Use one main analogy throughout the explanation
4. **PRACTICAL FOCUS**: Help students understand how to recognize and solve similar problems
5. **USE ALL CONTEXT**: Leverage the summary and code_snippets to create rich, accurate explanations
6. **CODE INTEGRATION**: When code_snippets are available, reference them to illustrate technical concepts
7. **GROUNDED IN SOURCE**: Base your explanation on the provided context - don't add information not present in the inputs
8. **SPECIAL CHARACTERS**: Do NOT escape or duplicate special characters (braces, brackets, quotes) in your output. Write technical syntax naturally.

## OUTPUT SCHEMA:

```json
{
  "question_explanation": "Clear breakdown of what the question scenario is asking using analogy",
  "answer_reasoning": "Detailed explanation of why the correct answer solves this specific problem",
  "key_concept_analogy": "The main analogy/metaphor used to explain the concept",
  "memorable_takeaway": "One key insight students can remember for similar questions"
}
```

## EXAMPLE TONE:
"This question is like asking which tool you'd use to organize 50,000 library books. The scenario tells us we need to handle a massive catalog without overwhelming the system..."

Generate a focused explanation that helps students understand this specific question and answer.
{end_prompt}

{prompt Validate_Syntax}
# Syntax Validation Task

Scan all provided fields for programming syntax errors. Flag content with malformed code or hallucinated programming constructs.

## WHAT TO CHECK

Look for these error patterns:

1. **Repeated delimiters** suggesting data corruption (like 8+ repeated braces or brackets)
2. **Function calls missing required parameters**
3. **Corrupted closing syntax** with extra characters or typos
4. **Double-escaped characters** suggesting encoding errors
5. **Incomplete code** missing closing parentheses, quotes, or brackets
6. **Fake syntax** that doesn't exist in any real programming language

## VALIDATION RULES

- **VALID**: No syntax errors detected
- **INVALID**: Found malformed syntax suggesting LLM hallucination or data corruption

## EXAMPLES

### INVALID Example 1: Over-Escaped Strings
**Content**: `"code": "print(\\"Hello World\\")"`
**Reasoning**: Double-escaped quotes suggest incorrect escaping

### INVALID Example 2: Incomplete Function
**Content**: `"snippet": "def process(data"`
**Reasoning**: Missing closing parenthesis and colon

### INVALID Example 3: Corrupted Delimiters
**Content**: `"quote": "function(argument) ]]]]]d works now"`
**Reasoning**: Corrupted closing bracket with random 'd' character

### VALID Example 1: Clean Code
**Content**: `"snippet": "SELECT * FROM users WHERE active = true"`
**Reasoning**: Valid SQL syntax

### VALID Example 2: Natural Language
**Content**: `"fact": "The system uses template syntax for variables"`
**Reasoning**: Describing syntax in natural language, not actual code

## OUTPUT FORMAT

Return exactly 3 fields:
```json
{
  "has_syntax_errors": false,
  "validation_status": "VALID",
  "error_summary": "No syntax errors detected"
}
```

**CRITICAL**:
- `validation_status` must be ONLY "VALID" or "INVALID" (no other values)
- Only flag ACTUAL malformed code, not natural language descriptions
- If no programming syntax exists in content, return VALID
{end_prompt}

{prompt Validate_Answer_From_Source}
You are a quiz validation expert. Your task is to answer a multiple-choice question based ONLY on the provided source documentation.

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

**Instructions:**
1. Base your answer ONLY on the source documentation provided
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

**CRITICAL:**
- Only use letters A, B, C, D, E (depending on number of options)
- Your reasoning must reference the source documentation
- supporting_quotes must be an array of 1-3 VERBATIM excerpts from the source (complete sentences, not fragments)
{end_prompt}

{prompt Judge_Question_Quality}
You are a senior exam-content reviewer. Judge whether this question is valuable for learners or is verbose/fake/low-signal.

## QUESTION

{{ write_scenario_question.question }}

## OPTIONS

{% for option in reconstruct_options.options %}
{{ loop.index | string | replace('1', 'A') | replace('2', 'B') | replace('3', 'C') | replace('4', 'D') | replace('5', 'E') }}. {{ option }}
{% endfor %}

## CORRECT ANSWER

{{ write_scenario_question.answer }}

## ANSWER EXPLANATION

{{ write_scenario_question.answer_explanation }}

## EVALUATION CRITERIA

KEEP the question if it is:
- Clear, specific, and unambiguous (one best answer)
- Tests meaningful skills/knowledge, not trivia
- Concise and focused (no fluff or filler)
- Plausible and realistic for the target audience

DROP the question if it is:
- Verbose, padded, or telegraphed
- Ambiguous or has multiple defensible answers
- Fake/contrived with no practical learning value
- Overly generic, off-topic, or not testable

## OUTPUT FORMAT

```json
{
  "quality_vote_{{ seed.judge_num }}": "KEEP",
  "quality_reasoning_{{ seed.judge_num }}": "1-3 sentences explaining why this question is or is not valuable.",
  "quality_flags_{{ seed.judge_num }}": ["verbose", "ambiguous", "fake", "off_topic", "telegraphed", "multiple_correct"]
}
```

**CRITICAL:**
- `quality_vote_{{ seed.judge_num }}` must be ONLY "KEEP" or "DROP"
- `quality_flags_{{ seed.judge_num }}` must be an array (empty if no issues)
{end_prompt}
