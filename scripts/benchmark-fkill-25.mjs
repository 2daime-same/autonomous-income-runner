#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
import {performance} from 'node:perf_hooks';

const [baselineDirectory, patchedDirectory, outputPath] = process.argv.slice(2);
if (!baselineDirectory || !patchedDirectory || !outputPath) {
	throw new Error('Usage: node benchmark-fkill-25.mjs <baseline> <patched> <output.json>');
}

async function load(directory) {
	const root = path.resolve(directory);
	const fkill = (await import(pathToFileURL(path.join(root, 'index.js')).href)).default;
	const noopProcess = (await import(pathToFileURL(path.join(root, 'node_modules/noop-process/index.js')).href)).default;
	return {fkill, noopProcess};
}

async function measure(implementation, samples = 3) {
	const durations = [];
	for (let index = 0; index < samples; index += 1) {
		const pid = await implementation.noopProcess();
		const startedAt = performance.now();
		await implementation.fkill(pid, {force: true});
		durations.push(performance.now() - startedAt);
	}

	const ordered = [...durations].sort((a, b) => a - b);
	return {
		samplesMilliseconds: durations.map(value => Number(value.toFixed(2))),
		medianMilliseconds: Number(ordered[Math.floor(ordered.length / 2)].toFixed(2)),
	};
}

const baseline = await load(baselineDirectory);
const patched = await load(patchedDirectory);

// Alternate after one warm-up so both variants see a comparable runner state.
await measure(baseline, 1);
await measure(patched, 1);
const baselineResult = await measure(baseline);
const patchedResult = await measure(patched);

const improvement = baselineResult.medianMilliseconds / Math.max(patchedResult.medianMilliseconds, 0.01);
const result = {
	platform: process.platform,
	node: process.version,
	baseline: baselineResult,
	patched: patchedResult,
	medianSpeedup: Number(improvement.toFixed(2)),
	note: 'Measures successful PID kills. The baseline performs processExistsMultiple/ps-list before every kill; the patch performs that lookup only after a kill error.',
};

fs.mkdirSync(path.dirname(path.resolve(outputPath)), {recursive: true});
fs.writeFileSync(outputPath, `${JSON.stringify(result, null, 2)}\n`);
console.log(JSON.stringify(result));
