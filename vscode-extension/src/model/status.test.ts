import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, it } from 'node:test';

import {
    ACTION_STATUSES,
    formatWorkflowSummary,
    parseActionStatus,
    resolveActionStatus,
    rollupStatus,
    toActionStatus,
    workflowSortRank,
} from './status';
import type { AgentStatusData, ManifestData, StatusSummary } from './status';

describe('toActionStatus', () => {
    it('passes through every status the framework can write', () => {
        for (const status of ACTION_STATUSES) {
            assert.equal(toActionStatus(status), status);
        }
    });

    it('covers every member of the Python ActionStatus enum', () => {
        // The union and agent_actions/workflow/managers/state.py evolve
        // independently, with only the JSON on disk linking them. Read the enum
        // rather than restating it, so drift fails here instead of rendering a
        // real status as 'pending'.
        // npm test runs from vscode-extension/, so the framework sits one up.
        const enumSource = readFileSync(
            join('..', 'agent_actions', 'workflow', 'managers', 'state.py'),
            'utf8'
        );
        const body = enumSource.split('class ActionStatus(str, Enum):')[1].split('\n\n\n')[0];
        const written = [...body.matchAll(/^\s{4}[A-Z_]+ = "([a-z_]+)"$/gm)].map((m) => m[1]);

        assert.ok(written.length >= 9, `parsed too few enum members: ${written.length}`);
        for (const status of written) {
            assert.equal(toActionStatus(status), status, `${status} does not survive the union`);
        }
    });

    it('accepts the framework casing variants', () => {
        assert.equal(toActionStatus('RUNNING'), 'running');
        assert.equal(toActionStatus('Interrupted'), 'interrupted');
    });

    it('maps the legacy aliases', () => {
        assert.equal(toActionStatus('success'), 'completed');
        assert.equal(toActionStatus('error'), 'failed');
    });

    it('falls back to pending for absent or unknown values', () => {
        assert.equal(toActionStatus(undefined), 'pending');
        assert.equal(toActionStatus(''), 'pending');
        assert.equal(toActionStatus('nonsense'), 'pending');
    });

    it('distinguishes unknown from pending for callers that can fall back', () => {
        assert.equal(parseActionStatus('nonsense'), undefined);
        assert.equal(parseActionStatus('pending'), 'pending');
    });
});

describe('resolveActionStatus', () => {
    const manifest: ManifestData = {
        actions: {
            extract: { status: 'completed' },
            score: { status: 'running' },
        },
    };

    it('reads the object form of agent_status.json', () => {
        const agentStatus: AgentStatusData = { extract: { status: 'failed' } };
        assert.equal(resolveActionStatus(manifest, agentStatus, 'extract'), 'failed');
    });

    it('reads the bare-string form of agent_status.json', () => {
        const agentStatus: AgentStatusData = { extract: 'interrupted' };
        assert.equal(resolveActionStatus(manifest, agentStatus, 'extract'), 'interrupted');
    });

    it('prefers agent_status.json over the manifest', () => {
        const agentStatus: AgentStatusData = { score: { status: 'failed' } };
        assert.equal(resolveActionStatus(manifest, agentStatus, 'score'), 'failed');
    });

    it('falls back to the manifest when the action is absent from agent_status', () => {
        assert.equal(resolveActionStatus(manifest, { other: 'running' }, 'extract'), 'completed');
    });

    it('falls back to the manifest when agent_status is missing entirely', () => {
        assert.equal(resolveActionStatus(manifest, null, 'extract'), 'completed');
    });

    it('reports pending when neither source knows the action', () => {
        assert.equal(resolveActionStatus(manifest, null, 'unknown'), 'pending');
        assert.equal(resolveActionStatus(null, null, 'unknown'), 'pending');
    });

    it('ignores an agent_status entry with no usable status field', () => {
        const agentStatus = { extract: { execution_time: 1.2 } } as unknown as AgentStatusData;
        assert.equal(resolveActionStatus(manifest, agentStatus, 'extract'), 'completed');
    });
});

describe('resolveActionStatus with an unrecognised live value', () => {
    it('falls back to the manifest rather than claiming pending', () => {
        const manifest: ManifestData = { actions: { extract: { status: 'completed' } } };
        const agentStatus = { extract: 'from_the_future' } as AgentStatusData;
        assert.equal(resolveActionStatus(manifest, agentStatus, 'extract'), 'completed');
    });
});

describe('rollupStatus', () => {
    it('reports running when any action is live, whatever else happened', () => {
        assert.equal(rollupStatus(['completed', 'failed', 'running', 'pending']), 'running');
    });

    it('reports failed when nothing is live but something failed', () => {
        assert.equal(rollupStatus(['completed', 'failed', 'pending']), 'failed');
    });

    it('ranks a failure above an interruption', () => {
        assert.equal(rollupStatus(['interrupted', 'failed']), 'failed');
    });

    it('reports interrupted when that is the worst outcome', () => {
        assert.equal(rollupStatus(['completed', 'interrupted', 'pending']), 'interrupted');
    });

    it('reports completed only when every action reached a good end', () => {
        assert.equal(rollupStatus(['completed', 'completed']), 'completed');
        assert.equal(rollupStatus(['completed', 'skipped']), 'completed');
    });

    it('does not call a half-finished workflow completed', () => {
        assert.equal(rollupStatus(['completed', 'pending']), 'pending');
    });

    it('treats an empty workflow as pending, not completed', () => {
        assert.equal(rollupStatus([]), 'pending');
    });
});

describe('workflowSortRank', () => {
    it('puts live workflows above everything else', () => {
        const ranked = (['completed', 'pending', 'failed', 'running', 'interrupted'] as const)
            .slice()
            .sort((a, b) => workflowSortRank(a) - workflowSortRank(b));
        assert.deepEqual(ranked, ['running', 'failed', 'interrupted', 'pending', 'completed']);
    });

    it('gives skipped and completed the same lowest priority', () => {
        assert.equal(workflowSortRank('skipped'), workflowSortRank('completed'));
    });
});

describe('formatWorkflowSummary', () => {
    const base: StatusSummary = {
        total: 12,
        completed: 0,
        running: 0,
        failed: 0,
        pending: 0,
        skipped: 0,
        interrupted: 0,
    };

    it('names the live action when one is running', () => {
        const out = formatWorkflowSummary('running', { ...base, completed: 4 }, 'classify_genre');
        assert.equal(out, '4/12 · classify_genre');
    });

    it('reports the failure count when nothing is live', () => {
        assert.equal(formatWorkflowSummary('failed', { ...base, completed: 9, failed: 3 }), '9/12 · 3 failed');
    });

    it('reports interrupted when there are no failures', () => {
        assert.equal(
            formatWorkflowSummary('interrupted', { ...base, completed: 9, interrupted: 1 }),
            '9/12 · 1 interrupted'
        );
    });

    it('explains a short completed count with the skipped total', () => {
        // Without this a guard-skipped workflow reads as an unexplained 10/12.
        assert.equal(
            formatWorkflowSummary('completed', { ...base, completed: 10, skipped: 2 }),
            '10/12 · 2 skipped'
        );
    });

    it('says nothing extra when the count already tells the whole story', () => {
        assert.equal(formatWorkflowSummary('completed', { ...base, completed: 12 }), '12/12');
    });

    it('reports at most one detail, the most actionable', () => {
        const out = formatWorkflowSummary(
            'failed',
            { ...base, completed: 5, failed: 2, interrupted: 1, skipped: 3 },
            undefined
        );
        assert.equal(out, '5/12 · 2 failed');
    });
});
