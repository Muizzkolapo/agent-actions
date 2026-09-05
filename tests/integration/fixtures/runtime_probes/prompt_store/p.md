# p - prompt store

{prompt Label_Page}
Label the page with a topic and a difficulty.
## TITLE
{{ source.title }}
## PAGE
{{ source.page_content }}
```json
{"topic": "...", "difficulty": "..."}
```
{end_prompt}

{prompt Summarize}
Summarise the page and rate how densely it carries exam-worthy material.
## PAGE
{{ source.page_content }}
```json
{"summary": "...", "exam_density": "high|medium|low", "density_reason": "..."}
```
{end_prompt}
