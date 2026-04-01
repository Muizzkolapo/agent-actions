# Support Resolution Prompts — Field-by-Field Construction
#
# Each prompt asks for ONE answer. No JSON formatting required.
# Works with any model that can follow a simple instruction.

{prompt Classify_Issue}
You are a support ticket classifier.

**Ticket Title**: {{ source.title }}

**Ticket Body**: {{ source.body }}

**Labels**: {{ source.labels }}

Classify this ticket into exactly ONE of these categories:
- bug
- feature_request
- question
- account_issue
- performance

Answer with the category name only. Nothing else.
{end_prompt}

{prompt Assess_Severity}
You are assessing the severity of a support ticket.

**Title**: {{ source.title }}

**Description**: {{ source.body }}

**Issue Type**: {{ classify_issue.issue_type }}

Rate the severity as exactly ONE of:
- critical (production down, data loss, security breach)
- high (major feature broken, blocking multiple users)
- medium (feature degraded, workaround exists)
- low (cosmetic, minor inconvenience, nice-to-have)

Answer with the severity level only. Nothing else.
{end_prompt}

{prompt Identify_Area}
You are identifying which product area a support ticket belongs to.

**Title**: {{ source.title }}

**Description**: {{ source.body }}

**Issue Type**: {{ classify_issue.issue_type }}

Which product area is affected? Answer with ONE of:
- authentication
- api
- billing
- reports
- integrations
- ui
- infrastructure
- documentation

Answer with the area name only. Nothing else.
{end_prompt}

{prompt Assign_Team}
You are routing a support ticket to the right team.

**Issue Type**: {{ classify_issue.issue_type }}
**Severity**: {{ assess_severity.severity }}
**Product Area**: {{ identify_area.product_area }}

**Routing Rules**: {{ seed_data.routing_rules }}

Based on the routing rules, which team should handle this? Answer with the team name only. Nothing else.
{end_prompt}

{prompt Summarize_Issue}
You are writing a one-line summary for a triage dashboard.

**Title**: {{ source.title }}
**Issue Type**: {{ classify_issue.issue_type }}
**Severity**: {{ assess_severity.severity }}
**Area**: {{ identify_area.product_area }}
**Description**: {{ source.body }}

Write a single sentence (max 20 words) summarizing the issue for a triage dashboard.
Do not include severity or category — those are already shown separately.
Just describe what is broken or requested.
{end_prompt}

{prompt Draft_Response}
You are a support specialist drafting a brief customer response.

**Ticket**: {{ source.title }}
**Issue Type**: {{ classify_issue.issue_type }}
**Severity**: {{ assess_severity.severity }}
**Summary**: {{ summarize_issue.summary }}
**Assigned Team**: {{ assign_team.assigned_team }}

Write a short, empathetic customer response (3-5 sentences) that:
1. Acknowledges the issue
2. Confirms it has been triaged and assigned
3. Sets expectation on next steps

Keep it professional but human. Do not use placeholder names.
{end_prompt}
