# Question rounds

{prompt Write}
Write one exam question about: {{ spec.topic }}
{% if prior %}
Your last question was checked and failed: {{ prior.reasons }}
Write a better one.
{% endif %}
{end_prompt}
