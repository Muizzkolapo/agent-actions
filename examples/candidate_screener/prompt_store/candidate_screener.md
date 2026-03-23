{prompt Parse_Resume}
Extract structured candidate information from the resume text and cover letter.

## INPUT DATA

**Resume**:
{{ source.resume_text }}

**Cover Letter**:
{{ source.cover_letter }}

## TASK

Parse the candidate's materials and extract structured data for downstream assessment. Be thorough and precise — downstream assessors depend on the quality of this extraction.

1. **Skills**: Extract all technical and professional skills mentioned. Estimate proficiency level based on context (years used, depth of projects, leadership in that area). Categories:
   - `expert`: 5+ years, deep contributions, teaches others
   - `advanced`: 3-5 years, significant production use
   - `intermediate`: 1-3 years, working knowledge
   - `beginner`: mentioned but limited evidence of depth

2. **Previous Roles**: Extract each position with company, approximate duration, and key responsibilities. Focus on responsibilities that demonstrate technical depth, leadership, or impact.

3. **Experience Years**: Calculate total years of professional experience. Count from first full-time role (exclude internships under 6 months from the total, but include them in the roles list).

4. **Education**: Extract all degrees, fields of study, and institutions.

5. **Notable Achievements**: Pull out quantifiable results (revenue impact, scale metrics, performance improvements), publications, patents, awards, and open-source contributions.

6. **Communication Style**: Assess writing quality from both resume and cover letter. Consider: clarity, conciseness, professionalism, and ability to articulate impact.

## OUTPUT FORMAT

```json
{
  "candidate_name": "Full Name",
  "role_applied": "role_key",
  "skills": [
    {"name": "Python", "proficiency": "expert", "years": 5}
  ],
  "previous_roles": [
    {
      "title": "Senior Engineer",
      "company": "Acme Corp",
      "duration_years": 3,
      "key_responsibilities": ["Led team of 5", "Built distributed system"]
    }
  ],
  "experience_years": 7,
  "education": [
    {"degree": "M.S.", "field": "Computer Science", "institution": "Stanford"}
  ],
  "notable_achievements": ["Reduced latency by 40%", "Published at SOSP"],
  "communication_style": "Clear and impact-oriented, effectively quantifies achievements"
}
```

## GUIDELINES

- Use the normalized role key from the application (e.g., `senior_software_engineer`, not "Senior Software Engineer")
- When duration is ambiguous, estimate conservatively
- For skills, only list what is supported by evidence in the resume
- Notable achievements must be specific and verifiable, not generic claims

{end_prompt}

{prompt Assess_Skills}
Evaluate the candidate's technical skill match against the role requirements.

## ROLE REQUIREMENTS

**Role**: {{ parse_resume.role_applied }}

**Must-Have Skills**:
{{ seed_data.role_requirements.roles[parse_resume.role_applied].must_have }}

**Nice-to-Have Skills**:
{{ seed_data.role_requirements.roles[parse_resume.role_applied].nice_to_have }}

## CANDIDATE SKILLS

{{ parse_resume.skills }}

## CANDIDATE WORK HISTORY

{{ parse_resume.previous_roles }}

## TASK

Assess how well the candidate's skills match the role requirements. You are evaluating ONLY technical skill match — do not assess experience depth or culture fit.

### Evaluation Criteria

1. **Must-Have Coverage**: For each must-have requirement, determine if the candidate meets it. Provide specific evidence from their skills and work history.

2. **Nice-to-Have Coverage**: For each nice-to-have, determine if the candidate meets it.

3. **Skill Gaps**: Identify critical gaps that would require significant ramp-up time.

4. **Skill Strengths**: Note any exceptional skills beyond the requirements that add value.

### Scoring Guide (1-10)

- **9-10**: Exceeds all must-haves, strong on nice-to-haves, exceptional additional skills
- **7-8**: Meets all must-haves, some nice-to-haves, solid additional skills
- **5-6**: Meets most must-haves, gaps are addressable with reasonable ramp-up
- **3-4**: Missing multiple must-haves, significant ramp-up needed
- **1-2**: Major skill mismatch, most must-haves unmet

## OUTPUT FORMAT

```json
{
  "skills_score": 7,
  "must_have_coverage": [
    {"requirement": "Python or Java", "met": true, "evidence": "5 years Python at Stripe"}
  ],
  "nice_to_have_coverage": [
    {"requirement": "Cloud platforms", "met": true, "evidence": "AWS experience at Dropbox"}
  ],
  "skill_gaps": ["No Kubernetes experience mentioned"],
  "skill_strengths": ["Strong distributed systems background beyond requirements"],
  "skills_reasoning": "Candidate meets all must-haves with strong evidence..."
}
```

## IMPORTANT

- Score based on evidence, not assumptions
- A skill mentioned without context of use should be rated lower than one demonstrated in projects
- Consider recency of skill use — skills from 5+ years ago without recent use may be rusty
- Do NOT factor in years of experience or seniority — that is assessed separately

{end_prompt}

{prompt Assess_Experience}
Evaluate the depth and relevance of the candidate's professional experience.

## ROLE REQUIREMENTS

**Role**: {{ parse_resume.role_applied }}

**Required Level**: {{ seed_data.role_requirements.roles[parse_resume.role_applied].level }}

**Role Description**: {{ seed_data.role_requirements.roles[parse_resume.role_applied].description }}

**Team Size**: {{ seed_data.role_requirements.roles[parse_resume.role_applied].team_size }}

## CANDIDATE EXPERIENCE

**Total Years**: {{ parse_resume.experience_years }}

**Work History**:
{{ parse_resume.previous_roles }}

**Notable Achievements**:
{{ parse_resume.notable_achievements }}

**Education**:
{{ parse_resume.education }}

**Role Applied For**: {{ parse_resume.role_applied }}

## TASK

Assess the depth, relevance, and trajectory of the candidate's professional experience. You are evaluating ONLY experience — do not assess specific skill proficiency or culture fit.

### Evaluation Criteria

1. **Years Relevant**: How many years of experience are directly relevant to the target role (not total years)?

2. **Seniority Match**: Does the candidate's demonstrated level match the role?
   - `under-leveled`: Would need to grow significantly into the role
   - `appropriate`: Good match for the role level
   - `over-leveled`: May find the role insufficiently challenging

3. **Role Progression**: What does the career trajectory look like?
   - `stagnant`: Same level/scope for extended period
   - `steady`: Normal progression over time
   - `accelerating`: Faster-than-average growth in responsibility
   - `exceptional`: Rapid growth with increasing scope and impact

4. **Domain Relevance**: How relevant is their industry/problem-domain experience?

5. **Leadership Evidence**: Concrete examples of leading teams, mentoring, or driving cross-team initiatives.

6. **Impact Evidence**: Quantifiable results from previous roles.

### Scoring Guide (1-10)

- **9-10**: Exceptional trajectory, highly relevant experience, demonstrated leadership and impact
- **7-8**: Strong relevant experience, good progression, clear impact examples
- **5-6**: Adequate experience, some relevant work, limited leadership signals
- **3-4**: Limited relevant experience, unclear trajectory
- **1-2**: Insufficient experience for the role level

## OUTPUT FORMAT

```json
{
  "experience_score": 8,
  "years_relevant": 5,
  "seniority_match": "appropriate",
  "role_progression": "accelerating",
  "domain_relevance": "high",
  "leadership_evidence": ["Led team of 5 engineers", "Mentored 3 junior engineers"],
  "impact_evidence": ["Reduced API latency by 40%", "99.99% uptime"],
  "experience_reasoning": "Candidate shows strong, relevant experience..."
}
```

## IMPORTANT

- Relevant experience means directly applicable to the target role, not just any professional experience
- Quality of companies matters as a signal but is not decisive
- Education supplements but does not replace professional experience
- Do NOT assess specific technical skill proficiency — that is assessed separately

{end_prompt}

{prompt Assess_Culture_Fit}
Evaluate the candidate's alignment with company values and team culture.

## COMPANY VALUES

{{ seed_data.company_values.values }}

**Company**: {{ seed_data.company_values.company_name }}

## CANDIDATE SIGNALS

**Notable Achievements**:
{{ parse_resume.notable_achievements }}

**Communication Style**:
{{ parse_resume.communication_style }}

**Cover Letter**:
{{ source.cover_letter }}

## TASK

Assess how well the candidate aligns with the company's values and culture. You are evaluating ONLY culture fit — do not assess technical skills or experience depth.

### Evaluation Criteria

1. **Values Alignment**: For each company value, assess alignment based on evidence from the cover letter, achievements, and communication style.
   - `strong`: Clear, concrete evidence of alignment
   - `moderate`: Some signals but not definitive
   - `weak`: Signals that may conflict with the value
   - `no-signal`: Insufficient information to assess

2. **Communication Quality**: Based on cover letter and resume writing:
   - `excellent`: Clear, compelling, well-structured, shows genuine interest
   - `good`: Professional, clear, appropriate for the role
   - `adequate`: Acceptable but unremarkable
   - `poor`: Unclear, generic, or poorly written

3. **Motivation Signals**: What drives this candidate? Do their stated motivations align with what the role and company offer?

4. **Culture Risks**: Flag any potential concerns — e.g., may prefer different work style, misaligned career goals, or compensation expectations mismatch.

### Scoring Guide (1-10)

- **9-10**: Strong alignment across most values, excellent communication, compelling motivation
- **7-8**: Good alignment, clear motivation, minor concerns
- **5-6**: Mixed signals, some alignment but notable gaps
- **3-4**: Weak alignment, generic motivation, potential concerns
- **1-2**: Misaligned values or significant culture risks

## OUTPUT FORMAT

```json
{
  "culture_score": 7,
  "values_alignment": [
    {
      "value": "Ownership Mindset",
      "alignment": "strong",
      "evidence": "Proactively identified and led migration project"
    }
  ],
  "communication_quality": "good",
  "motivation_signals": ["Seeking broader architectural impact", "Values collaborative culture"],
  "culture_risks": ["May expect faster promotion cycle than we offer"],
  "culture_reasoning": "Candidate shows strong alignment with ownership and curiosity values..."
}
```

## IMPORTANT

- Base assessments on observable evidence, not assumptions about personality
- Cover letters are a strong signal for communication and motivation but may be coached
- Achievements reveal values in action better than stated values
- Be cautious about inferring culture fit from demographic or background signals
- A "no-signal" rating is better than guessing when evidence is insufficient

{end_prompt}

{prompt Generate_Recommendation}
Generate a final hire/no-hire recommendation with actionable details for the hiring team.

## CANDIDATE OVERVIEW

**Candidate**: {{ combine_scores.candidate_name }}

**Role**: {{ combine_scores.role_applied }}

## ASSESSMENT SCORES

**Composite Score**: {{ combine_scores.composite_score }} / 10

**Score Breakdown**:
- Skills: {{ combine_scores.skills_score }} (weighted: {{ combine_scores.score_breakdown.skills_weighted }})
- Experience: {{ combine_scores.experience_score }} (weighted: {{ combine_scores.score_breakdown.experience_weighted }})
- Culture Fit: {{ combine_scores.culture_score }} (weighted: {{ combine_scores.score_breakdown.culture_weighted }})

**Recommendation Tier**: {{ combine_scores.recommendation_tier }}

**Skills Assessment**:
- Gaps: {{ combine_scores.skill_gaps }}
- Strengths: {{ combine_scores.skill_strengths }}
- Reasoning: {{ combine_scores.skills_reasoning }}

**Experience Assessment**:
- Seniority Match: {{ combine_scores.seniority_match }}
- Role Progression: {{ combine_scores.role_progression }}
- Reasoning: {{ combine_scores.experience_reasoning }}

**Culture Fit Assessment**:
- Communication Quality: {{ combine_scores.communication_quality }}
- Culture Risks: {{ combine_scores.culture_risks }}
- Reasoning: {{ combine_scores.culture_reasoning }}

## TASK

Generate a comprehensive recommendation that helps the hiring team make a decision and prepare for next steps.

### Decision Criteria

- **STRONG_HIRE** (composite >= 8): Exceptional candidate, prioritize scheduling
- **HIRE** (composite >= 6): Good candidate, proceed to interview
- **NO_HIRE** (composite < 6): Does not meet the bar (should be filtered by guard)

### Required Output

1. **Decision**: STRONG_HIRE, HIRE, or NO_HIRE
2. **Confidence**: How confident are you in this recommendation? (0.0-1.0)
3. **Summary**: 2-3 sentence executive summary a hiring manager can scan
4. **Strengths**: Top 3-5 strengths most relevant to the role
5. **Concerns**: Honest concerns to probe during interviews
6. **Interview Focus Areas**: Specific topics to explore in depth during interviews
7. **Compensation Guidance**: Brief note on level and expectations
8. **Next Steps**: Concrete recommendation on process

## OUTPUT FORMAT

```json
{
  "decision": "HIRE",
  "confidence": 0.85,
  "summary": "Strong backend engineer with relevant distributed systems experience...",
  "strengths": ["Deep Python expertise", "Production-scale system design"],
  "concerns": ["Limited leadership experience for senior role"],
  "interview_focus_areas": ["System design depth", "Team leadership scenarios"],
  "compensation_guidance": "Mid-band for senior level based on experience",
  "next_steps": "Proceed to technical phone screen, then onsite"
}
```

## GUIDELINES

- Be direct and actionable — hiring managers are busy
- Strengths and concerns should be specific, not generic
- Interview focus areas should help interviewers probe the concerns
- Compensation guidance should reflect the candidate's market position
- Next steps should be tailored to the candidate's strength level

{end_prompt}
