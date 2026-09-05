# p - prompt store

{prompt Summarize}
Summarise the page in one sentence and rate how densely it carries exam-worthy material.
## PAGE
{{ source.page_content }}
```json
{"summary": "...", "exam_density": "high|medium|low"}
```
{end_prompt}

{prompt Publish}
Restate this summary verbatim.
## SUMMARY
{{ summarize.summary }}
```json
{"summary": "...", "exam_density": "high|medium|low"}
```
{end_prompt}
