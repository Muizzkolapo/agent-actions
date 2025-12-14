# Code Options Quiz Workflow

## Overview
Generates "Select the Best Code Implementation" quizzes where users compare 4 different code implementations and identify the optimal one.

## Quiz Format (from Image #1)
- **Question**: "Select the Best Code Implementation:"
- **Options**: A, B, C, D (each showing complete code blocks)
- **Answer Type**: Single correct answer (radio button selection)
- **Key Feature**: All options are functional, but only ONE is the BEST practice

## Workflow Steps

### 1. **code_extractor**
- Extracts code blocks from technical documentation
- Uses existing `$drop_down_quiz.Code_extraction` prompt
- Output: `candidate_code_list`

### 2. **flatten_code**
- Flattens extracted code for processing
- Tool: `drop_down_quiz.flatten_code.flatten_code`

### 3. **code_usage_scenario**
- Generates realistic scenario and context
- Uses existing `$drop_down_quiz.Scenario_generation` prompt
- Output: `sample_usage_scenario`, `code_for_scenario`, `scenario_complexity`, `key_considerations`

### 4. **generate_optimal_code**
- Creates the BEST implementation with industry best practices
- Output:
  - `optimal_code`: The complete best implementation
  - `optimization_areas`: Areas improved (performance, security, readability)
  - `best_practices_applied`: Specific practices used

### 5. **generate_code_alternatives** (Loop 3x)
- Generates 3 suboptimal but working alternatives
- Each alternative has intentional issues:
  - **Alternative 1**: Performance/Efficiency issues
  - **Alternative 2**: Security/Reliability issues
  - **Alternative 3**: Readability/Maintainability issues
- Output per iteration:
  - `alternative_code_N`: Complete working code with issues
  - `issue_type_N`: Category of issue
  - `issue_description_N`: Specific technical problem

### 6. **merge_alternatives**
- Merges loop outputs into single record
- Uses existing `qanalabs-quiz-gen.test2.apply_edited_distractors` tool

### 7. **explain_code_choices**
- Generates educational explanations for each option
- Output:
  - `why_optimal_is_best`: Why the best code is superior
  - `why_alternative_1_is_suboptimal`: What's wrong with alternative 1
  - `why_alternative_2_is_suboptimal`: What's wrong with alternative 2
  - `why_alternative_3_is_suboptimal`: What's wrong with alternative 3

### 8. **randomize_option_order**
- Shuffles code options into A, B, C, D positions
- Tracks which letter is the correct answer
- Tool: `code_options_quiz.randomize_options.shuffle_code_options` (NEW)

### 9. **transform_code_quiz_thinkific_compatible_structure**
- Transforms quiz into Thinkific-compatible JSON structure
- Applies IDE-style formatting with syntax highlighting to both question and option code blocks
- Tool: `code_options_quiz.clean_quiz_data.format_for_lms`

## Formatting & Styling

### Color Theme: Dark Teal & Amber

Complete gradient-based theme using Tailwind-inspired colors for a modern, cohesive look.

#### Background Gradients
- **Question outer container**: `linear-gradient(to bottom right, slate-900, teal-900)`
- **Scenario card**: `rgba(slate-800, 0.5)` - Semi-transparent slate
- **Code blocks (question)**: `rgba(slate-950, 0.6)` - Deep slate with transparency
- **Code blocks (options)**: `linear-gradient(135deg, slate-900 → slate-800 → teal-900)`
- **Instruction button**: `linear-gradient(to right, amber-500, orange-500)`

#### Syntax Highlighting
Custom regex-based highlighter (no Pygments dependency) with Dark Teal & Amber color scheme:

**Colors (Tailwind):**
- **Comments** `# text` → slate-400 grey (#94a3b8) - muted/greyed out
- **Commands** `dbt`, `run`, `test`, `build` → teal-300 (#5eead4)
- **Flags** `--select`, `--defer`, `--state` → teal-300 (#5eead4)
- **Variables** `modified_models`, `state_path` → teal-300 (#5eead4)
- **Paths** `path/to/prod/artifacts` → orange-300 (#fdba74)
- **Selectors** `state:modified+` → teal-300 + orange-300
- **Keywords** `all`, `modified`, `incremental` → teal-300 (#5eead4)
- **Default text** → slate-100 (#f1f5f9)

#### Visual Details
- Monospace fonts (Fira Code, JetBrains Mono, SF Mono)
- Teal accent borders on code blocks `rgba(20, 184, 166, 0.2)`
- Deeper shadows `0 4px 12px rgba(0, 0, 0, 0.4)`
- Uniform card heights (220px minimum) for clean grid layout

**Implementation:** `tools/code_options_quiz/clean_quiz_data.py::highlight_bash_code()`

### HTML Structure

**Question Code Blocks:**
```html
<div style="background: #1e1e1e; border-radius: 6px;">
  <div style="background: #2d2d2d;">Code Example</div>
  <pre><code>{syntax_highlighted_code}</code></pre>
</div>
```

**Option Code Blocks:**
```html
<div style="background: #1e1e1e; border-radius: 6px;">
  <div style="background: #2d2d2d;">bash</div>
  <pre><code>{syntax_highlighted_code}</code></pre>
</div>
```

### Important: HTML Option Handling

Options that already contain HTML (like pre-formatted code blocks) are **NOT wrapped** in additional styling templates to preserve their formatting. This is handled in `tools/qanalabs-quiz-gen/apply_html_text.py::format_options()`.

## Thinkific Compatibility

✅ **Works perfectly** because:
- Standard multiple choice (radio buttons)
- No JavaScript needed
- Uses `<pre>` and `<code>` tags for code display
- **Inline CSS styles** for syntax highlighting (not external stylesheets)
- Single correct answer format
- Syntax highlighting uses pure HTML `<span>` tags with inline styles
- No external dependencies (Pygments, Prism.js, etc.)

## Key Differences from Other Workflows

### vs. drop_down_quiz:
- ✅ Uses code extraction and scenario generation
- ❌ No blanking or dropdowns
- ✅ Shows complete code implementations

### vs. qanalabs-quiz-gen:
- ✅ Uses distractor generation pattern (loop + merge)
- ❌ No fact extraction
- ✅ Works directly with code

## Example Output Structure

**Final Thinkific-Compatible JSON:**
```json
{
  "quiz_id": "code_opt_001",
  "topic": "DBT Analytics Engineering",
  "difficulty_level": "intermediate",
  "question": "<html><body><div style='background: #0f172a; padding: 24px;'>...</div></body></html>",
  "options": [
    "<html><body><div style='background: #1e1e1e;'><div>bash</div><pre><code><span style='color: #4EC9B0;'>dbt</span> <span style='color: #4EC9B0;'>run</span>...</code></pre></div></body></html>",
    "<html><body><div style='background: #1e1e1e;'>...</div></body></html>",
    "<html><body><div style='background: #1e1e1e;'>...</div></body></html>",
    "<html><body><div style='background: #1e1e1e;'>...</div></body></html>"
  ],
  "answer": "A",
  "explanation": "<html><body>...</body></html>"
}
```

**Key Features:**
- Question contains scenario card + code block with syntax highlighting
- Each option is a complete HTML code block with syntax colors
- All styling is inline (no external CSS)
- Comments, commands, flags, paths all have distinct colors


```

# we keep this here
- name: explain_code_choices
intent: "Generate explanations for why optimal is best and why alternatives are suboptimal"
schema:
  why_optimal_is_best: string
  why_alternative_1_is_suboptimal: string
  why_alternative_2_is_suboptimal: string
  why_alternative_3_is_suboptimal: string
observe: [optimal_code, best_practices_applied, alternative_code_1, issue_type_1, issue_description_1, alternative_code_2, issue_type_2, issue_description_2, alternative_code_3, issue_type_3, issue_description_3, sample_usage_scenario]
prompt: $code_options_quiz.explain_code_choices
```



## Implementation Details

### Syntax Highlighting Function

Located in `tools/code_options_quiz/clean_quiz_data.py`:

```python
def highlight_bash_code(code: str) -> str:
    """
    Apply syntax highlighting to bash/dbt code using regex.

    Order matters:
    1. Comments FIRST (so they don't get mixed with other patterns)
    2. Commands (dbt, run, test, build)
    3. Flags (--select, --defer, --state)
    4. Paths (path/to/something)
    5. Selectors (state:modified+)
    6. Variables (modified_models)
    7. Keywords (all, modified)
    8. Operators (+, *)

    Returns HTML with inline <span> color styles
    """
```

### Key Technical Decisions

1. **No Pygments Dependency**: Uses regex-based highlighting to avoid external dependencies that Thinkific can't execute
2. **Inline Styles with Gradients**: All colors and gradients are inline CSS to survive Thinkific's HTML sanitization
3. **Gradient Backgrounds**: Uses CSS `linear-gradient()` for rich, modern appearance matching Tailwind aesthetic
4. **Comments First**: Comment regex runs before other patterns to prevent keyword highlighting inside comments
5. **Unified Color Palette**: Teal (#5eead4) for keywords, grey (#94a3b8) for comments, orange (#fdba74) for strings
6. **Consistent Card Heights**: Options use `min-height: 220px` with flexbox for uniform grid layout
7. **HTML Preservation**: Options with existing HTML skip the white wrapper template (`apply_html_text.py::format_options()`)

### Files Modified

- `tools/code_options_quiz/clean_quiz_data.py` - Added syntax highlighting to both question and option code blocks
- `tools/qanalabs-quiz-gen/apply_html_text.py` - Fixed HTML option wrapping to preserve dark theme

### Testing

Run workflow:
```bash
python -m agent_actions run code_options_quiz prompt_store/code_quiz/code_options_quiz.md
```

Verify output in:
```
agent_workflow/code_options_quiz/agent_io/target/node_9_transform_code_quiz_thinkific_compatible_structure/
```

## Known Limitations

- Currently optimized for bash/dbt commands with full syntax highlighting
- Python and SQL detection exists but uses basic escaping (no syntax highlighting yet)
- Long code lines may require horizontal scroll in Thinkific
- Syntax highlighting is regex-based (not AST-based), so edge cases may exist
- Gradients may render differently across browsers/LMS platforms
