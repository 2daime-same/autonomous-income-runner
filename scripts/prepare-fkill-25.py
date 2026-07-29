#!/usr/bin/env python3
"""Apply and verify the candidate fix for sindresorhus/fkill#25.

The change removes the unconditional process-list lookup from the successful kill
path. Process existence is queried only for kill attempts that actually failed,
so successful PID kills no longer pay the cost of enumerating every process.
"""
from __future__ import annotations

import argparse
from pathlib import Path


OLD_BLOCK = """\tconst exists = await processExistsMultiple([...parsedInputsMap.values()]);

\tconst errors = [];

\tconst handleKill = async input => {
\t\tconst parsedInput = parsedInputsMap.get(input);

\t\ttry {
\t\t\tawait killWithLimits(input, options);
\t\t} catch (error) {
\t\t\tif (!exists.get(parsedInput)) {
\t\t\t\terrors.push(`Killing process ${input} failed: Process doesn't exist`);
\t\t\t\treturn;
\t\t\t}

\t\t\terrors.push(`Killing process ${input} failed: ${error.message.replace(/.*\\n/, '').replace(/kill: \\d+: /, '').trim()}`);
\t\t}
\t};

\tawait Promise.all(inputs.map(input => handleKill(input)));

\tif (errors.length > 0 && !options.silent) {
"""

NEW_BLOCK = """\tconst killErrors = [];

\tconst handleKill = async input => {
\t\ttry {
\t\t\tawait killWithLimits(input, options);
\t\t} catch (error) {
\t\t\tkillErrors.push({input, parsedInput: parsedInputsMap.get(input), error});
\t\t}
\t};

\tawait Promise.all(inputs.map(input => handleKill(input)));

\tconst errors = [];
\tif (killErrors.length > 0) {
\t\tconst failedInputs = [...new Set(killErrors.map(({parsedInput}) => parsedInput))];
\t\tconst exists = await processExistsMultiple(failedInputs);

\t\tfor (const {input, parsedInput, error} of killErrors) {
\t\t\tif (!exists.get(parsedInput)) {
\t\t\t\terrors.push(`Killing process ${input} failed: Process doesn't exist`);
\t\t\t\tcontinue;
\t\t\t}

\t\t\terrors.push(`Killing process ${input} failed: ${error.message.replace(/.*\\n/, '').replace(/kill: \\d+: /, '').trim()}`);
\t\t}
\t}

\tif (errors.length > 0 && !options.silent) {
"""

TEST_ANCHOR = """test('fail', async () => {
\ttry {
\t\tawait fkill(['123456', '654321']);
\t\tassert.fail('Expected error to be thrown');
\t} catch (error) {
\t\tassert.ok(error instanceof AggregateError);
\t\tconst errorString = error.errors.join(' ');
\t\tassert.match(errorString, /123456/);
\t\tassert.match(errorString, /654321/);
\t}
});
"""

TEST_REPLACEMENT = TEST_ANCHOR + """

test('successful kills are preserved when another input is missing', async () => {
\tconst pid = await noopProcess();

\ttry {
\t\tawait fkill([pid, 'fkill-process-that-does-not-exist'], {force: true});
\t\tassert.fail('Expected error to be thrown');
\t} catch (error) {
\t\tassert.ok(error instanceof AggregateError);
\t\tassert.match(error.errors.join(' '), /fkill-process-that-does-not-exist/);
\t\tassert.match(error.errors.join(' '), /Process doesn't exist/);
\t}

\tawait noopProcessKilled(pid);
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
