#!/usr/bin/env python3
"""Apply and verify the candidate fix for sindresorhus/fkill#25.

The change removes the unconditional process-list lookup from the successful kill
path. Process existence is queried only for kill attempts that actually failed,
so successful PID kills no longer pay the cost of enumerating every process.
"""
from __future__ import annotations

import argparse
from pathlib import Path


INDEX_START = "\tconst exists = await processExistsMultiple([...parsedInputsMap.values()]);"
INDEX_END = "\tif (errors.length > 0 && !options.silent) {"

NEW_BLOCK = r"""	const killErrors = [];

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

""".replace("\\t", "\t")

TEST_MARKER = "test('don\\'t kill self', async () => {"
TEST_NAME = "successful kills are preserved when another input is missing"
TEST_BLOCK = r"""test('successful kills are preserved when another input is missing', async () => {
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

""".replace("\\t", "\t")


def replace_index_block(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    if text.count(INDEX_START) != 1:
        raise RuntimeError(f"Expected one index start marker in {path}")
    if text.count(INDEX_END) != 1:
        raise RuntimeError(f"Expected one index end marker in {path}")
    start = text.index(INDEX_START)
    end = text.index(INDEX_END, start)
    if end <= start:
        raise RuntimeError("Invalid fkill function marker order")
    path.write_text(text[:start] + NEW_BLOCK + text[end:], encoding="utf-8")


def insert_regression_test(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    if TEST_NAME in text:
        return
    if text.count(TEST_MARKER) != 1:
        raise RuntimeError(f"Expected one test insertion marker in {path}")
    path.write_text(text.replace(TEST_MARKER, TEST_BLOCK + TEST_MARKER, 1), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("repository", type=Path)
    args = parser.parse_args()
    repository = args.repository.resolve()

    replace_index_block(repository / "index.js")
    insert_regression_test(repository / "test.js")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
