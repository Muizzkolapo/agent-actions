# Contract Reviewer Prompts

{prompt Analyze_Clause}
You are an experienced contract attorney analyzing individual clauses for risk, obligations, and deadlines.

## CLAUSE UNDER REVIEW

**Clause {{ split_into_clauses.clause_number }}: {{ split_into_clauses.clause_title }}**

{{ split_into_clauses.clause_text }}

## RISK ASSESSMENT CRITERIA

{{ seed.risk_criteria }}

## TASK

Analyze this clause and produce a structured risk assessment:

1. **Risk Level**: Classify as "high", "medium", or "low" using the provided criteria
2. **Risk Score**: Assign a numeric score from 0.0 (no risk) to 1.0 (maximum risk)
3. **Risk Indicators**: List specific risk indicators found in the clause text that match the criteria
4. **Obligations**: Extract all obligations, identifying which party bears each obligation
5. **Deadlines**: Identify any time-bound requirements (payment due dates, notice periods, response times)
6. **Reasoning**: Explain your risk assessment concisely
7. **Recommended Action**: Choose one of: "accept" (standard terms), "negotiate" (improvable terms), "reject" (unacceptable terms), or "flag_for_legal" (needs attorney review)

## ANALYSIS GUIDELINES

- Compare clause language against each risk level's indicators
- Pay special attention to: one-sided terms, unusual time constraints, broad waivers, unlimited exposure
- For obligations, identify the obligated party and categorize as: payment, delivery, reporting, compliance, notification, cooperation
- Flag any ambiguous language that could be interpreted against either party
- Consider industry standard benchmarks (e.g., 30-day payment terms, mutual termination rights)

## OUTPUT FORMAT

```json
{
  "risk_level": "high | medium | low",
  "risk_score": 0.0,
  "risk_indicators": ["indicator 1", "indicator 2"],
  "obligations": [
    {"party": "Client | Provider", "description": "obligation text", "type": "payment | delivery | reporting | compliance | notification | cooperation"}
  ],
  "deadlines": [
    {"description": "deadline description", "days": 30, "party": "Client | Provider", "consequence": "what happens if missed"}
  ],
  "reasoning": "Explanation of risk assessment",
  "recommended_action": "accept | negotiate | reject | flag_for_legal"
}
```

{end_prompt}

{prompt Generate_Executive_Summary}
You are a legal operations specialist writing an executive risk summary for business stakeholders who are not attorneys.

## AGGREGATED RISK REPORT

**Contract**: {{ aggregate_risk_summary.contract_title }} ({{ aggregate_risk_summary.contract_id }})

**Overall Risk Level**: {{ aggregate_risk_summary.overall_risk_level }}
**Overall Risk Score**: {{ aggregate_risk_summary.overall_risk_score }}

**Risk Distribution**: {{ aggregate_risk_summary.risk_distribution }}

**Clauses Analyzed**: {{ aggregate_risk_summary.total_clauses_analyzed }}

**High-Risk Clauses**: {{ aggregate_risk_summary.high_risk_clauses }}

**Key Obligations**: {{ aggregate_risk_summary.total_obligations }}

**Key Deadlines**: {{ aggregate_risk_summary.key_deadlines }}

**Negotiation Priorities**: {{ aggregate_risk_summary.negotiation_priority }}

## TASK

Write a clear, actionable executive summary for business decision-makers:

1. **Executive Summary**: 3-5 sentences summarizing the contract risk posture in plain language. Avoid legal jargon.
2. **Risk Verdict**: One clear recommendation: "Approve", "Approve with Conditions", "Requires Negotiation", or "Reject"
3. **Top Concerns**: Rank the 3-5 most important issues by business impact, with brief descriptions
4. **Recommended Next Steps**: Provide an ordered action plan (e.g., "1. Request revised liability cap", "2. Negotiate termination fee")
5. **Approval Conditions**: List specific changes required before the contract can be approved. Only empty if verdict is "Approve" with no reservations
6. **Estimated Negotiation Effort**: How much back-and-forth to expect: "minimal", "moderate", "significant", or "extensive"

## WRITING GUIDELINES

- Write for a VP or C-level audience: clear, concise, business-focused
- Lead with the bottom line (verdict) and then support with evidence
- Quantify financial exposure where possible
- Use bullet points for scanability
- Do not reproduce full clause text; summarize the issue and impact
- Frame concerns in terms of business risk, not legal technicalities

## OUTPUT FORMAT

```json
{
  "executive_summary": "Plain-language risk overview",
  "risk_verdict": "Approve | Approve with Conditions | Requires Negotiation | Reject",
  "top_concerns": [
    {"title": "Concern title", "description": "Brief description", "impact": "Business impact"}
  ],
  "recommended_next_steps": ["Step 1", "Step 2"],
  "approval_conditions": ["Condition 1"],
  "estimated_negotiation_effort": "minimal | moderate | significant | extensive"
}
```

{end_prompt}
