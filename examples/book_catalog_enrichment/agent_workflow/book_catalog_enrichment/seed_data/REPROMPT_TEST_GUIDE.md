# Reprompt Testing Guide

This guide explains how to test the **reprompt recovery mechanism** with the book catalog enrichment workflow.

## Overview

The reprompt feature has been enabled on the `write_description` action to validate that marketing descriptions contain at least 50 words. When the LLM generates a response with fewer than 50 words, it will be automatically re-executed with feedback about the requirement.

## Setup

### 1. Validation Functions

The validation functions are defined in:
```
agent_config/reprompt_validations.py
```

Three validations are available:
- `check_description_word_count` - Ensures marketing description has at least 50 words
- `check_description_exists` - Ensures the field exists and is not empty
- `check_no_placeholders` - Ensures no placeholder text like "TODO" or "[INSERT]"

Currently enabled: **`check_description_word_count`**

### 2. Configuration

In `agent_config/book_catalog_enrichment.yml`, the `write_description` action is configured with:

```yaml
- name: write_description
  reprompt:
    validation: check_description_word_count  # UDF name
    max_attempts: 3                           # Try up to 3 times
    on_exhausted: return_last                 # Return best attempt if all fail
```

### 3. Run Mode

The workflow is set to **online mode** for immediate feedback:
```yaml
defaults:
  run_mode: online  # See reprompt in action immediately
  prompt_debug: true  # See the feedback messages
```

## Testing

### Run the Workflow

From the agent-actions directory:

```bash
cd /Users/muizz/Documents/codeshop/agent-actions

# Run with the test data (2 books)
agac run -a book_catalog_enrichment -i books_test_reprompt.json

# Or run with the full catalog
agac run -a book_catalog_enrichment
```

### What to Expect

1. **If LLM generates short description (< 50 words):**
   - ❌ Validation fails
   - 📝 Feedback message is generated:
     ```
     ---
     Your response failed validation: Marketing description must contain at least 50 words. Please provide a more detailed and compelling description.

     Your response: {"marketing_description": "Short description here"}

     Please correct and respond again.
     ```
   - 🔄 LLM is called again with this feedback appended to the original prompt
   - 📊 Process repeats up to 3 times (max_attempts)

2. **If LLM generates adequate description (>= 50 words):**
   - ✅ Validation passes on first attempt
   - ✨ No reprompt needed
   - 📝 No recovery metadata added

3. **Output includes recovery metadata:**
   ```json
   {
     "source_guid": "...",
     "content": {
       "marketing_description": "..."
     },
     "_recovery": {
       "reprompt": {
         "attempts": 2,
         "passed": true,
         "validation": "check_description_word_count"
       }
     }
   }
   ```

### Check the Results

Results are written to:
```
agent_io/target/write_description/books_test_reprompt.json
```

Look for the `_recovery` field to see if reprompt was triggered.

### View Logs

With `prompt_debug: true`, you'll see:
- Original prompts sent to LLM
- Feedback messages when validation fails
- Number of reprompt attempts
- Final validation status

## Testing Different Scenarios

### Test 1: Force Short Descriptions

Modify the prompt or model settings to intentionally generate short descriptions:

```yaml
# In agent_config/book_catalog_enrichment.yml
model_name: deepseek-r1:1.5b  # Smaller model more likely to generate short text
```

### Test 2: Change Validation

Switch to a different validation in the YAML:

```yaml
reprompt:
  validation: check_no_placeholders  # Test placeholder detection
```

### Test 3: Test Exhaustion

Set `max_attempts: 1` to see what happens when reprompt exhausts:

```yaml
reprompt:
  max_attempts: 1
  on_exhausted: return_last  # Or "raise" to see error
```

### Test 4: Batch Mode

Change to batch mode to test batch reprompt:

```yaml
defaults:
  run_mode: batch
```

In batch mode, failed records are resubmitted as a new batch with feedback.

## Validation Function Testing

Test the validation functions directly:

```bash
cd /Users/muizz/Documents/codeshop/agent_action_test/qanalabs/agent_workflow/book_catalog_enrichment/agent_config

python reprompt_validations.py  # Lists registered functions

# Test specific validation
python -c "
from reprompt_validations import check_description_word_count
result = check_description_word_count({'marketing_description': 'Short text'})
print(f'Passes validation: {result}')
"
```

## Recovery Statistics

After running, check the manifest for recovery stats:

```bash
cat agent_io/target/.manifest.json | jq '.actions.write_description.recovery_stats'
```

Expected output:
```json
{
  "retry_count": 0,
  "reprompt_count": 2  # Number of records that needed reprompt
}
```

## Troubleshooting

### Validation Not Triggered

1. **Check the validation is registered:**
   ```bash
   python agent_config/reprompt_validations.py
   ```

2. **Verify YAML configuration:**
   - Ensure `reprompt:` block is properly indented under the action
   - Check validation name matches the function name

3. **Check agent_actions is importable:**
   ```bash
   python -c "from agent_actions import reprompt_validation; print('OK')"
   ```

### All Validations Pass on First Try

The model is generating good content! Try:
- Using a smaller/weaker model
- Increasing the word count requirement (edit the validation function)
- Testing with a different validation (e.g., `check_no_placeholders`)

### Import Errors

Make sure agent-actions is installed:
```bash
cd /path/to/agent-actions
uv pip install -e .
```

## Next Steps

1. **Create Custom Validations:** Add more validation functions to `reprompt_validations.py`
2. **Test Combined Recovery:** Enable both retry and reprompt to see them work together
3. **Production Use:** Switch back to batch mode for large-scale processing
4. **Monitor Stats:** Use recovery statistics to track validation quality

## References

- **Implementation Summary:** `/Users/muizz/Documents/codeshop/agent-actions/docs/features/REPROMPT_IMPLEMENTATION_SUMMARY.md`
- **RFC:** `/Users/muizz/Documents/codeshop/agent-actions/docs/specs/RFC_recovery.md`
- **Test Coverage:** 76/76 tests passing (100%)
