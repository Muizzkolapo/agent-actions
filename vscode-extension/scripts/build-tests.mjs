/**
 * Compile *.test.ts to out-tests/ so `node --test` can run them.
 *
 * Uses the esbuild already present for the extension bundle rather than adding
 * a test-runner dependency. Only modules free of `vscode` imports can be tested
 * this way — the editor API has no implementation outside the host, so logic
 * that needs testing belongs in a vscode-free module.
 */

import { build } from 'esbuild';
import { globSync, rmSync } from 'node:fs';

const entryPoints = globSync('src/**/*.test.ts');

if (entryPoints.length === 0) {
    console.error('No *.test.ts files found under src/');
    process.exit(1);
}

rmSync('out-tests', { recursive: true, force: true });

await build({
    entryPoints,
    outdir: 'out-tests',
    bundle: true,
    platform: 'node',
    format: 'esm',
    target: 'node20',
    sourcemap: 'inline',
    external: ['node:*'],
    outExtension: { '.js': '.mjs' },
});

console.log(`Compiled ${entryPoints.length} test file(s) to out-tests/`);
