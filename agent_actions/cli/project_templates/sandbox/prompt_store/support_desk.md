# support_desk prompts

{prompt Classify}
Classify this support ticket as billing, technical or account.
Give it a reference in the form REF-0000, and summarise it in one sentence.

Ticket {{ read_ticket.ticket_id }}:
{{ read_ticket.text }}
{end_prompt}

{prompt Score}
Rate how urgent this {{ classify.category }} ticket is, from 1 (can wait) to 5 (urgent).

{{ read_ticket.text }}
{end_prompt}

{prompt Draft_Reply}
Write a short, polite reply to ticket {{ ticket.ticket_id }}. Its urgency is {{ rating.urgency }} of 5.

{{ ticket.text }}
{% if prior %}
The last reply was checked and failed: {{ prior.reasons }}
Write a better one.
{% endif %}
{end_prompt}

{prompt Tag}
Give two to four help-centre tags for this {{ classify.category }} reply.

{{ reply_round.reply }}
{end_prompt}
