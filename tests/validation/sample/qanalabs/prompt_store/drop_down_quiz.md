{prompt Wrong_Answer_Generator}
You are provided with a list of code blanks and the correct values they replaced.

Your task is to generate 2–4 plausible but incorrect answers (distractors) for each blank. These should be:
- Syntactically and semantically plausible in the code context
- Common misconceptions, near-miss syntax, or related keywords
- Not obviously wrong or random

**CRITICAL: Code Formatting Rules**
- **Never wrap code in extra braces, quotes, or escape characters** (e.g., `{{{{` instead of `{{`)
- **Return code exactly as it would be written in the actual tool/language** (no markdown, no escaping)
- For Jinja/dbt: use `{{ }}` not `{{{{ }}}}`; for Python: use normal syntax; for SQL: use standard SQL
- All wrong answers must follow the same formatting rules as the correct answer

Return a JSON array with:
- placeholder_id: the placeholder being targeted (e.g., "__BLANK_1__")
- wrong_answers: an array of 2–4 strings that are incorrect choices

These will be used in multiple-choice fill-in-the-blank questions.
{end_prompt}


{prompt Code_extraction}
# Intelligent Code Extraction

You are extracting **only high-value, testable code snippets** from the provided documentation that demonstrate practical implementation and hands-on coding skills.

## Core Requirements

**Target Bloom's Taxonomy Levels 3-6** (Apply, Analyze, Evaluate, Create):
- How to configure services through code
- Implementation patterns and best practices
- API usage and integration code
- Error handling and troubleshooting patterns

## Extraction Criteria

### ✅ **EXTRACT code snippets that include:**
- **Service configuration**: Client initialization, authentication setup, service connections
- **API calls**: Request/response handling, method invocations, parameter passing
- **Data processing**: JSON parsing, response handling, data transformation
- **Error handling**: Try-catch blocks, exception handling, retry logic
- **Authentication flows**: Token acquisition, credential management, security patterns
- **Performance optimization**: Batch processing, async patterns, resource management
- **Integration patterns**: Service-to-service communication, webhook handling, event processing
- **Configuration management**: Environment setup, parameter configuration, resource provisioning

### ❌ **STRICTLY AVOID extracting:**

#### Non-Functional Code Examples
- Pseudo-code or incomplete snippets that won't compile/run
- Comments-only sections without actual implementation
- Generic programming examples not specific to Azure AI services
- Placeholder code with TODO comments or dummy values

#### Business Logic Without Technical Context
- General data processing without service integration
- UI/frontend code not related to API service consumption
- Database operations without API context
- Generic utility functions unrelated to technical implementation

#### Incomplete Code Fragments
- Single line statements without context
- Variable declarations without usage
- Import statements without accompanying implementation
- Code snippets missing critical dependencies or setup

#### Documentation-Only Content
- Code comments explaining concepts without implementation
- Configuration examples without actual code usage
- API reference listings without implementation examples
- Theoretical examples without practical service integration

## Critical Validation Tests

**Each code snippet MUST pass ALL these tests:**

1. **Technical Specificity Test**: Does it use specific APIs, SDKs, or technical frameworks?
2. **Functional Completeness Test**: Is this a working code block that demonstrates a complete operation?
3. **Implementation Relevance Test**: Does it show HOW to accomplish a specific technical task?
4. **Practical Value Test**: Would implementing this code help solve real-world implementation challenges?
5. **Standalone Utility Test**: Can this code be understood and adapted for practical implementations?

## Quality Filters

**Skip this document entirely if it contains primarily:**
- Conceptual explanations without code examples
- Business requirements without technical implementation
- Architecture diagrams without accompanying code
- Marketing content about platform capabilities
- Generic programming tutorials not service-specific
- Setup instructions without actual code implementation

**Technical Implementation Test**: Each code snippet should demonstrate "how to implement," "how to configure," or "how to integrate" rather than just "what exists" or "what's possible."

## Schema: `candidate_code_list`

```json
{
  "candidate_code_list": [
    {
      "code": "string (max 150 chars) - Representative code snippet from documentation",
      "code_explanation": "string - What the code does and its context within Azure AI implementation",
      "technical_level": "string - One of: configuration|implementation|constraint|procedure|integration"
    }
  ]
}
```

### Enhanced Fields:
- **`code`**: Actual code snippet that demonstrates service usage or technical implementation
- **`code_explanation`**: Context explaining the code's purpose and when to use it
- **`technical_level`**: Categorizes the type of technical implementation for better filtering

## Examples

### ✅ **GOOD Extractions (Service-specific, functional, testable):**
```json
{
  "code": "client = OpenAIClient(endpoint=endpoint, credential=KeyCredential(key))",
  "code_explanation": "Initializes API client with endpoint and subscription key for authentication",
  "technical_level": "configuration"
}
```

```json
{
  "code": "response = client.get_completions(model=\"gpt-3.5-turbo\", prompt=\"Hello\", max_tokens=100)",
  "code_explanation": "Makes completion request to API service with specific model and token limit parameters",
  "technical_level": "implementation"
}
```

```json
{
  "code": "if response.status_code == 429: time.sleep(int(response.headers.get('Retry-After', 60)))",
  "code_explanation": "Handles rate limiting from API services by implementing exponential backoff retry logic",
  "technical_level": "procedure"
}
```

### ❌ **BAD Extractions (generic, incomplete, non-functional):**
```json
{
  "code": "# Initialize the client",
  "reason_bad": "Comment-only content without actual implementation code"
}
```

```json
{
  "code": "import requests",
  "reason_bad": "Generic import statement without Azure AI service context or usage"
}
```

```json
{
  "code": "def process_data(data): # TODO: implement",
  "reason_bad": "Incomplete function with placeholder content, not functional Azure AI code"
}
```

```json
{
  "code": "result = some_function()",
  "reason_bad": "Generic function call without service specificity or context"
}
```

## Code Types to Prioritize

### Configuration Level
- Service client initialization
- Authentication setup
- Environment configuration
- Connection string handling

### Implementation Level
- API method calls
- Request/response processing
- Data transformation
- Service integration patterns

### Constraint Level
- Rate limiting handling
- Token limit management
- Resource quota enforcement
- Error boundary implementation

### Procedure Level
- Multi-step workflows
- Batch processing patterns
- Retry mechanisms
- Deployment automation

### Integration Level
- Service-to-service communication
- Event handling
- Webhook processing
- Pipeline orchestration

## Red Flag Code Patterns to Avoid

If a potential code snippet contains these patterns, it's likely NOT a good technical extraction:
- Comments without accompanying code
- Generic variable names without service context (e.g., `client`, `response` without service specificity)
- Incomplete try-catch blocks without implementation
- Pseudo-code or placeholder functions
- Import statements without usage examples
- Configuration examples without code implementation

## Pre-Processing Check

Before extracting code, evaluate the source:

1. **Code Density**: Does this document contain actual, functional code examples for Azure AI services?
2. **Implementation Focus**: Are the code examples showing HOW to use Azure AI services, not just WHAT they can do?
3. **Practical Value**: Would these code snippets help someone actually implement Azure AI solutions?

**If the source fails these checks, return:**
```json
{
  "candidate_code_list": [],
  "skip_reason": "Document contains primarily conceptual content without functional Azure AI implementation code"
}
```

## Output Instructions

- **Minimum 3 code snippets** from technical documents (or empty if no valid implementation code exists)
- **Maximum 10 code snippets** to maintain quality over quantity
- Prioritize code containing specific Azure AI service names, SDK methods, or API calls
- Each snippet must be verifiable through Azure AI SDK documentation or hands-on testing
- Ensure each code example represents practical knowledge required for Azure AI implementation
- Focus on code that demonstrates real-world Azure AI service integration patterns

{end_prompt}


{prompt Scenario_generation}
# Quiz Question Generator for Code Completion

You are creating **quiz questions** from extracted code snippets that challenge learners to complete code based on a problem statement.

## Core Requirements

**Transform extracted code into quiz questions** that:
- **Single concept focus**: Each question tests ONE specific concept or technique
- **Problem-based**: Present a task/challenge that requires completing the code, NOT an explanation of when to use it
- **Minimal expansion**: Keep code focused and concise (typically 5-15 lines max)
- **Clear objective**: One clear problem that the code solves
- **No answer spoilers**: Don't reveal technical details that give away the solution

## **CRITICAL CONSTRAINTS FOR TEACHING**

**❌ NEVER create scenarios that:**
- Combine multiple concepts (e.g., CI/CD pipelines with testing, docs, deployment)
- Combine multiple flags, parameters, or selection criteria in one command
- Include multi-step workflows spanning different operations
- Exceed 15 lines of code unless the single concept requires it
- Add environment setup, artifact downloading, or infrastructure concerns
- Show production-ready "complete" implementations with many features
- Use complex compound selection logic (e.g., `state:modified+,config.materialized:incremental,state:old`)
- **Wrap code in extra braces, quotes, or escape characters (e.g., `{{{{` instead of `{{`)**
- **Add markdown formatting, backticks, or code fences to the code itself**

**✅ ALWAYS create scenarios that:**
- Focus on demonstrating ONE core concept from the input code
- Use ONE flag, parameter, or selection criterion at a time
- Keep the code snippet small and digestible (ideally 1-5 lines)
- Show the simplest realistic example of the concept
- Have business context in 1-2 sentences maximum
- Use the tool's native syntax without unnecessary additions
- If input code is complex, simplify to demonstrate just ONE aspect
- **Return code exactly as it would be written in the actual tool/language (no wrapping, no escaping)**
- **For Jinja/dbt: use `{{ }}` not `{{{{ }}}}`; for Python: use normal syntax; for SQL: use standard SQL**

## Input Processing

You will receive a code extraction object with these fields:
- `doc_name`: The tool/technology this code belongs to (e.g., "dbt(data build tool)", "Kubernetes", "Docker")
- `code`: The core code snippet (max 150 chars)
- `code_explanation`: What the code does and its context
- `technical_level`: configuration|implementation|constraint|procedure|integration
- Additional metadata: `id`, `url`, `page_content`, `bloom_details`

## **CRITICAL RULE: Stay Within Tool Context & Keep It Simple**

**❌ NEVER:**
- Wrap the original code in a different language or framework
- Combine multiple concepts into one scenario
- Combine multiple flags or parameters in one command
- Create multi-step workflows or pipelines

**✅ ALWAYS:**
- Use only the tool/technology from `doc_name`
- Focus on ONE concept per scenario
- Use ONE flag/parameter/feature at a time
- Keep code minimal (1-5 lines ideally, max 15 lines)
- Simplify complex input code to focus on ONE aspect

## What to Create

### ✅ **DO:**
- Present a problem/task that requires the learner to complete the code (1-2 sentences)
- Frame as "You need to...", "Complete the command to...", "Write code to..."
- Minimal code showing the single concept clearly
- Simple, realistic challenge within the tool's native syntax
- Keep key_considerations minimal or empty to avoid giving away answers

### ❌ **DON'T:**
- Explain when/why to use the code (this gives away the answer)
- Include technical hints that reveal the solution (like specific flags or parameters)
- Combine multiple operations or concepts
- Add setup, teardown, or infrastructure code
- Create workflows that chain multiple commands
- Write verbose business scenarios

## Examples

### Example 1: Simple flag usage

**Input:** `dbt clone --select state:modified+`

**✅ GOOD (quiz question format - presents a problem to solve):**
```json
{
  "sample_usage_scenario": "In a feature branch, you need to clone only the models that were modified in your current branch compared to production. Complete the dbt command:",
  "code_for_scenario": "dbt clone --select state:modified+",
  "scenario_complexity": "intermediate",
  "key_considerations": ""
}
```

**❌ BAD (explains when to use it - gives away the answer):**
```json
{
  "sample_usage_scenario": "You want to clone only the models that were modified in your current branch.",
  "code_for_scenario": "dbt clone --select state:modified+",
  "scenario_complexity": "intermediate",
  "key_considerations": "Requires dbt 1.6+ and a state manifest to compare against. The + includes downstream dependencies."
}
```

### Example 2: Simplifying complex input

**Input:** `dbt clone --select state:modified+,config.materialized:incremental,state:old`

**✅ GOOD (simplified to focus on ONE aspect - config.materialized filtering):**
```json
{
  "sample_usage_scenario": "You need to clone only the models in your project that use incremental materialization. Complete the command:",
  "code_for_scenario": "dbt clone --select config.materialized:incremental",
  "scenario_complexity": "basic",
  "key_considerations": ""
}
```

**OR focus on a different aspect - state:old filtering:**
```json
{
  "sample_usage_scenario": "You need to clone only pre-existing models from the previous deployment, excluding any brand-new models. Complete the command:",
  "code_for_scenario": "dbt clone --select state:old",
  "scenario_complexity": "intermediate",
  "key_considerations": ""
}
```

### Example 3: Multi-step workflow (BAD)

**❌ BAD (combines multiple concepts, too verbose):**
```json
{
  "sample_usage_scenario": "A data engineering team implements a CI/CD pipeline where feature branches are tested against production state without rebuilding unchanged models. When developers push changes to their dbt models, the pipeline needs to identify which models were modified and run only those models plus their downstream dependencies...",
  "code_for_scenario": "# CI/CD pipeline for incremental dbt testing\nexport DBT_PROFILES_DIR=./profiles\nexport DBT_TARGET=ci\nexport DBT_STATE_PATH=./artifacts/prod\n\naws s3 sync s3://analytics-artifacts/prod/ $DBT_STATE_PATH/\n\ndbt deps --profiles-dir $DBT_PROFILES_DIR\ndbt run -s state:modified+ --defer --state $DBT_STATE_PATH --target $DBT_TARGET\ndbt test -s state:modified+ --defer --state $DBT_STATE_PATH --target $DBT_TARGET\ndbt docs generate...",
  "scenario_complexity": "intermediate",
  "key_considerations": "..."
}
```
**Why it's bad:** Combines setup, multiple dbt commands (run, test, docs), AWS operations, environment variables, and multiple flags. This teaches too many things at once.

## Output Schema

```json
{
  "sample_usage_scenario": "string - 1-2 sentence PROBLEM STATEMENT or TASK that requires completing the code. Frame as 'You need to...', 'Complete the command to...', NOT as 'You want to...' or 'When you want...'",
  "code_for_scenario": "string - Minimal code (1-5 lines ideally, max 15) demonstrating ONE SINGLE concept using the SAME TOOL as input. If input is complex, simplify to ONE aspect.",
  "scenario_complexity": "string - One of: basic|intermediate|advanced",
  "key_considerations": "string - Leave EMPTY or provide only non-revealing context. Do NOT include technical details that give away the solution (like specific flags, parameters, or version requirements)."
}
```

## Quality Checklist

Before finalizing, verify:

1. **Single Concept**: Does it test only ONE thing? ONE flag/parameter/feature?
2. **Simplified**: If input had multiple flags/concepts, did you simplify to just ONE?
3. **Tool Consistency**: Uses only the technology from `doc_name`?
4. **Brevity**: Is the question 1-2 sentences? Is the code 1-5 lines (max 15)?
5. **No Multi-Step Workflows**: Does it avoid chaining multiple operations?
6. **No Compound Logic**: Does it avoid combining multiple flags, parameters, or selection criteria?
7. **Realistic**: Could this problem occur in practice?
8. **Quiz Format**: Is sample_usage_scenario a problem/task (not an explanation)?
9. **No Spoilers**: Does key_considerations avoid revealing the answer?
10. **Clear Challenge**: Is it obvious what task the learner needs to complete?

{end_prompt}


