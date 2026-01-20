{prompt generate_optimal_code}
You are creating the CORRECT, IDIOMATIC code implementation for a focused learning scenario.

**CRITICAL CONSTRAINTS:**
- The optimal code must be PURELY GROUNDED in the provided context
- Do NOT add ANY flags, parameters, or code elements not present in {code_for_scenario}
- Do NOT add complexity beyond what's in {code_for_scenario}
- Keep the EXACT SAME flags/parameters as {code_for_scenario}
- Only fix syntax errors or make the existing code idiomatic
- Use ONLY information from: {sample_usage_scenario}, {code_for_scenario}, {key_considerations}

**Your task:**
Take {code_for_scenario} and make MINIMAL corrections to ensure it's syntactically correct and idiomatic. Do NOT add anything new.

Context:
- Scenario: {sample_usage_scenario}
- Base Code: {code_for_scenario}
- Complexity: {scenario_complexity}
- Considerations: {key_considerations}

**What you CAN do:**
- Fix syntax errors in {code_for_scenario}
- Correct parameter/flag formatting
- Fix quote styles
- Ensure proper spacing
- Make idiomatic what's already there

**What you CANNOT do:**
- Add flags not in {code_for_scenario} (e.g., if code has `--select X`, don't add `--target prod`)
- Add parameters not in {code_for_scenario}
- Combine multiple concepts if {code_for_scenario} has one concept
- Add code from page_content that's not in {code_for_scenario}
- Expand beyond the length of {code_for_scenario}
- Wrap in scripts if {code_for_scenario} is a command
- Add error handling, logging, or production features

**Example:**
- Input code_for_scenario: `dbt clone --select config.materialized:incremental`
- ✅ CORRECT optimal_code: `dbt clone --select config.materialized:incremental` (identical, already correct)
- ❌ WRONG optimal_code: `dbt clone --select state:modified+,config.materialized:incremental,state:old` (added flags not in input)

Provide only:
- optimal_code: The MINIMALLY corrected version of {code_for_scenario} (same flags/parameters, just syntactically correct)

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

You are generating alternative ${alternative_num} of 3 suboptimal code implementations.

**CRITICAL CONSTRAINTS:**
- Keep the same LENGTH and STYLE as the optimal code
- If optimal code is 1 line, alternative should be ~1 line
- If optimal code is 10 lines, alternative should be ~10 lines
- Do NOT add production complexity that wasn't in the optimal code
- Do NOT wrap in scripts if optimal code is a simple command
- Stay in the SAME TOOL/LANGUAGE as the optimal code

Each alternative must:
- Be syntactically correct and functional
- Work in the given scenario BUT have specific issues (wrong flag, suboptimal parameter, inefficient approach)
- Be clearly inferior to the optimal code
- Be SIMILAR in length and complexity to the optimal code
- DO NOT ADD ANY INLINE COMMENTS

Alternative types:
- Alternative 1: Performance/Efficiency issues (e.g., wrong selector, missing optimization flag, inefficient approach)
- Alternative 2: Security/Reliability issues (e.g., missing required parameter, brittle implementation, incorrect configuration)
- Alternative 3: Readability/Maintainability issues (e.g., overly complex syntax, unclear parameter values, poor flag choices)

Context:
- Scenario: {sample_usage_scenario}
- Optimal Code: {optimal_code}

For alternative ${alternative_num}, provide:
- alternative_code_${alternative_num}: Code with same length/style as optimal but with intentional issues
- issue_type_${alternative_num}: Category of issue (performance/security/readability)
- issue_description_${alternative_num}: Specific technical issue present (1-2 sentences)
{end_prompt}


