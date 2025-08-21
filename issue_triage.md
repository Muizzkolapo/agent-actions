# GitHub Issue Triage - Agent Actions
Date: 2025-08-21

## Summary
- Total Open Issues: 29
- To Close: 10
- To Keep Open: 19

## Issues to CLOSE

### Documentation (1)
- #329 - Multi-Agent Architecture Guide (move to docs/wiki)

### Completed Tasks (7)
```bash
# Close completed tasks
gh issue close 201 --comment "Completed - closing as marked with ✅"
gh issue close 200 --comment "Completed - closing as marked with ✅"
gh issue close 196 --comment "Completed - closing as marked with ✅"
gh issue close 192 --comment "Completed - closing as marked with ✅"
gh issue close 191 --comment "Completed - closing as marked with ✅"
gh issue close 190 --comment "Completed - closing as marked with ✅"
gh issue close 177 --comment "Completed - closing as marked with ✅"
```

### Invalid/Vague (2)
```bash
gh issue close 294 --comment "Closing due to lack of description. Please create a new issue with details if still relevant."
gh issue close 236 --comment "Unclear issue. Please create a new issue with clear description if still relevant."
```

## Issues to KEEP OPEN (Priority Order)

### P0 - Critical Bugs (3)
1. **#297** - Data structure inconsistency between batch vs online mode
2. **#304** - Multiple JSON sources only output last file
3. **#308** - Warning with no context when using return collection

### P1 - Active Development (5)
4. **#293** - List of new features (roadmap)
5. **#173** - Standardize Schema Enforcement for LLM Vendors
6. **#171** - Vendor Handler Implementation & Consistency
7. **#172** - Implement ClaudeHandler Non-JSON Mode
8. **#216** - Better schema validation

### P2 - Technical Debt (4)
9. **#211** - Address TODO/FIXME Comments
10. **#203** - Refactor static-only classes to modules
11. **#176** - Address spaCy Dependency in Tokenizer
12. **#175** - Refine Exception Types in ConfigManager

### P3 - Return Collection Issues (5)
13. **#243** - Issue with return collection
14. **#242** - Return collection issue (possible duplicate of #243)
15. **#237** - Remove objects from context
16. **#214** - Template syntax issue with return_collection
17. **#152** - Remove collection optimization

### P4 - Lower Priority (2)
18. **#154** - Dependency key case sensitivity
19. **#139** - Each content with its own ID

## Recommended Actions

1. **Immediate**: Close the 10 identified issues to reduce noise
2. **This Sprint**: Focus on P0 bugs (#297, #304, #308)
3. **Next Sprint**: Address vendor consistency issues (P1)
4. **Backlog**: Consolidate return collection issues (possibly merge duplicates)

## Duplicate Candidates
- #243 and #242 appear to be duplicates (both "return collection issue")
- Consider merging or linking these issues