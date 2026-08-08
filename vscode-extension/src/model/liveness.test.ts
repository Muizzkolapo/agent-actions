import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import { isProcessAlive } from './status';

describe('isProcessAlive', () => {
    it('reports this very process as alive', () => {
        assert.equal(isProcessAlive(process.pid), true);
    });

    it('reports a pid with no such process as gone', () => {
        // ESRCH is the only outcome that actually means "not there".
        assert.equal(isProcessAlive(0x7ffffffe), false);
    });

    it('reports alive when the probe cannot tell', () => {
        // A caller downgrades a running action on false, so anything other
        // than a definite ESRCH must not claim the process is gone. This
        // input raises ERR_INVALID_ARG_TYPE, which a whitelist would have
        // mistaken for death and relabelled a live run as interrupted.
        assert.equal(isProcessAlive('not-a-pid' as unknown as number), true);
    });
});
