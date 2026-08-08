import assert from 'node:assert/strict';
import * as path from 'node:path';
import { describe, it } from 'node:test';

import {
    AGENT_STATUS_GLOB,
    MANIFEST_GLOB,
    agentStatusPath,
    manifestCandidatePaths,
} from './paths';

const AGENT_IO = path.join('proj', 'agent_workflow', 'wf', 'agent_io');

describe('manifestCandidatePaths', () => {
    it('looks in logs/ first, where the framework writes', () => {
        assert.equal(
            manifestCandidatePaths(AGENT_IO)[0],
            path.join(AGENT_IO, 'logs', '.manifest.json')
        );
    });

    it('keeps target/ as a fallback for projects last run before the move', () => {
        assert.equal(
            manifestCandidatePaths(AGENT_IO)[1],
            path.join(AGENT_IO, 'target', '.manifest.json')
        );
    });

    it('offers exactly the two known locations', () => {
        assert.equal(manifestCandidatePaths(AGENT_IO).length, 2);
    });

    it('puts the framework-written location ahead of the legacy one', () => {
        // Order is the whole point: reversing it would serve a pre-migration
        // manifest in preference to the current run's.
        const dirs = manifestCandidatePaths(AGENT_IO).map((p) => path.basename(path.dirname(p)));
        assert.deepEqual(dirs, ['logs', 'target']);
    });
});

describe('agentStatusPath', () => {
    it('resolves directly under agent_io', () => {
        assert.equal(agentStatusPath(AGENT_IO), path.join(AGENT_IO, '.agent_status.json'));
    });
});

describe('watch globs', () => {
    it('covers every location the reader will look in', () => {
        // Substring checks would pass for a glob that watches nothing, so
        // derive the expectation from the candidate list itself.
        const dirs = manifestCandidatePaths(AGENT_IO).map((p) => path.basename(path.dirname(p)));
        assert.deepEqual(dirs.sort(), ['logs', 'target']);
        assert.equal(MANIFEST_GLOB, '**/agent_io/{logs,target}/.manifest.json');
    });

    it('watches the status file where the framework writes it', () => {
        assert.equal(AGENT_STATUS_GLOB, '**/agent_io/.agent_status.json');
    });
});
