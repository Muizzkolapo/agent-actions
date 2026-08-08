import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import { resolveActionStatus, toActionStatus } from './status';
import type { AgentStatusData, ManifestData } from './status';

describe('toActionStatus', () => {
    it('passes through every status the framework can write', () => {
        for (const status of [
            'pending',
            'running',
            'completed',
            'failed',
            'skipped',
            'interrupted',
        ]) {
            assert.equal(toActionStatus(status), status);
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

    it('does not report a status the framework emits as never-started', () => {
        // Guards the whole class of bug: a value missing from the union reads
        // as 'pending', which claims the action never ran.
        assert.notEqual(toActionStatus('interrupted'), 'pending');
        assert.notEqual(toActionStatus('skipped'), 'pending');
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
