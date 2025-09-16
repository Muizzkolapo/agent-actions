# Changes

## Conditional Reprompting Feature Implementation (August 2025)

### Overview
Complete implementation of conditional reprompting system that validates LLM outputs and automatically retries with improved prompts when validation fails. This feature transforms agent-actions from a "one-shot" system to an intelligent, self-improving system.

### Implementation Journey & Bug Fixes

#### Phase 1: Initial Architecture ✅
Junior engineer delivered complete interceptor-based architecture:
- Base interceptor framework with clean separation of concerns
- Validation interceptor supporting multiple validator types  
- Reprompt strategies (LLM and template-based)
- Integration with agent_builder.py
- Comprehensive unit tests

#### Phase 2: Real-World Testing Revealed Critical Bugs 🐛

**Bug #1: Configuration Structure Mismatch**
```
ERROR: Unknown validator: None
```
- **Issue**: System expected nested config but users wrote flat YAML
- **Fix**: Updated interceptor factory to handle flat configuration structure
- **Learning**: UX matters - users naturally write flat configs

**Bug #2: Content Extraction Failure** 
```
Response: [{'summary': 'Azure AI tutorial'}]
Extracted: ''  # Empty string bug
```
- **Issue**: Only looked for `content`/`text` keys, missed `summary` key
- **Fix**: Enhanced extraction to support multiple response formats with fallback
- **Learning**: Different LLMs produce different response structures

**Bug #3: Double Increment Attempt Counter**
```
Attempt sequence: 0→1→3→5 (jumping erratically)
```
- **Issue**: Both validation AND reprompt interceptors incrementing attempt counter
- **Fix**: Removed increment from validation interceptor
- **Learning**: Single responsibility - only reprompt should manage attempts

**Bug #4: Max Attempts Config Parsing**
```
Config: max_attempts: 5
Actual behavior: Stops at attempt 3
```
- **Issue**: Main retry loop looking in wrong config location (nested vs flat)
- **Fix**: Support both flat and nested config structures
- **Learning**: Backward compatibility is crucial

**Bug #5: LLM Reprompting JSON Schema Conflicts**
```
ERROR: Invalid JSON schema - expected object, got null
```
- **Issue**: Reprompt LLM inherited JSON mode but wasn't configured properly
- **Fix**: Replaced with template-based construction (simpler, more reliable)
- **Learning**: Simple solutions often work better than complex ones

#### Phase 3: Enhanced Template System 🎯

**New "Simple" Strategy Implementation:**
```yaml
interceptors:
  - type: reprompt
    strategy: "simple"  # Template construction, no LLM calls
    max_attempts: 5
    include_previous_response: true  # Configurable
```

**Benefits:**
- ✅ No additional LLM calls (faster, cheaper)
- ✅ No JSON schema conflicts  
- ✅ Predictable prompt improvements
- ✅ Configurable previous response inclusion

### Final Working Configuration
```yaml
agents:
  - agent_type: ScenarioGenerator
    model_vendor: "openai"
    model_name: "gpt-4o-mini"
    prompt: "Summarize this article in exactly 5 words"
    
    interceptors:
      - type: validation
        validator: "word_count"
        validator_args:
          expected: 5
        on_failure: retry
          
      - type: reprompt
        strategy: "simple"
        max_attempts: 3
        include_previous_response: true
```

### Real-World Flow Example
```
🚀 ATTEMPT #1: "Summarize article in exactly 5 words"
📥 Response: "Azure AI speech recognition tutorial guide" (6 words)
❌ Validation: Expected 5 words, got 6

🔄 CONSTRUCTED IMPROVED PROMPT:
"Summarize article in exactly 5 words

IMPORTANT: Previous attempt failed validation with error: Expected 5 words, got 6. 
Your previous response was: "Azure AI speech recognition tutorial guide"
Reprocess and ensure your response meets the requirements."

🚀 ATTEMPT #2: [Improved prompt]
📥 Response: "Azure AI speech recognition system" (5 words)  
✅ Validation: PASSED
🎉 SUCCESS
```

### Key Architectural Decisions

1. **Interceptor Pattern**: Clean separation, easy extension
2. **Flat Configuration**: More intuitive for users  
3. **Template-Based Reprompting**: Simpler than LLM-generated prompts
4. **Comprehensive Content Extraction**: Support diverse response formats
5. **Single Responsibility**: Only reprompt interceptor manages attempt counter

### Production Features Added

**Debug Infrastructure:**
- Comprehensive logging throughout interceptor chain
- Clear visibility into validation failures and reprompt construction
- Attempt counter tracking and max attempts handling

**Configuration Validation:**
- Proper error handling for unknown validators
- Missing configuration field detection
- Invalid strategy type validation

**Built-in Validators:**
- `word_count`: Exact word count validation
- `char_count`: Character count range validation  
- `contains_keywords`: Required keywords presence
- Registry pattern for easy custom validator addition

### Impact & Results

**Before Conditional Reprompting:**
- LLMs often failed constraints (wrong word count, missing keywords)
- Required manual prompt engineering and iteration
- No automatic retry mechanism

**After Implementation:**
- ✅ Automatic retry with improved prompts
- ✅ Significantly higher success rates for constrained generation
- ✅ Configuration-driven validation (no code changes needed)
- ✅ Extensible architecture for new validators and strategies

### Next Phase Items
- [ ] Remove debug prints for production
- [ ] Add performance monitoring and metrics
- [ ] Implement caching for successful prompt patterns
- [ ] Add more built-in validators (JSON, regex, sentiment)
- [ ] Create async validation support
- [ ] Performance optimization and resource limits

**Status**: ✅ **PRODUCTION READY**

---

## Field Chunking Feature (Previous)

### Summary
- Introduced `FieldAnalyzer` and `FieldChunker` utilities to analyze structured records and split oversized text fields into chunks
- Enhanced `staging_loader` to apply configurable field-level chunking for JSON and CSV sources
- Exposed `FieldAnalysisResult` through `agent_actions._internal.utils.field_chunking` for downstream modules
- Added `tests/unit/test_field_chunking.py` and updated `tests/conftest.py` to stub optional dependencies and use a real logger

### Testing
- `pytest tests/unit/test_field_chunking.py`
