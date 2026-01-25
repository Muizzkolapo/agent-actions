{prompt generate_optimal_code}
You are creating the CORRECT, IDIOMATIC code implementation for a focused learning scenario.

**Works with ANY language/technology:** Python, Terraform, Azure CLI, Kubernetes, Bash, SQL, Docker, etc.

**CRITICAL: Ground your code in the source documentation. Follow best practices and patterns documented in the source material.**

## SOURCE DOCUMENTATION

Title: {{ source.title }}

Documentation:
```
{{ source.page_content }}
```

## TASK CONTEXT

- Scenario: {{ code_usage_scenario.sample_usage_scenario }}
- Base Code: {{ code_usage_scenario.code_for_scenario }}
- Complexity: {{ code_usage_scenario.scenario_complexity }}
- Considerations: {{ code_usage_scenario.key_considerations }}

## CRITICAL CONSTRAINTS

- The optimal code must be PURELY GROUNDED in the provided documentation and code_for_scenario
- Do NOT add ANY flags, parameters, configuration, or code elements not present in {code_for_scenario} OR mentioned in the source docs
- Do NOT add complexity beyond what's in {code_for_scenario}
- Keep the EXACT SAME flags/parameters/config as {code_for_scenario}
- Only fix syntax errors or make the existing code idiomatic based on patterns shown in the source documentation
- Use ONLY information from: source documentation, sample_usage_scenario, code_for_scenario, key_considerations

**Your task:**
Take {code_for_scenario} and make MINIMAL corrections to ensure it's syntactically correct and follows best practices FROM THE SOURCE DOCUMENTATION. Do NOT add anything new.

**What you CAN do:**
- Fix syntax errors in {code_for_scenario}
- Correct parameter/flag/argument formatting
- Fix quote styles, indentation, spacing
- Make idiomatic what's already there (e.g., proper Python conventions, Terraform best practices, etc.)
- Preserve the language/framework's syntax rules

**What you CANNOT do:**
- Add flags/parameters/config not in {code_for_scenario}
- Add imports, modules, or dependencies not in {code_for_scenario}
- Combine multiple concepts if {code_for_scenario} has one concept
- Add code from page_content that's not in {code_for_scenario}
- Expand beyond the length of {code_for_scenario}
- Wrap in functions/scripts if {code_for_scenario} is a simple command/statement
- Add error handling, logging, or production features
- Change the technology/framework (if it's Python, keep it Python; if it's Terraform, keep it Terraform)

**Examples across technologies:**

Python:
- Input: `data = json.load(open('file.json'))`
- ✅ CORRECT: `data = json.load(open('file.json'))` (already correct)
- ❌ WRONG: `with open('file.json') as f: data = json.load(f)` (added context manager not in input)

Terraform:
- Input: `resource "aws_instance" "app" { ami = "ami-123" }`
- ✅ CORRECT: `resource "aws_instance" "app" { ami = "ami-123" }`
- ❌ WRONG: `resource "aws_instance" "app" { ami = "ami-123" instance_type = "t2.micro" }` (added property)

Azure CLI:
- Input: `az vm create --name myVM --resource-group myRG`
- ✅ CORRECT: `az vm create --name myVM --resource-group myRG`
- ❌ WRONG: `az vm create --name myVM --resource-group myRG --location eastus` (added flag)

Provide only:
- optimal_code: The MINIMALLY corrected version of {code_for_scenario} (same flags/parameters, just syntactically correct and idiomatic)

{end_prompt}


{prompt generate_scenario_question}
You are an expert at creating scenario-based quiz questions for technical certification exams.

Your task is to generate a concise scenario-based question that tests the ability to choose the best code implementation.

Context provided:
- Scenario: {sample_usage_scenario}
- Original Code: {code_for_scenario}
- Complexity Level: {scenario_complexity}
- Technical Considerations: {key_considerations}
- Optimal Implementation: {optimal_code}

Generate a quiz question following these guidelines:

A) Question (1-2 sentences maximum)
1. Start with the core technical scenario in 1 sentence:
   - Include key technical context (tools, frameworks, versions)
   - Include the main requirement or constraint
   - Keep it focused and direct
2. End with a clear question stem:
   - "Which implementation should you use?"
   - "What is the best approach?"
   - "Which code correctly implements this?"

Example structure:
"[Scenario context with key requirement]. Which implementation should you use?"

Keep the question CONCISE—avoid lengthy details. The code options will provide the specifics.

B) Answer explanation (2-3 sentences)
Explain how the optimal_code SOLVES the specific question asked:
- Connect the code directly to the requirements stated in the question
- Explain what the code does and why it addresses the problem
- ONLY explain why this code is RIGHT—do NOT explain why other options are wrong
- Do NOT reference option identifiers (A, B, C, D)
- Focus on technical reasoning: what the code accomplishes and how it meets the requirements

C) Question context
Leave this as an empty string. All necessary context should be in the question itself.

Output:
- question: Concise scenario + question stem (1-2 sentences max)
- question_context: "" (always empty string)
- answer_explanation: How the optimal_code solves the question (2-3 sentences, focused on what the code does to address the requirements)

Style:
- Professional certification exam tone
- Concise and focused
- No preambles or extra fields
{end_prompt}



{prompt generate_code_alternatives}

You are generating alternatives of 3 suboptimal code implementations.

**Works with ANY language/technology:** Python, Terraform, Azure CLI, Kubernetes, Docker, Bash, SQL, Go, and more.

**CRITICAL: Ground your alternatives in common mistakes or anti-patterns mentioned or implied in the source documentation.**

## SOURCE DOCUMENTATION

Title: {{ source.title }}

Documentation:
```
{{ source.page_content }}
```

## TASK CONTEXT

- Scenario: {{ code_usage_scenario.sample_usage_scenario }}
- Optimal Code: {{ generate_optimal_code.optimal_code }}
- Key Considerations: {{ code_usage_scenario.key_considerations }}

## CRITICAL CONSTRAINTS

- Keep the same LENGTH and STYLE as the optimal code
- If optimal code is 1 line (e.g., CLI command), alternative should be ~1 line
- If optimal code is 10 lines (e.g., Python function), alternative should be ~10 lines
- Do NOT add production complexity that wasn't in the optimal code
- Do NOT wrap in scripts/functions if optimal code is a simple command/statement
- Stay in the SAME TOOL/LANGUAGE as the optimal code (if Python, stay Python; if Terraform, stay Terraform)
- Preserve the same technology stack and framework

Each alternative must:
- Be syntactically correct and functional in that language/tool
- Work in the given scenario BUT have specific issues relevant to that technology
- Represent common mistakes or violations of best practices FROM THE SOURCE DOCUMENTATION
- Be clearly inferior to the optimal code
- Be SIMILAR in length and complexity to the optimal code
- DO NOT ADD ANY INLINE COMMENTS
- Use realistic mistakes that developers actually make (ideally referenced or implied in the docs)

Alternative types (adapt to the technology):
- Alternative 1: Performance/Efficiency issues
  - Look for: optimization flags, efficient patterns, performance tips in the docs
  - Examples: Missing optimization flag, inefficient algorithm, wrong index, excessive API calls
- Alternative 2: Security/Reliability issues
  - Look for: security warnings, required parameters, error handling advice in the docs
  - Examples: Missing validation, hardcoded credentials, no error handling, brittle configuration
- Alternative 3: Readability/Maintainability issues
  - Look for: code style guidelines, conventions, best practices in the docs
  - Examples: Overly complex syntax, unclear naming, poor structure, non-idiomatic code

**Use the documentation to identify:**
- Common gotchas or caveats mentioned
- Required vs optional parameters
- Deprecated or discouraged patterns
- Performance considerations
- Security warnings

For this alternative, provide:
- alternative_code_number: Code with same length/style as optimal but with intentional issues based on documentation guidance
- issue_type_number: Category of issue (performance/security/readability/maintainability)
- issue_description_number: Specific technical issue present, explaining why it violates best practices FROM THE DOCS (1-2 sentences)
{end_prompt}





{prompt explain_code_choices}
You are explaining code quality differences to help learners understand best practices.

Generate concise explanations (2-3 sentences each) for:

1. why_optimal_is_best:
    - Explain what makes the optimal code superior
    - Reference specific best practices applied
    - Highlight key improvements over alternatives

2. why_alternative_1_is_suboptimal:
    - Explain the specific issue: {issue_description_1}
    - Describe the negative impact in production
    - Keep it educational, not judgmental

3. why_alternative_2_is_suboptimal:
    - Explain the specific issue: {issue_description_2}
    - Describe the negative impact in production

4. why_alternative_3_is_suboptimal:
    - Explain the specific issue: {issue_description_3}
    - Describe the negative impact in production

Context:
- Scenario: {sample_usage_scenario}
- Issue Types: {issue_type_1}, {issue_type_2}, {issue_type_3}

{end_prompt}

{prompt Fact_extraction}
Extract key technical facts and code patterns from the documentation.

From the page_content, identify:
- candidate_facts_list: Array of technical facts, each containing:
  - fact: The core technical concept or code pattern
  - quote: Direct quote from documentation supporting this fact
  - technical_level: beginner/intermediate/advanced

Focus on:
- Code syntax and usage patterns
- Configuration options and flags
- Best practices mentioned in the documentation
- Technical requirements or constraints

Only extract facts that are clearly stated in the page_content. Do not infer or add external knowledge.
{end_prompt}


{prompt Cluster_Validation_Agent}
Validate if the cluster of facts should be kept together or split.

Review the flagged_items (list of facts with their cluster_tags) and determine:
1. should_keep_cluster: true/false - whether these facts belong together
2. reasoning: explanation of your decision
3. new_clusters: if splitting, map cluster_tags to new cluster IDs like {"new_cluster1": ["tag1", "tag2"], "new_cluster2": ["tag3"]}

Keep clusters together if facts share:
- Same code component or feature
- Related technical concepts
- Similar complexity level

Split clusters if facts cover:
- Different code components
- Unrelated technical areas
- Mixed complexity levels that would confuse learners
{end_prompt}


{prompt terraform}
Generate a code-focused quiz scenario from technical facts.

Based on the fact and fact_explanation, create a technical quiz:

Output:
- sample_usage_scenario: practical scenario where this code is needed (2-3 sentences)
- code_for_scenario: example code demonstrating the concept
- scenario_complexity: beginner/intermediate/advanced
- key_considerations: important technical points (1-2 sentences)
- questionable: "High Value" if makes a good quiz question, "Low Value" if too simple/unclear
- questions: array containing one question object with:
  - question: scenario-based question asking which code implementation is best
  - options: array with correct code answer
  - answer: "A" (letter key for correct option)
  - question_type: "code_implementation"

Focus on creating realistic code scenarios that test understanding of the technical concept.
{end_prompt}


{prompt answer_explanation}
Generate teaching explanations for the quiz question.

Based on the question, options, and answer, provide:

- solution_approach: step-by-step explanation of how to solve this type of problem (2-3 sentences)
- key_concept_definition: clear definition of the main technical concept being tested (1-2 sentences)

Focus on helping learners understand the WHY behind the correct answer, not just the what.
{end_prompt}


{prompt AnswerLengthDistractorGenerator_prompt}
Generate a distractor (wrong answer) for a code quiz question.

You are creating distractor ${stage} of 3.

Context:
- Question: {question}
- Correct answer: {answer_text}
- Answer explanation: {answer_explanation}
- Target word count: {target_word_counts}
- Solution approach: {solution_approach}
- Key concept: {key_concept_definition}

Generate:
- distractor_${stage}: plausible but incorrect code/answer
- explanation_why_it_is_incorrect_${stage}: why this answer is wrong (2-3 sentences)

The distractor should:
- Be similar in length to the correct answer
- Look plausible to someone who doesn't fully understand the concept
- Have a clear technical flaw or misconception
- NOT be obviously wrong

Distractor types:
- Stage 1: Performance/efficiency issue
- Stage 2: Missing required element or incorrect configuration  
- Stage 3: Edge case mishandling or common misconception
{end_prompt}

{prompt Feynman_Explanation_Generator}
# Feynman-Style Explanation for Code Quiz

You are an expert educator creating simple, memorable explanations for coding concepts.

## YOUR TASK

Generate a Feynman-style explanation for why the optimal code solution is the best choice.

**CRITICAL: Ground your explanation in the source documentation. Use concepts, terminology, and examples from the documentation.**

## INPUT DATA

**Source Documentation:**
Title: {{ source.title }}
URL: {{ source.url }}

Documentation excerpt:
```
{{ source.page_content }}
```

**Scenario:**
{{ code_usage_scenario.sample_usage_scenario }}

**Key Considerations:**
{{ code_usage_scenario.key_considerations }}

**Optimal Code:**
```
{{ generate_optimal_code.optimal_code }}
```

**Why Alternatives Are Wrong:**
{% for key, value in merge_alternatives.items() %}
{% if 'issue_description' in key %}
- {{ value }}
{% endif %}
{% endfor %}

## OUTPUT REQUIREMENTS

Generate a simple explanation that a beginner could understand:

1. **question_explanation**: Explain the scenario in simple terms using an analogy or real-world comparison (2-3 sentences). Ground this in concepts from the source documentation.

2. **answer_reasoning**: Explain why the optimal code is best, using the analogy. Reference specific aspects from the code AND the source documentation that make it superior (3-4 sentences). Connect to best practices mentioned in the docs.

3. **key_concept_analogy**: A memorable comparison that helps remember the concept (ideally related to the domain or use case in the documentation)

4. **memorable_takeaway**: One key lesson to remember (1 sentence) - this should reflect a principle from the source material

**Important:**
- Use terminology from the source documentation
- Reference specific features, patterns, or best practices mentioned in the docs
- Make analogies relevant to the technology domain
- Ensure technical accuracy by grounding in source material

Make it conversational and memorable, but technically accurate.

{end_prompt}

{prompt Generate_Concept_Explanation}
# Technical Concept Explanation for Code Quiz

You are an expert software engineering educator explaining technical concepts in depth.

## YOUR TASK

Generate a detailed technical explanation of the coding concept being tested.

**CRITICAL: Ground your explanation entirely in the source documentation. Quote, reference, and explain concepts directly from the docs.**

## INPUT DATA

**Source Documentation:**
Title: {{ source.title }}
URL: {{ source.url }}

Full documentation:
```
{{ source.page_content }}
```

**Scenario:**
{{ code_usage_scenario.sample_usage_scenario }}

**Optimal Code:**
```
{{ generate_optimal_code.optimal_code }}
```

**Simple Explanation (for context):**
{{ generate_feynman_explanation.question_explanation }}

**Alternative Issues:**
{% for key, value in merge_alternatives.items() %}
{% if 'issue_description' in key %}
- {{ value }}
{% endif %}
{% endfor %}

## OUTPUT REQUIREMENTS

Generate comprehensive technical explanation (concept_explanation) covering:

1. **Core technical principle**: What concept from the source documentation is being tested? Quote or reference specific sections of the docs.

2. **Implementation considerations**: Key factors mentioned in the docs for implementing this pattern correctly. Reference specific best practices, warnings, or requirements from the documentation.

3. **Why alternatives fail**: Explain technical reasons using concepts from the source material. Connect each alternative's issue to specific guidance in the docs.

4. **Best practices from source**: Cite specific best practices, patterns, or recommendations from the documentation. Quote or paraphrase relevant sections.

5. **Practical impact**: How this choice affects performance/maintainability/security based on what the documentation explains about these trade-offs.

**Important:**
- Quote or reference specific sections of the source documentation
- Use exact terminology from the docs
- Connect code patterns to documented best practices
- Explain WHY something is a best practice based on what the docs say
- Cite warnings, gotchas, or caveats mentioned in the source

Length: 3-5 paragraphs of technically accurate, documentation-grounded explanation.

{end_prompt}
