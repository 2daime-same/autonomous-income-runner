#!/usr/bin/env python3
"""Apply and verify the candidate fix for sindresorhus/fkill#25.

The change removes the unconditional process-list lookup from the successful kill
path. Process existence is queried only for kill attempts that actually failed,
so successful PID kills no longer pay the cost of enumerating every process.
"""
from __future__ import annotations

import argparse
from pathlib import Path


OLD_BLOCK = """	const exists = await processExistsMultiple([...parsedInputsMap.values()]);

	const errors = [];

	const handleKill = async input => {
		const parsedInput = parsedInputsMap.get(input);

		try {
			await killWithLimits(input, options);
		} catch (error) {
			if (!exists.get(parsedInput)) {
				errors.push(`Killing process ${input} failed: Process doesn't exist`);
				return;
			}

			errors.push(`Killing process ${input} failed: ${error.message.replace(/.*\n/, '').replace(/kill: \d+: /, '').trim()}`);
		}
	};

	await Promise.all(inputs.map(input => handleKill(input)));

	if (errors.length > 0 && !options.silent) {
"""

NEW_BLOCK = """	const killErrors = [];

	const handleKill = async input => {
		try {
			await killWithLimits(input, options);
		} catch (error) {
			killErrors.push({input, parsedInput: parsedInputsMap.get(input), error});
		}
	};

	await Promise.all(inputs.map(input => handleKill(input)));

	const errors = [];
	if (killErrors.length > 0) {
		const failedInputs = [...new Set(killErrors.map(({parsedInput}) => parsedInput))];
		const exists = await processExistsMultiple(failedInputs);

		for (const {input, parsedInput, error} of killErrors) {
			if (!exists.get(parsedInput)) {
				errors.push(`Killing process ${input} failed: Process doesn't exist`);
				continue;
			}

			errors.push(`Killing process ${input} failed: ${error.message.replace(/.*\n/, '').replace(/kill: \d+: /, '').trim()}`);
		}
	}

	if (errors.length > 0 && !options.silent) {
"""

TEST_ANCHOR = """test('fail', async () => {
	try {
		await fkill(['123456', '654321']);
		assert.fail('Expected error to be thrown');
	} catch (error) {
		assert.ok(error instanceof AggregateError);
		const errorString = error.errors.join(' ');
		assert.match(errorString, /123456/);
		assert.match(errorString, /654321/);
	}
});
"""

TEST_REPLACEMENT = TEST_ANCHOR + """
test('successful kills are preserved when another input is missing', async () => {
	const pid = await noopProcess();

	try {
		await fkill([pid, 'fkill-process-that-does-not-exist'], {force: true});
		assert.fail('Expected error to be thrown');
	} catch (error) {
		assert.ok(error instanceof AggregateError);
		assert.match(error.errors.join(' '), /fkill-process-that-does-not-exist/);
		assert.match(error.errors.join(' '), /Process doesn't exist/);
	}

	await noopProcessKilled(pid);
});
"""


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"Expected one match in {path}, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("repository", type=Path)
    args = parser.parse_args()
    repository = args.repository.resolve()

    replace_once(repository / "index.js", OLD_BLOCK, NEW_BLOCK)
    replace_once(repository / "test.js", TEST_ANCHOR, TEST_REPLACEMENT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
