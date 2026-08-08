import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, it } from 'node:test';

import { ACTION_STATUSES, parseActionStatus, resolveActionStatus, toActionStatus } from './status';
import type { AgentStatusData, ManifestData } from './status';

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
