---
name: Tracing Integration Reminder
about: Ensure span/trace instrumentation is included when optimizing artifacts
title: "🔍 Add Tracing: [Feature/Component Name]"
labels: tracing, optimization, telemetry
assignees: ''
---

## Context
When working on optimization artifacts, we must ensure proper span and trace instrumentation.

## Checklist
- [ ] Spans created for key operations
- [ ] Relevant attributes added to spans  
- [ ] Artifacts attached to spans
- [ ] Trace correlation maintained across operations
- [ ] Integration tested with existing telemetry

## Reference
See `/TRACING_REQUIREMENTS.md` for detailed requirements.

## Components That Need Tracing
- [ ] Interceptors (validation, reprompt)
- [ ] Strategy execution 
- [ ] Template variable resolution
- [ ] Context data passing
- [ ] Error handling flows

## Artifacts to Capture
- [ ] Prompt evolution (original → improved)
- [ ] Validation results and context
- [ ] Strategy decisions and reasoning
- [ ] Performance metrics
- [ ] Configuration used

## Testing
- [ ] Spans appear in trace viewer
- [ ] Attributes are populated correctly  
- [ ] Artifacts are queryable
- [ ] No performance degradation
- [ ] Nested span relationships correct