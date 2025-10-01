# Example 5: Environment Variables Best Practices

This example demonstrates how to properly manage API keys and sensitive configuration using environment variables in Agent Actions.

## Why Use Environment Variables?

✅ **Security**: Keep API keys out of version control
✅ **Flexibility**: Different keys for dev/staging/prod
✅ **Safety**: No accidental commits of secrets
✅ **Team workflows**: Each developer uses their own keys
✅ **CI/CD**: Easy integration with deployment pipelines

## Environment Variable Syntax

Agent Actions supports two formats for referencing environment variables:

```yaml
# Format 1: ${VAR_NAME} (recommended)
api_key: ${OPENAI_API_KEY}

# Format 2: VAR_NAME (also supported)
api_key: OPENAI_API_KEY
```

Both formats are equivalent. Use whichever you prefer.

## Basic Setup

### 1. Create .env File

Create `.env` in your project root (add to `.gitignore`!):

```bash
# .env
export OPENAI_API_KEY=sk-proj-abc123...
export ANTHROPIC_API_KEY=sk-ant-xyz789...
export GEMINI_API_KEY=AIza...
export GROQ_API_KEY=gsk_...
export DEEPSEEK_API_KEY=sk-...
export PERPLEXITY_API_KEY=pplx-...
```

### 2. Add to .gitignore

```bash
# .gitignore
.env
.env.*
*.key
secrets/
```

### 3. Load Variables

```bash
# Load environment variables
source .env

# Verify they're set
echo $OPENAI_API_KEY
```

### 4. Use in Config

```yaml
# agent_actions.yml
model_vendor: openai
model_name: gpt-4o-mini
api_key: ${OPENAI_API_KEY}    # References environment variable
```

## Complete Example

### Project Structure

```
my-project/
├── .env                    # Environment variables (in .gitignore)
├── .env.example            # Template for other developers
├── .gitignore              # Excludes .env
├── agent_actions.yml       # Uses ${VAR_NAME} syntax
└── workflows/
    └── process.yml
```

### .env (NOT in git)

```bash
# API Keys - DO NOT COMMIT THIS FILE
export OPENAI_API_KEY=sk-proj-abc123xyz...
export ANTHROPIC_API_KEY=sk-ant-api03-xyz...
export GEMINI_API_KEY=AIzaSyDxxx...
export GROQ_API_KEY=gsk_xxx...

# Optional: Custom configuration
export AGENT_ACTIONS_DEFAULT_VENDOR=openai
export AGENT_ACTIONS_DEFAULT_MODEL=gpt-4o-mini
```

### .env.example (IN git)

```bash
# API Keys - Copy this to .env and fill in your keys
export OPENAI_API_KEY=your-key-here
export ANTHROPIC_API_KEY=your-key-here
export GEMINI_API_KEY=your-key-here
export GROQ_API_KEY=your-key-here

# Optional: Custom configuration
export AGENT_ACTIONS_DEFAULT_VENDOR=openai
export AGENT_ACTIONS_DEFAULT_MODEL=gpt-4o-mini
```

### .gitignore

```
# Environment variables
.env
.env.local
.env.*.local
*.key

# OS files
.DS_Store
Thumbs.db

# IDE
.vscode/
.idea/
*.swp

# Output
outputs/
results/
*.log
```

### agent_actions.yml

```yaml
# Reference environment variables using ${VAR} syntax
model_vendor: openai
model_name: gpt-4o-mini
api_key: ${OPENAI_API_KEY}

temperature: 0.7
max_tokens: 2000
```

### workflows/multi-vendor.yml

```yaml
# Different actions use different API keys
actions:
  - name: openai_step
    model_vendor: openai
    model_name: gpt-4o-mini
    api_key: ${OPENAI_API_KEY}
    # ...

  - name: claude_step
    model_vendor: anthropic
    model_name: claude-3-5-sonnet-20241022
    api_key: ${ANTHROPIC_API_KEY}
    # ...

  - name: gemini_step
    model_vendor: gemini
    model_name: gemini-1.5-pro
    api_key: ${GEMINI_API_KEY}
    # ...
```

## Multiple Environments

### Development vs Production

```
.env.development          # Dev API keys (lower limits, test keys)
.env.production          # Production API keys (higher limits)
.env.staging             # Staging environment
```

#### .env.development

```bash
export OPENAI_API_KEY=sk-proj-dev-test123...
export ANTHROPIC_API_KEY=sk-ant-dev-test456...

# Use cheaper models in dev
export DEFAULT_MODEL=gpt-4o-mini
```

#### .env.production

```bash
export OPENAI_API_KEY=sk-proj-prod-real789...
export ANTHROPIC_API_KEY=sk-ant-prod-real012...

# Use better models in production
export DEFAULT_MODEL=gpt-4o
```

#### Loading Environment-Specific Config

```bash
# Development
source .env.development
agent-actions run workflow --input dev-data.jsonl

# Production
source .env.production
agent-actions run workflow --input prod-data.jsonl
```

## Security Best Practices

### 1. Never Hardcode Keys

```yaml
# ❌ BAD: Hardcoded API key
api_key: sk-proj-abc123xyz789...

# ✅ GOOD: Environment variable
api_key: ${OPENAI_API_KEY}
```

### 2. Use .gitignore

```bash
# Always ignore environment files
.env
.env.*
!.env.example    # But DO commit the example
```

### 3. Provide .env.example

Help teammates set up their environment:

```bash
# .env.example
export OPENAI_API_KEY=your-openai-key-here
export ANTHROPIC_API_KEY=your-anthropic-key-here

# Instructions:
# 1. Copy this file to .env
# 2. Replace placeholder values with your actual API keys
# 3. Never commit .env to version control
```

### 4. Check Variables Are Set

```bash
# Before running workflows, verify
if [ -z "$OPENAI_API_KEY" ]; then
    echo "Error: OPENAI_API_KEY not set"
    exit 1
fi

agent-actions run workflow --input data.jsonl
```

### 5. Use Read-Only Keys When Possible

If vendor supports read-only or restricted API keys, use those for development.

## CI/CD Integration

### GitHub Actions

```yaml
# .github/workflows/run-workflows.yml
name: Run Agent Actions

on: [push]

jobs:
  process:
    runs-on: ubuntu-latest

    steps:
      - uses: actions/checkout@v3

      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'

      - name: Install Agent Actions
        run: pip install agent-actions

      - name: Run Workflow
        env:
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
        run: |
          agent-actions run workflows/process.yml --input data.jsonl
```

**Setting GitHub Secrets**:
1. Go to Repository → Settings → Secrets and variables → Actions
2. Click "New repository secret"
3. Add `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, etc.

### GitLab CI

```yaml
# .gitlab-ci.yml
process_data:
  image: python:3.11
  script:
    - pip install agent-actions
    - agent-actions run workflows/process.yml --input data.jsonl
  variables:
    OPENAI_API_KEY: $OPENAI_API_KEY
    ANTHROPIC_API_KEY: $ANTHROPIC_API_KEY
```

**Setting GitLab Variables**:
1. Go to Project → Settings → CI/CD → Variables
2. Add variables, mark as "Protected" and "Masked"

### Docker

```dockerfile
# Dockerfile
FROM python:3.11

WORKDIR /app
COPY . /app

RUN pip install agent-actions

# Don't bake secrets into image!
# Pass them at runtime via -e flags

CMD ["agent-actions", "run", "workflows/process.yml"]
```

```bash
# Run with environment variables
docker run -e OPENAI_API_KEY=$OPENAI_API_KEY \
           -e ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY \
           my-agent-actions-image
```

## Advanced Patterns

### 1. Conditional Vendor Selection

Use environment variables to control which vendor:

```bash
# .env
export DEFAULT_VENDOR=openai
export OPENAI_API_KEY=sk-proj-...
export ANTHROPIC_API_KEY=sk-ant-...
```

```yaml
# agent_actions.yml
model_vendor: ${DEFAULT_VENDOR}    # Use env var for vendor
model_name: gpt-4o-mini
api_key: ${${DEFAULT_VENDOR}_API_KEY}    # Dynamic key selection
```

Note: Dynamic variable selection (`${${VAR}}`) may not be supported. Instead, use conditional loading:

```bash
# run.sh
if [ "$DEFAULT_VENDOR" = "openai" ]; then
    export API_KEY=$OPENAI_API_KEY
elif [ "$DEFAULT_VENDOR" = "anthropic" ]; then
    export API_KEY=$ANTHROPIC_API_KEY
fi

agent-actions run workflow --input data.jsonl
```

```yaml
# agent_actions.yml
model_vendor: ${DEFAULT_VENDOR}
api_key: ${API_KEY}    # Single variable, set by script
```

### 2. Per-Workflow API Keys

Different workflows can use different API keys:

```bash
# .env
export OPENAI_CHEAP_KEY=sk-proj-dev-...       # Low-limit key
export OPENAI_PREMIUM_KEY=sk-proj-prod-...    # High-limit key
```

```yaml
# workflows/cheap-tasks.yml
api_key: ${OPENAI_CHEAP_KEY}

# workflows/important-tasks.yml
api_key: ${OPENAI_PREMIUM_KEY}
```

### 3. Shared Secrets Store

Use cloud secret managers:

```bash
# fetch-secrets.sh
#!/bin/bash

# AWS Secrets Manager
export OPENAI_API_KEY=$(aws secretsmanager get-secret-value \
    --secret-id openai-api-key --query SecretString --output text)

# Google Secret Manager
export ANTHROPIC_API_KEY=$(gcloud secrets versions access latest \
    --secret="anthropic-api-key")

# Azure Key Vault
export GEMINI_API_KEY=$(az keyvault secret show \
    --vault-name my-vault --name gemini-api-key --query value -o tsv)

# Now run workflows
agent-actions run workflows/process.yml --input data.jsonl
```

## Validation

Agent Actions validates environment variables at runtime:

### Missing Variable Error

```yaml
# Config
api_key: ${MISSING_VAR}
```

```
Error: Environment variable 'MISSING_VAR' is not set

Context:
  agent: my_agent
  env_var: MISSING_VAR
  config_value: ${MISSING_VAR}
  operation: get_api_key

Hint: Set the environment variable:
  export MISSING_VAR=your-api-key
```

### Empty Variable Error

```bash
export OPENAI_API_KEY=""    # Set but empty
```

```
Error: Environment variable 'OPENAI_API_KEY' is set but empty

Context:
  agent: my_agent
  env_var: OPENAI_API_KEY
  config_value: ${OPENAI_API_KEY}
  operation: get_api_key

Hint: Provide a value: export OPENAI_API_KEY=your-api-key
```

## Troubleshooting

### Issue 1: "Environment variable not set"

**Cause**: Variable not exported or .env not sourced

**Solution**:
```bash
# Check if variable is set
echo $OPENAI_API_KEY

# If empty, source .env
source .env

# Verify again
echo $OPENAI_API_KEY
```

### Issue 2: "API authentication failed"

**Cause**: Variable is set but key is invalid

**Solution**:
```bash
# Check the key value (first few chars)
echo ${OPENAI_API_KEY:0:10}

# Verify it starts with expected prefix
# OpenAI: sk-proj- or sk-
# Anthropic: sk-ant-
# Gemini: AIza
```

### Issue 3: Variables not loading in subprocess

**Cause**: Variables not exported

**Solution**:
```bash
# ❌ BAD: Not exported
OPENAI_API_KEY=sk-proj-...

# ✅ GOOD: Exported
export OPENAI_API_KEY=sk-proj-...
```

## Team Onboarding

### Setup Script

Create `setup.sh` for new team members:

```bash
#!/bin/bash
# setup.sh - Set up development environment

echo "Setting up Agent Actions environment..."

# Check if .env exists
if [ ! -f .env ]; then
    echo "Creating .env from .env.example..."
    cp .env.example .env
    echo "✓ Created .env"
    echo "⚠ Please edit .env and add your API keys"
    exit 0
fi

# Load .env
source .env

# Validate required variables
REQUIRED_VARS=("OPENAI_API_KEY" "ANTHROPIC_API_KEY")

for VAR in "${REQUIRED_VARS[@]}"; do
    if [ -z "${!VAR}" ]; then
        echo "❌ $VAR is not set in .env"
        exit 1
    fi
    echo "✓ $VAR is set"
done

echo "✅ Environment setup complete!"
```

### README Instructions

```markdown
## Setup

1. Clone the repository
2. Run setup script: `./setup.sh`
3. Edit `.env` with your API keys
4. Run workflows: `agent-actions run workflows/process.yml`

## Getting API Keys

- OpenAI: https://platform.openai.com/api-keys
- Anthropic: https://console.anthropic.com/
- Google AI: https://makersuite.google.com/app/apikey
- Groq: https://console.groq.com/keys
```

## Next Steps

- [Example 6: Tool Actions](./06-tool-actions.md) - Non-LLM actions
- [Example 7: Batch Mode](./07-batch-mode.md) - High-volume processing
- [Core Concepts: Configuration Hierarchy](../../core-concepts/configuration-hierarchy.md)
