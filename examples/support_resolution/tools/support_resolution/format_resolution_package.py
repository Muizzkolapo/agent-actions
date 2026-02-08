"""
Format all resolution outputs into a final package.
"""
from typing import Dict, Any, List
from datetime import datetime
from agent_actions import udf_tool


@udf_tool()
def format_resolution_package(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Package all outputs into final resolution bundle.

    Combines:
    - Customer response
    - Internal task
    - PR draft (if applicable)

    Returns a complete resolution package ready for action.
    """
    content = data.get('content', data)

    # Extract components
    analysis = {
        'issue_type': content.get('issue_type', content.get('analyze_issue', {}).get('issue_type')),
        'severity': content.get('severity', content.get('analyze_issue', {}).get('severity')),
        'summary': content.get('summary', content.get('analyze_issue', {}).get('summary')),
        'affected_area': content.get('affected_area', content.get('analyze_issue', {}).get('affected_area'))
    }

    response = content.get('generate_response', {})
    task = content.get('generate_task', {})
    pr = content.get('draft_pr', {})
    resolution = content.get('determine_resolution', {})

    # Determine what outputs we have
    has_response = bool(response.get('full_response'))
    has_task = bool(task.get('title'))
    has_pr = bool(pr.get('pr_title'))

    # Build resolution package
    package = {
        'resolution_id': f"RES-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
        'generated_at': datetime.utcnow().isoformat() + "Z",
        'status': 'ready_for_review',

        # Issue summary
        'issue': {
            'type': analysis['issue_type'],
            'severity': analysis['severity'],
            'summary': analysis['summary'],
            'affected_area': analysis['affected_area']
        },

        # Resolution decision
        'resolution': {
            'type': resolution.get('resolution_type', 'unknown'),
            'priority': resolution.get('priority', 'p2'),
            'complexity': resolution.get('complexity', 'medium'),
            'assigned_team': resolution.get('assigned_team', 'support'),
            'estimated_effort': resolution.get('estimated_effort', 'unknown'),
            'requires_code_change': resolution.get('requires_code_change', False)
        },

        # Outputs
        'outputs': {
            'customer_response': {
                'available': has_response,
                'subject': response.get('subject', ''),
                'body': response.get('full_response', ''),
                'tone': response.get('tone', 'professional')
            } if has_response else None,

            'internal_task': {
                'available': has_task,
                'title': task.get('title', ''),
                'description': task.get('description', ''),
                'priority': task.get('priority', ''),
                'labels': task.get('labels', []),
                'acceptance_criteria': task.get('acceptance_criteria', []),
                'assigned_team': task.get('assigned_team', '')
            } if has_task else None,

            'pr_draft': {
                'available': has_pr,
                'title': pr.get('pr_title', ''),
                'type': pr.get('pr_type', ''),
                'body': pr.get('full_pr_body', ''),
                'files_to_modify': pr.get('files_to_modify', []),
                'breaking_changes': pr.get('breaking_changes', False)
            } if has_pr else None
        },

        # Summary for quick review
        'quick_summary': {
            'outputs_generated': [
                'customer_response' if has_response else None,
                'internal_task' if has_task else None,
                'pr_draft' if has_pr else None
            ],
            'next_actions': _determine_next_actions(has_response, has_task, has_pr, resolution)
        },

        # Metadata
        'metadata': {
            'workflow_version': '1.0.0',
            'pipeline': 'support_resolution',
            'processing_complete': True
        }
    }

    # Clean up None values from outputs
    package['quick_summary']['outputs_generated'] = [
        o for o in package['quick_summary']['outputs_generated'] if o
    ]

    return [package]


def _determine_next_actions(has_response: bool, has_task: bool, has_pr: bool, resolution: dict) -> List[str]:
    """Determine recommended next actions."""
    actions = []

    if has_response:
        actions.append("Review and send customer response")

    if has_task:
        actions.append(f"Create ticket in project board (Priority: {resolution.get('priority', 'p2')})")

    if has_pr:
        actions.append("Review PR draft and create actual PR")

    if resolution.get('requires_code_change') and not has_pr:
        actions.append("Code change needed but PR not drafted - manual intervention required")

    if not actions:
        actions.append("Review resolution and determine next steps")

    return actions
