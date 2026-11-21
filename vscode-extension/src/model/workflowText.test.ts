import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import { localActionLines, parseWorkflowText } from './workflowText';

const CFG = 'file:///proj/agent_workflow/wf/agent_config/wf.yml';
const TPL = 'file:///proj/templates/branch_b.jinja2';

// What the language server returns for a workflow that calls two macros.
const RENDERED_FIXTURE = [
    '',
    '',
    'name: wf',
    'actions:',
    '  - name: a__extract',
    '    kind: tool',
    '  - name: b__extract',
    '    kind: tool',
    '    dependencies: [a__extract]',
    '',
].join('\n');

describe('parseWorkflowText', () => {
    it('parses rendered text that holds macro actions', () => {
        const cfg = parseWorkflowText(RENDERED_FIXTURE, 'fallback');
        assert.ok(cfg);
        assert.equal(cfg.name, 'wf');
        assert.deepEqual(cfg.actions.map((a) => a.name), ['a__extract', 'b__extract']);
        assert.deepEqual(cfg.actions[1].dependencies, ['a__extract']);
    });

    it('throws on raw Jinja so the caller asks the LSP', () => {
        assert.throws(() => parseWorkflowText("{% from 'x' import y %}\nactions: []\n", 'wf'));
    });

    it('uses the fallback name when the file names none', () => {
        const cfg = parseWorkflowText('actions:\n  - name: x\n', 'from_file');
        assert.equal(cfg?.name, 'from_file');
        assert.equal(cfg?.actionLocations.get('x'), 1);
    });

    it('returns null for a document that is not a mapping', () => {
        assert.equal(parseWorkflowText('', 'wf'), null);
    });
});

describe('localActionLines', () => {
    it('keeps only actions defined in the config file', () => {
        const m = localActionLines({ a: { uri: CFG, line: 4 }, b: { uri: TPL, line: 1 } }, CFG);
        assert.deepEqual([...m], [['a', 4]]);
    });

    it('matches a config URI that the two sides encode differently', () => {
        const python = 'file:///C:/my%20proj/agent_config/wf.yml';
        const vscode = 'file:///c%3A/my%20proj/agent_config/wf.yml';
        const m = localActionLines({ a: { uri: python, line: 2 } }, vscode);
        assert.deepEqual([...m], [['a', 2]]);
    });
});
