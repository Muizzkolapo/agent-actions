---
title: Configuration Examples
description: Sample workflow configurations demonstrating Agent Actions features
sidebar_position: 1
---

# Configuration Examples

Production-ready workflow configurations that demonstrate advanced Agent Actions features and best practices.

## Educational Quiz Generation

**File**: [`qanalabs-quiz-gen-migrated.yml`](./qanalabs-quiz-gen-migrated.yml)

A sophisticated educational content processing workflow that generates quiz questions from source material.

### Workflow Overview

```
Source Content → Fact Extraction → Clustering → Validation → Quiz Generation
```

**Processing Pipeline:**
1. **fact_extractor** - Extract candidate facts from educational content
2. **cluster_list** - Group facts into logical clusters
3. **combine_by_cluster_and_id** - Merge records for processing
4. **validate_clusters** - Quality validation with flagging
5. **create_new_clusters** - Split clusters if validation fails
6. **explain_facts** - Generate detailed fact explanations
7. **classify_feynman** - Classify using Feynman technique principles
8. **generate_scenarios** - Create quiz scenarios from facts
9. **flatten_questions** - Restructure for answer generation
10. **suggest_distractor_counts** - Optimize distractor word counts
11. **add_answer_text** - Structure answer text
12. **generate_distractors** - Create wrong answers (using loops)
13. **reconstruct_options** - Finalize answer options

### Key Features Demonstrated

#### 🎯 **Additive Defaults Pattern**

The configuration showcases the new additive behavior for `drops` and `observe` fields:

```yaml
defaults:
  # Common fields applied to all actions
  observe: [id, url, platform_name, exam_name, page_content, bloom_details, fact, quote, fact_explanation, technical_level, questionable]
  drops: [rewrite_instruction, needs_rewrite, flagged_items, quiz_type, rationale]

actions:
  - name: explain_facts
    observe: [candidate_facts_list, why_questionable]  # only unique additions
    # Final result: defaults + unique = 13 total fields

  - name: classify_feynman
    drops: [id, url, page_content, bloom_details]  # overrides defaults
    observe: [summary, question, options, ...]       # only unique additions
```

**Benefits:**
- ✅ **DRY Configuration**: 84% reduction in field repetition
- ✅ **Maintainable**: Common changes in one place
- ✅ **Composable**: Actions specify only unique requirements

#### 🔄 **Loop Actions**

Demonstrates loop functionality for generating multiple distractors:

```yaml
- name: generate_distractors
  loop:
    param: stage
    range: [1, 3]
  schema:
    distractor_${stage}: string
    explanation_why_it_is_incorrect_${stage}: string
```

Generates `distractor_1`, `distractor_2`, `distractor_3` with explanations in a single action definition.

#### ⚙️ **Tool Workflows**

Shows integration of custom transformation tools:

```yaml
- name: cluster_list
  kind: tool
  impl: qanalabs-quiz-gen.final_clustering.cluster_list
  guard: 'candidate_facts_list != "[]"'
```

#### 🛡️ **Conditional Logic**

Quality gates and conditional processing:

```yaml
defaults:
  guard: 'questionable != "Low Value"'  # Skip low-quality content

actions:
  - name: create_new_clusters
    conditional_clause: "qanalabs-quiz-gen.combine_records_to_items.needs_split"
```

#### 📋 **Schema-Driven Validation**

Structured outputs with validation:

```yaml
- name: classify_feynman
  schema: {quiz_type: string, rationale: string}

- name: validate_clusters
  schema: cluster_validation  # References external schema
```

### Usage Instructions

1. **Prerequisites**: Ensure you have the required schema files and tool implementations
2. **Configuration**: Copy the file to your workflows directory
3. **Customization**: Modify prompts, schemas, and field lists for your domain
4. **Execution**: Run with your Agent Actions installation

### Educational Applications

This workflow pattern is ideal for:

- **E-learning platforms** generating practice questions
- **Training materials** with automated assessment
- **Educational content** quality validation
- **Quiz generation** from research papers or documentation

### Performance Characteristics

- **Parallel Processing**: Independent actions run simultaneously
- **Field Optimization**: Minimal LLM token usage via strategic field dropping
- **Quality Assurance**: Multi-stage validation prevents low-quality outputs
- **Scalability**: Handles large document collections efficiently

## More Examples Coming Soon

- **API Integration**: External service connections
- **Multi-Modal Processing**: Text, image, and data workflows
- **Real-Time Streaming**: Event-driven processing patterns
- **Enterprise Integrations**: Database and system connections