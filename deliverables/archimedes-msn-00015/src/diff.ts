import { GitHubApiError } from './errors.js';
import type { DiffSide, ParsedDiffHunk, ParsedDiffLine, ParsedFileDiff } from './types.js';

const HUNK_HEADER = /^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@/;

interface GitHubFileLike {
  filename?: unknown;
  previous_filename?: unknown;
  status?: unknown;
  additions?: unknown;
  deletions?: unknown;
  changes?: unknown;
  patch?: unknown;
}

function integer(value: unknown): number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0 ? value : 0;
}

export function parsePatch(patch: string): ParsedDiffHunk[] {
  const hunks: ParsedDiffHunk[] = [];
  const lines = patch.split('\n');
  let current: ParsedDiffHunk | null = null;
  let oldLine = 0;
  let newLine = 0;
  let position = 0;

  for (const line of lines) {
    const header = HUNK_HEADER.exec(line);
    if (header) {
      const oldStart = Number(header[1]);
      const oldCount = Number(header[2] ?? '1');
      const newStart = Number(header[3]);
      const newCount = Number(header[4] ?? '1');
      current = {
        header: line,
        oldStart,
        oldCount,
        newStart,
        newCount,
        lines: [],
      };
      hunks.push(current);
      oldLine = oldStart;
      newLine = newStart;
      position += 1;
      continue;
    }
    if (!current || line.startsWith('\\ No newline at end of file')) {
      continue;
    }
    position += 1;
    let parsed: ParsedDiffLine | null = null;
    if (line.startsWith('+') && !line.startsWith('+++')) {
      parsed = {
        position,
        kind: 'addition',
        text: line.slice(1),
        oldLine: null,
        newLine,
      };
      newLine += 1;
    } else if (line.startsWith('-') && !line.startsWith('---')) {
      parsed = {
        position,
        kind: 'deletion',
        text: line.slice(1),
        oldLine,
        newLine: null,
      };
      oldLine += 1;
    } else if (line.startsWith(' ')) {
      parsed = {
        position,
        kind: 'context',
        text: line.slice(1),
        oldLine,
        newLine,
      };
      oldLine += 1;
      newLine += 1;
    }
    if (parsed) {
      current.lines.push(parsed);
    }
  }
  return hunks;
}

export function parseFileDiff(file: GitHubFileLike, includePatch = true): ParsedFileDiff {
  const path = typeof file.filename === 'string' ? file.filename : '';
  if (!path) {
    throw new GitHubApiError('invalid_response', 'GitHub file response did not include filename.');
  }
  const patch = typeof file.patch === 'string' ? file.patch : null;
  return {
    path,
    previousPath: typeof file.previous_filename === 'string' ? file.previous_filename : null,
    status: typeof file.status === 'string' ? file.status : 'unknown',
    additions: integer(file.additions),
    deletions: integer(file.deletions),
    changes: integer(file.changes),
    binary: patch === null && integer(file.changes) === 0 ? true : patch === null ? null : false,
    patchUnavailable: patch === null,
    patchTruncated: patch !== null && !patch.endsWith('\n') && patch.length >= 65_000,
    hunks: patch === null ? [] : parsePatch(patch),
    rawPatch: includePatch ? patch : null,
  };
}

function lineExists(file: ParsedFileDiff, line: number, side: DiffSide): boolean {
  return file.hunks.some((hunk) =>
    hunk.lines.some((entry) =>
      side === 'RIGHT' ? entry.newLine === line : entry.oldLine === line,
    ),
  );
}

function hunkForLine(file: ParsedFileDiff, line: number, side: DiffSide): ParsedDiffHunk | null {
  return (
    file.hunks.find((hunk) =>
      hunk.lines.some((entry) =>
        side === 'RIGHT' ? entry.newLine === line : entry.oldLine === line,
      ),
    ) ?? null
  );
}

export function validateDiffLocation(
  file: ParsedFileDiff,
  line: number,
  side: DiffSide,
  startLine?: number,
  startSide?: DiffSide,
): void {
  if (file.patchUnavailable || file.hunks.length === 0) {
    throw new GitHubApiError(
      'invalid_diff_location',
      'The selected file has no commentable text patch.',
    );
  }
  if (!Number.isSafeInteger(line) || line < 1 || !lineExists(file, line, side)) {
    throw new GitHubApiError(
      'invalid_diff_location',
      `Line ${line} is not present on the ${side} side of the pull-request diff.`,
    );
  }
  if (startLine === undefined && startSide === undefined) {
    return;
  }
  if (startLine === undefined || startSide === undefined) {
    throw new GitHubApiError(
      'invalid_diff_location',
      'start_line and start_side must be supplied together.',
    );
  }
  if (!Number.isSafeInteger(startLine) || startLine < 1 || !lineExists(file, startLine, startSide)) {
    throw new GitHubApiError(
      'invalid_diff_location',
      `Start line ${startLine} is not present on the ${startSide} side of the diff.`,
    );
  }
  if (startSide !== side) {
    throw new GitHubApiError(
      'invalid_diff_location',
      'Multi-line review comments must use the same side for start_side and side.',
    );
  }
  const startHunk = hunkForLine(file, startLine, startSide);
  const endHunk = hunkForLine(file, line, side);
  if (!startHunk || startHunk !== endHunk) {
    throw new GitHubApiError(
      'invalid_diff_location',
      'Multi-line review comments must remain within one diff hunk.',
    );
  }
  if (startLine > line) {
    throw new GitHubApiError(
      'invalid_diff_location',
      'start_line must be less than or equal to line.',
    );
  }
}

export function compactFileDiff(file: ParsedFileDiff, maximumLines: number): ParsedFileDiff {
  let remaining = maximumLines;
  const hunks: ParsedDiffHunk[] = [];
  for (const hunk of file.hunks) {
    if (remaining <= 0) {
      break;
    }
    const selected = hunk.lines.slice(0, remaining);
    hunks.push({ ...hunk, lines: selected });
    remaining -= selected.length;
  }
  return {
    ...file,
    hunks,
    patchTruncated:
      file.patchTruncated || file.hunks.reduce((sum, hunk) => sum + hunk.lines.length, 0) > maximumLines,
  };
}
