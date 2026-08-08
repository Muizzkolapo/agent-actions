/**
 * Compile *.test.ts to out-tests/ so `node --test` can run them.
 *
 * Uses the esbuild already present for the extension bundle rather than adding
 * a test-runner dependency. Only modules free of `vscode` imports can be tested
 * this way — the editor API has no implementation outside the host, so logic
 * that needs testing belongs in a vscode-free module.
 */

import { build } from 'esbuild';
import { readdirSync, rmSync } from 'node:fs';
import * as path from 'node:path';

// readdirSync's recursive option rather than fs.globSync: glob landed in Node
// 22 and CI runs Node 20.
const entryPoints = readdirSync('src', { recursive: true })
    .map(String)
    .filter((file) => file.endsWith('.test.ts'))
    .map((file) => path.join('src', file));

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
