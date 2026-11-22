import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import {
    localActionLines,
    parseLoadedWorkflow,
    parseWorkflowText,
    uniqueWorkflowName,
} from './workflowText';

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

describe('parseLoadedWorkflow', () => {
    // Raw Jinja that is still valid YAML: a global macro called under `actions:`.
    const RAW = "name: wf\nactions:\n  {{ branch_a('a') | indent(2) }}\n";
    const rendered = {
        text: 'name: wf\nactions:\n  - name: a__extract\n    kind: tool\n',
        error: null,
        actionSources: { a__extract: { uri: TPL, line: 1 } },
    };

    it('uses the render even when the raw text parses', () => {
        const cfg = parseLoadedWorkflow(RAW, 'wf', CFG, rendered);
        assert.deepEqual(cfg?.actions.map((a) => a.name), ['a__extract']);
        assert.deepEqual([...(cfg?.actionLocations ?? [])], []);
    });

    it('throws the render error of the language server', () => {
        assert.throws(
            () => parseLoadedWorkflow(RAW, 'wf', CFG, { text: null, error: 'boom at line 3', actionSources: {} }),
            /boom at line 3/
        );
    });

    it('parses the raw text when there is no render', () => {
        const cfg = parseLoadedWorkflow('actions:\n  - name: x\n', 'wf', CFG, null);
        assert.deepEqual(cfg?.actions.map((a) => a.name), ['x']);
        const noProject = { text: null, error: null, actionSources: {} };
        assert.deepEqual(parseLoadedWorkflow('actions:\n  - name: y\n', 'wf', CFG, noProject)?.actions.map((a) => a.name), ['y']);
    });

    it('names the language server when raw Jinja fails with no render', () => {
        assert.throws(
            () => parseLoadedWorkflow("{% from 'x' import y %}\nactions: []\n", 'wf', CFG, null),
            /loads only through the language server/
        );
    });

    it('keeps the last of two equal keys, as agac does', () => {
        const cfg = parseWorkflowText('actions:\n  - name: a\n    kind: llm\n    kind: tool\n', 'wf');
        assert.equal(cfg?.actions[0].type, 'tool');
    });
});

describe('uniqueWorkflowName', () => {
    it('keeps a name nothing else holds', () => {
        assert.equal(uniqueWorkflowName('w', new Set(['other']), 'agent_config/old/w.yml'), 'w');
    });

    it('adds the path when a loaded workflow holds the name', () => {
        assert.equal(uniqueWorkflowName('w', new Set(['w']), 'agent_config/old/w.yml'), 'w (agent_config/old/w.yml)');
    });
});
