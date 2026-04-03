{prompt Extract_Incident_Details}
Extract structured information from the incident report for triage processing.

## INPUT DATA

**Incident Report**: {{ source.incident_report }}

**Monitoring Data** (if available): {{ source.monitoring_data }}

**Report Timestamp**: {{ source.timestamp }}

## TASK

Extract and structure key information needed for incident triage:

1. **Title**: Create a clear, concise incident title (max 100 chars)
2. **Description**: Summarize the incident in 2-3 sentences
3. **Affected Systems**: List all mentioned systems, services, or components
4. **Error Messages**: Extract any error messages, stack traces, or log entries
5. **Impact Signals**: Identify signals of impact (user reports, metrics, alerts)
6. **Reporter Priority**: The priority level indicated by the reporter (if any)

## OUTPUT FORMAT

```json
{
  "title": "Brief incident title",
  "description": "2-3 sentence summary of the incident",
  "affected_systems": ["system1", "system2"],
  "error_messages": ["error 1", "error 2"],
  "impact_signals": ["signal 1", "signal 2"],
  "reporter_priority": "HIGH | MEDIUM | LOW | UNKNOWN"
}
```

## EXAMPLES

**Good extraction:**
```json
{
  "title": "API Gateway returning 502 errors on /checkout endpoint",
  "description": "Users reporting failed checkout attempts. API Gateway logs show 502 errors from backend service. Started ~15 minutes ago.",
  "affected_systems": ["API Gateway", "checkout-service", "payment-processing"],
  "error_messages": ["502 Bad Gateway", "Connection timeout to checkout-service:8080"],
  "impact_signals": ["15 user reports", "Error rate spike to 45%", "Revenue drop detected"],
  "reporter_priority": "HIGH"
}
```

{end_prompt}

{prompt Classify_Severity}
You are classifier {{ i }} of {{ version.length }} in a severity classification ensemble.

{% if version.first %}
**Your role**: Be CONSERVATIVE. When in doubt, classify higher severity.
{% elif version.last %}
**Your role**: Be THOROUGH. Consider all possible impacts comprehensively.
{% else %}
**Your role**: Be BALANCED. Focus on evidence-based assessment.
{% endif %}

## INCIDENT DETAILS

**Title**: {{ extract_incident_details.title }}

**Description**: {{ extract_incident_details.description }}

**Affected Systems**: {{ extract_incident_details.affected_systems }}

**Error Messages**: {{ extract_incident_details.error_messages }}

**Impact Signals**: {{ extract_incident_details.impact_signals }}

**Full Report**: {{ source.incident_report }}

## SEVERITY LEVELS

**SEV1 (Critical)**: Complete service outage, massive customer impact, immediate revenue loss
- Examples: Payment processing down, app completely unavailable, data breach

**SEV2 (High)**: Major functionality impaired, significant customer impact
- Examples: Checkout broken, major feature unavailable, severe performance degradation

**SEV3 (Medium)**: Partial functionality impaired, moderate customer impact
- Examples: Non-critical feature broken, intermittent errors, elevated latency

**SEV4 (Low)**: Minor issue, limited customer impact
- Examples: UI glitch, non-blocking bug, isolated errors

**SEV5 (Informational)**: No customer impact, monitoring alert only
- Examples: Internal tool issue, false positive alert

## CLASSIFICATION CRITERIA

Consider:
1. **Customer Impact**: How many users are affected? Can they work around it?
2. **Business Impact**: Is revenue affected? Brand reputation at risk?
3. **Scope**: Is it isolated or widespread?
4. **Urgency**: Does it require immediate action?

## OUTPUT FORMAT

```json
{
  "severity": "SEV1 | SEV2 | SEV3 | SEV4 | SEV5",
  "confidence": 0.0-1.0,
  "reasoning": "Explain why you classified this severity, citing specific evidence from the incident details",
  "business_impact_estimate": "Brief estimate of business impact"
}
```

## IMPORTANT

- Base decision on evidence, not assumptions
- Consider worst-case realistic scenario
- Provide your independent assessment based on the evidence

{end_prompt}

{prompt Assess_Customer_Impact}
Assess the impact of this incident on customers and revenue.

## INCIDENT INFORMATION

**Incident**: {{ extract_incident_details.title }}

**Description**: {{ extract_incident_details.description }}

**Severity**: {{ aggregate_severity.final_severity }}

**Affected Systems**: {{ extract_incident_details.affected_systems }}

**Impact Signals**: {{ extract_incident_details.impact_signals }}

## ASSESSMENT CRITERIA

**Customer Impact Level**:
- **CRITICAL**: All or most customers cannot use core functionality
- **HIGH**: Significant portion of customers experiencing issues
- **MEDIUM**: Some customers experiencing issues, workarounds available
- **LOW**: Minimal customer impact, edge case scenarios
- **NONE**: No customer-facing impact

**Estimates**:
- Affected customer count (use ranges: <100, 100-1K, 1K-10K, 10K-100K, 100K+)
- Revenue impact (use ranges: <$1K, $1K-$10K, $10K-$100K, $100K-$1M, $1M+)
- Is this customer-facing?

## OUTPUT FORMAT

```json
{
  "customer_impact_level": "CRITICAL | HIGH | MEDIUM | LOW | NONE",
  "affected_customer_count_estimate": "Range estimate or specific number",
  "revenue_impact_estimate": "Range estimate or 'Unable to estimate'",
  "customer_facing": true or false
}
```

{end_prompt}

{prompt Assess_System_Impact}
Assess the technical system impact and blast radius.

## INCIDENT INFORMATION

**Incident**: {{ extract_incident_details.title }}

**Description**: {{ extract_incident_details.description }}

**Severity**: {{ aggregate_severity.final_severity }}

**Affected Systems**: {{ extract_incident_details.affected_systems }}

**Error Messages**: {{ extract_incident_details.error_messages }}

## ASSESSMENT CRITERIA

**System Impact Level**:
- **CRITICAL**: Core infrastructure failure, multiple dependent systems affected
- **HIGH**: Major service degradation, significant blast radius
- **MEDIUM**: Service partially degraded, contained blast radius
- **LOW**: Isolated component issue, minimal dependencies
- **MINIMAL**: Monitoring/logging only, no service impact

**Technical Analysis**:
- List all affected services/components
- Estimate degradation percentage (0-100%)
- Assess cascading failure risk (CRITICAL/HIGH/MEDIUM/LOW/NONE)

## OUTPUT FORMAT

```json
{
  "system_impact_level": "CRITICAL | HIGH | MEDIUM | LOW | MINIMAL",
  "affected_services": ["service1", "service2"],
  "degradation_percentage": "Percentage or range",
  "cascading_failure_risk": "CRITICAL | HIGH | MEDIUM | LOW | NONE"
}
```

{end_prompt}

{prompt Generate_Response_Plan}
Generate an initial incident response plan with actionable steps.

## INCIDENT CONTEXT

**Incident**: {{ extract_incident_details.title }}

**Description**: {{ extract_incident_details.description }}

**Severity**: {{ assign_response_team.final_severity }}

**Assigned Teams**: {{ assign_response_team.assigned_teams }}

**Customer Impact**: {{ assess_customer_impact.customer_impact_level }}

**Affected Systems**: {{ assign_response_team.affected_services }}

**Urgency**: {{ assign_response_team.urgency_level }}

**Response Message**: {{ assign_response_team.response_message }}

## RESPONSE PLAN STRUCTURE

**Immediate Actions** (0-5 minutes):
- Steps to contain/mitigate the incident RIGHT NOW
- Quick wins to reduce impact

**Investigation Steps**:
- Ordered steps to identify root cause
- Data to gather, logs to check, metrics to analyze

**Communication Plan**:
- Who needs to be notified? (internal teams, customers, stakeholders)
- What channels to use?
- What to communicate?

**Escalation Criteria**:
- When should this be escalated further?
- What conditions trigger escalation?

**Estimated Time to Engage (TTE)**:
- Realistic estimate for when responders can fully engage

## OUTPUT FORMAT

```json
{
  "immediate_actions": [
    "Action 1: Specific mitigation step",
    "Action 2: Quick containment measure"
  ],
  "investigation_steps": [
    "Step 1: Check specific logs/metrics",
    "Step 2: Review recent changes"
  ],
  "communication_plan": "Who to notify, when, and what to say",
  "escalation_criteria": [
    "Escalate if: condition 1",
    "Escalate if: condition 2"
  ],
  "estimated_tte": "5 minutes | 15 minutes | 30 minutes | 1 hour | etc."
}
```

## GUIDELINES

- Be specific and actionable
- Prioritize by impact reduction
- Include verification steps
- Consider rollback plans if recent deployments

{end_prompt}

{prompt Generate_Executive_Summary}
Generate an executive summary for leadership notification.

## INCIDENT OVERVIEW

**Severity**: {{ aggregate_severity.final_severity }}

**Customer Impact**: {{ assess_customer_impact.customer_impact_level }}

**Revenue Impact**: {{ assess_customer_impact.revenue_impact_estimate }}

**Immediate Actions**: {{ generate_response_plan.immediate_actions }}

**Communication Plan**: {{ generate_response_plan.communication_plan }}

## EXECUTIVE SUMMARY REQUIREMENTS

Write a clear, non-technical summary for executive leadership:

1. **Executive Summary** (3-4 sentences):
   - What happened?
   - What's the business impact?
   - What are we doing about it?
   - When will it be resolved?

2. **Business Impact Summary**:
   - Customer impact in business terms
   - Revenue/brand implications
   - Any regulatory/compliance concerns

3. **Response Status**:
   - Current response activities
   - Teams engaged
   - Next steps

4. **Key Stakeholders**:
   - Who should be informed/involved?

## TONE GUIDELINES

- Clear, concise, non-technical language
- Focus on business impact, not technical details
- Action-oriented and reassuring
- Transparent about unknowns

## OUTPUT FORMAT

```json
{
  "executive_summary": "3-4 sentence non-technical summary",
  "business_impact_summary": "Business impact in leadership terms",
  "response_status": "Current response activities and timeline",
  "key_stakeholders": ["stakeholder1", "stakeholder2"]
}
```

{end_prompt}
