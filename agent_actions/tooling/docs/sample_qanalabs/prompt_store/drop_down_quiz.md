{prompt Code_extraction}
Extract code blocks and examples from technical documentation.

**Supports ALL languages/technologies:** Python, Terraform, Azure CLI, Kubernetes YAML, Docker, Bash, PowerShell, SQL, Go, Rust, Java, C#, JavaScript, TypeScript, and more.

From the page_content, identify:
- candidate_code_list: Array of code examples, each containing:
  - code_block: The actual code snippet (preserve exact syntax - do NOT escape special characters)
  - description: Brief description of what this code does
  - language: Programming language or tool (python, terraform, azure-cli, kubernetes, docker, bash, powershell, sql, go, rust, java, csharp, javascript, typescript, jinja, yaml, json, etc.)
  - complexity: beginner/intermediate/advanced
  - applicable_context: Where/when this code would be used

Focus on:
- Complete, working code examples
- Code that demonstrates specific concepts, patterns, or best practices
- Code that could be compared with alternative implementations
- Configuration examples (Terraform resources, Kubernetes manifests, Docker Compose, etc.)
- CLI commands with flags/parameters (Azure CLI, AWS CLI, kubectl, etc.)
- Functions, classes, or modules that solve specific problems
- SQL queries or database operations
- Infrastructure as Code examples

Avoid:
- Incomplete snippets or pseudocode
- Code fragments missing critical context
- Output examples (console output, logs) - extract ONLY executable code

**Important:** Preserve exact syntax including:
- Template variables (double braces, curly-percent tags, dollar-braces)
- Special characters in any language
- Indentation and formatting
- Comments

Only extract code that is clearly presented in the page_content.
{end_prompt}


{prompt Scenario_generation}
Generate a realistic usage scenario for the extracted code.

**Works for ANY technology:** Python, Terraform, Azure, Kubernetes, Docker, Bash, SQL, Go, and more.

Based on the code_block, language, and context, create:

Output:
- sample_usage_scenario: Practical situation where this code is needed (2-3 sentences describing the business/technical problem or requirement that this code solves)
- code_for_scenario: The code from the candidate (may need minor cleanup for syntax, but preserve all functionality)
- scenario_complexity: beginner/intermediate/advanced (matching the code complexity and prerequisite knowledge)
- key_considerations: Important technical points to consider (1-2 sentences about performance, security, maintainability, scalability, cost, or other trade-offs)

The scenario should:
- Be specific and realistic for that technology domain
- Clearly state the technical requirement or constraint
- Set up a situation where multiple implementations could work, but one is optimal
- Include relevant context (e.g., for cloud: mention scale, for Python: mention use case, for SQL: mention data volume)
- Be relatable to professionals using that technology

**Technology-specific scenario examples:**

Infrastructure (Terraform, CloudFormation):
- Provisioning resources, managing state, handling different environments, cost optimization

Cloud CLI (Azure, AWS, GCP):
- Deployment automation, resource management, configuration, monitoring

Containers (Docker, Kubernetes):
- Image building, orchestration, scaling, networking, security

Programming (Python, Go, Java):
- Data processing, API integration, algorithm optimization, error handling

Database (SQL, NoSQL):
- Query optimization, data modeling, indexing, transactions

DevOps (Bash, PowerShell, CI/CD):
- Automation, deployment, testing, environment setup

Style: Professional, technical, focused on real-world application
{end_prompt}
