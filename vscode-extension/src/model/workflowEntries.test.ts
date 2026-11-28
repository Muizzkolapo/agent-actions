import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import { branchNames, extractActionLocations, parseEntries } from './workflowEntries';

// The entries as the `yaml` library parses them. The test bundle cannot load that
// library (it requires `process` dynamically), so they are written as objects.
const ROUND = {
    branch: 'round',
    inputs: { spec: 'Holds the specification' },
    outputs: ['finalize'],
    actions: [
        { name: 'write', dependencies: ['spec'] },
        { name: 'finalize', dependencies: ['write'] },
    ],
};

const ENTRIES = [
    { name: 'classify' },
    { route: 'router', on: 'classify.format', cases: { mc: ['mc_write'], matching: 'm' }, default: 'filter' },
    { name: 'mc_write' },
    { include: 'round', as: 'm', inputs: { spec: 'classify' } },
    { join: 'bank', of: ['mc_write', 'm'] },
    { name: 'publish', dependencies: ['bank'] },
];

const CONTENT = `actions:
  - name: classify
  - route: router
    on: classify.format
  - join: bank
    of: [classify]
  - loop: round
`;

function nodes(entries: unknown[], branches: Record<string, unknown> = { round: ROUND }) {
    const parsed = parseEntries(entries, (name) => branches[name]);
    return new Map(parsed.map((action) => [action.name, action]));
}

describe('parseEntries', () => {
    it('gives a route entry a node that depends on the action of its field', () => {
        const router = nodes(ENTRIES).get('router');

        assert.deepEqual(router?.dependencies, ['classify']);
        assert.equal(router?.type, 'route');
    });

    it('gives each retrieve entry a step node that the action depends on', () => {
        const parsed = nodes([
            { name: 'classify' },
            {
                name: 'write_reply',
                dependencies: ['classify'],
                context_scope: {
                    retrieve: {
                        help: { from: 'kb', query: ['source.text'], where: { product: 'classify.product' } },
                    },
                },
            },
        ]);

        assert.deepEqual(parsed.get('write_reply__help')?.dependencies, ['classify']);
        assert.equal(parsed.get('write_reply__help')?.type, 'retrieve');
        assert.deepEqual(parsed.get('write_reply')?.dependencies, ['classify', 'write_reply__help']);
    });

    it('makes a retrieve step depend on the earlier action its from: names', () => {
        const parsed = nodes([
            { name: 'summarize' },
            {
                name: 'link',
                dependencies: ['summarize'],
                context_scope: {
                    retrieve: {
                        similar: { from: 'summarize', text: ['summary'], query: ['source.text'] },
                        help: { from: 'kb', query: ['source.text'] },
                    },
                },
            },
        ]);

        assert.deepEqual(parsed.get('link__similar')?.dependencies, ['summarize']);
        assert.deepEqual(parsed.get('link__help')?.dependencies, []);
    });

    it('makes the entry actions of each case depend on the router', () => {
        const parsed = nodes(ENTRIES);

        assert.deepEqual(parsed.get('mc_write')?.dependencies, ['router']);
        assert.deepEqual(parsed.get('m__write')?.dependencies, ['classify', 'router']);
        assert.deepEqual(parsed.get('m__finalize')?.dependencies, ['m__write']);
    });

    it('gives a join entry a node that depends on what it joins, an instance by its output', () => {
        const parsed = nodes(ENTRIES);

        assert.deepEqual(parsed.get('bank')?.dependencies, ['mc_write', 'm__finalize']);
        assert.equal(parsed.get('bank')?.type, 'join');
        assert.deepEqual(parsed.get('publish')?.dependencies, ['bank']);
    });

    it('renames the actions of an include with as:, and binds its inputs', () => {
        const parsed = nodes([
            { name: 'a' },
            { include: 'round', as: 'c', inputs: { spec: 'a' } },
            { include: 'round', as: 'c2', inputs: { spec: 'c__finalize' } },
        ]);

        assert.deepEqual(
            [...parsed.keys()],
            ['a', 'c__write', 'c__finalize', 'c2__write', 'c2__finalize']
        );
        assert.deepEqual(parsed.get('c__write')?.dependencies, ['a']);
        assert.deepEqual(parsed.get('c2__write')?.dependencies, ['c__finalize']);
    });

    it('keeps the names of an include without as:, and leaves out a removed action', () => {
        const parsed = nodes([{ name: 'spec' }, { include: 'round', remove: ['finalize'] }]);

        assert.deepEqual([...parsed.keys()], ['spec', 'write']);
    });

    it('expands the versions of a branch action under its final name', () => {
        const versioned = {
            ...ROUND,
            actions: [{ name: 'vote', versions: { range: [1, 2] } }],
            outputs: [],
        };

        const parsed = nodes([{ include: 'round', as: 'c' }], { round: versioned });

        assert.deepEqual([...parsed.keys()], ['c__vote_1', 'c__vote_2']);
        assert.equal(parsed.get('c__vote_1')?.baseName, 'c__vote');
    });

    it('shows no actions for an include whose branch file cannot be read', () => {
        assert.deepEqual(
            [...nodes(ENTRIES, {}).keys()],
            ['classify', 'router', 'mc_write', 'bank', 'publish']
        );
    });

    it('reads a router on a source field as having no upstream action', () => {
        const parsed = nodes([
            { route: 'r', on: 'source.kind', cases: { a: ['x'] }, default: 'filter' },
            { name: 'x' },
        ]);

        assert.deepEqual(parsed.get('r')?.dependencies, []);
        assert.deepEqual(parsed.get('x')?.dependencies, ['r']);
    });
});

describe('a loop entry', () => {
    const REVIEWED = {
        branch: 'round',
        inputs: { spec: 'Holds the specification', prior: 'The previous review' },
        outputs: ['check'],
        actions: [
            { name: 'write', dependencies: ['spec', 'prior'] },
            { name: 'check', dependencies: ['write'] },
        ],
    };
    const LOOP = {
        loop: 'round',
        include: 'round',
        max_iterations: 3,
        inputs: { spec: 'a' },
        feedback: { prior: 'check' },
        until: 'check.passed == true',
        result: 'check',
    };

    it('unrolls into its iterations and a node named after it that takes each result', () => {
        const parsed = nodes([{ name: 'a' }, LOOP, { name: 'after', dependencies: ['round'] }], {
            round: REVIEWED,
        });

        assert.deepEqual(
            [...parsed.keys()],
            [
                'a',
                'round_iter1__write',
                'round_iter1__check',
                'round_iter2__write',
                'round_iter2__check',
                'round_iter3__write',
                'round_iter3__check',
                'round',
                'after',
            ]
        );
        assert.deepEqual(parsed.get('round')?.dependencies, [
            'round_iter1__check',
            'round_iter2__check',
            'round_iter3__check',
        ]);
        assert.equal(parsed.get('round')?.type, 'loop');
    });

    it('feeds nothing back into the first iteration, and the previous result into the next', () => {
        const parsed = nodes([{ name: 'a' }, LOOP], { round: REVIEWED });

        assert.deepEqual(parsed.get('round_iter1__write')?.dependencies, ['a']);
        assert.deepEqual(parsed.get('round_iter2__write')?.dependencies, ['round_iter1__check']);
        assert.deepEqual(parsed.get('round_iter3__check')?.dependencies, ['round_iter3__write']);
    });
});

describe('branchNames', () => {
    it('lists each branch file an include or a loop reads, once', () => {
        assert.deepEqual(branchNames([...ENTRIES, { include: 'round', as: 'n' }]), ['round']);
        assert.deepEqual(branchNames([{ loop: 'l', include: 'other' }]), ['other']);
    });
});

describe('extractActionLocations', () => {
    it('finds the line of each action, route and join name', () => {
        const locations = extractActionLocations(CONTENT);

        assert.equal(locations.get('classify'), 1);
        assert.equal(locations.get('router'), 2);
        assert.equal(locations.get('bank'), 4);
        assert.equal(locations.get('round'), 6);
    });
});
