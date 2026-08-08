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

    it('never looks for the manifest directly under agent_io', () => {
        // The bug this replaces: a single hardcoded path that no longer exists.
        const stray = path.join(AGENT_IO, '.manifest.json');
        assert.ok(!manifestCandidatePaths(AGENT_IO).includes(stray));
    });
});

describe('agentStatusPath', () => {
    it('resolves directly under agent_io', () => {
        assert.equal(agentStatusPath(AGENT_IO), path.join(AGENT_IO, '.agent_status.json'));
    });
});

describe('watch globs', () => {
    it('covers both manifest locations so the fallback still refreshes', () => {
        assert.match(MANIFEST_GLOB, /logs/);
        assert.match(MANIFEST_GLOB, /target/);
    });

    it('watches the status file where the framework writes it', () => {
        assert.equal(AGENT_STATUS_GLOB, '**/agent_io/.agent_status.json');
    });
});
