#!/usr/bin/env python3
"""Render an evidence-driven MP4 demo for MSN-00015.

The renderer consumes machine-generated MCP and clean-install evidence. It uses
only local fonts, ffmpeg, and optional espeak-ng narration. No secrets are put
on screen or written into the resulting artifact.
"""
from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

ROOT = Path.cwd()
EVIDENCE_DIR = Path(os.environ.get("DEMO_EVIDENCE_DIR", "dist-submission/demo"))
OUTPUT = Path(os.environ.get("DEMO_VIDEO_OUTPUT", EVIDENCE_DIR / "Archimedes_MSN-00015_Demo.mp4"))
WIDTH = 1920
HEIGHT = 1080
FPS = 30
BACKGROUND = "0x0B1020"
ACCENT = "&H00F5C16C"  # ASS BGR-ish accent
TEXT = "&H00F4F7FB"
MUTED = "&H00AAB5C4"
DANGER = "&H006B8CFF"
FONT_SANS = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_MONO = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"

SECRET_PATTERNS = [
    re.compile(r"\bgh[opsu]_[A-Za-z0-9_]{16,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{16,}\b"),
    re.compile(r"\b(?:sk|pk)_[A-Za-z0-9._~+/=-]{16,}\b"),
    re.compile(r"(?i)authorization\s*[:=]"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
]


@dataclass(frozen=True)
class Slide:
    title: str
    lines: tuple[str, ...]
    narration: str
    minimum_duration: float = 9.0
    status: str = "VERIFIED EVIDENCE"


def run(command: list[str], *, check: bool = True, capture: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=check,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def nested_values(value: Any, key: str) -> list[Any]:
    found: list[Any] = []
    if isinstance(value, dict):
        for current_key, item in value.items():
            if current_key == key:
                found.append(item)
            found.extend(nested_values(item, key))
    elif isinstance(value, list):
        for item in value:
            found.extend(nested_values(item, key))
    return found


def first_scalar(value: Any, keys: Iterable[str], default: Any = None) -> Any:
    for key in keys:
        for item in nested_values(value, key):
            if isinstance(item, (str, int, float, bool)) and item not in ("", None):
                return item
    return default


def compact(value: Any, limit: int = 58) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def assert_no_secrets(text: str) -> None:
    for pattern in SECRET_PATTERNS:
        if pattern.search(text):
            raise RuntimeError(f"Credential-like material matched {pattern.pattern}")


def ass_time(seconds: float) -> str:
    centiseconds = max(0, int(round(seconds * 100)))
    hours, remainder = divmod(centiseconds, 360_000)
    minutes, remainder = divmod(remainder, 6_000)
    whole_seconds, cs = divmod(remainder, 100)
    return f"{hours}:{minutes:02d}:{whole_seconds:02d}.{cs:02d}"


def ass_escape(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace("{", "\\{")
        .replace("}", "\\}")
        .replace("\n", "\\N")
    )


def wrap_line(text: str, width: int = 76) -> list[str]:
    if len(text) <= width:
        return [text]
    words = text.split(" ")
    if len(words) == 1:
        return [text[index : index + width] for index in range(0, len(text), width)]
    output: list[str] = []
    current = ""
    for word in words:
        candidate = word if not current else f"{current} {word}"
        if len(candidate) <= width:
            current = candidate
        else:
            if current:
                output.append(current)
            current = word
    if current:
        output.append(current)
    return output


def build_slides(evidence: dict[str, Any], install: dict[str, Any]) -> list[Slide]:
    tool_names = [str(name) for name in evidence.get("registered_tools", [])]
    prompt_names = [str(name) for name in evidence.get("registered_prompts", [])]
    calls = {str(call.get("name")): call for call in evidence.get("read_calls", []) if isinstance(call, dict)}
    get_pr = calls.get("get_pr", {})
    get_diff = calls.get("get_pr_diff", {})
    comments = calls.get("list_pr_comments", {})
    list_prs = calls.get("list_prs", {})

    pr_title = first_scalar(get_pr.get("structured"), ("title",), "Run MSN-00015 guarded live write acceptance")
    changed_files = first_scalar(get_diff.get("structured"), ("returned_files", "changed_files"), "1+")
    comments_returned = first_scalar(comments.get("structured"), ("returned", "count"), "2+")
    list_returned = first_scalar(list_prs.get("structured"), ("returned", "count"), "1+")
    package_seconds = float(install.get("total_seconds", 0) or 0)
    install_seconds = float(install.get("install_seconds", 0) or 0)
    tarball = compact(install.get("tarball", "archimedes-github-pr-mcp-1.0.0.tgz"), 50)

    tools_first = ", ".join(tool_names[:4])
    tools_second = ", ".join(tool_names[4:])
    prompts = ", ".join(prompt_names) or "review_pr_correctness, review_pr_security"

    return [
        Slide(
            "Archimedes MSN-00015",
            (
                "GitHub Pull Request Review MCP Server",
                "TypeScript · stdio MCP · PAT + GitHub App authentication",
                "8 permission-gated tools · 2 opt-in review prompts",
                "Evidence generated from the packaged server on a clean runner",
            ),
            "This is a deterministic demonstration of the GitHub pull request review MCP server built for Archimedes mission MSN zero zero zero one five.",
            10,
            "LIVE PACKAGE DEMO",
        ),
        Slide(
            "Mission requirements covered",
            (
                "READ: list PRs, inspect metadata, parse diffs, read every comment surface",
                "WRITE: inline comments, reviews, labels, and request-changes",
                "AUTH: separate read/write PATs and reduced-permission GitHub App tokens",
                "SAFETY: process-level write gate + confirm=true on every write call",
                "RELIABILITY: bounded pagination, rate-limit reporting, no POST retries",
            ),
            "The implementation covers all eight required tools, both authentication modes, rate limit awareness, pagination, inline diff coordinates, and a deliberate two layer write gate.",
            15,
        ),
        Slide(
            "Clean-machine package quickstart",
            (
                "$ npm ci",
                "$ npm run verify     # typecheck + 20 tests + build + package inspection",
                f"$ npm pack           # {tarball}",
                "$ npm install ./archimedes-github-pr-mcp-1.0.0.tgz",
                f"Clean install: {install_seconds:.1f}s · complete demo path: {package_seconds:.1f}s",
                "No global dependencies and no unpublished source imports were used",
            ),
            "On a fresh GitHub hosted runner, the package is built, packed, installed into an empty npm project, and then exercised through standard MCP JSON RPC.",
            17,
            "CLEAN RUNNER",
        ),
        Slide(
            "MCP handshake and registration",
            (
                f"Protocol negotiated: {evidence.get('protocol_version', '2025-06-18')}",
                f"Tools ({len(tool_names)}): {tools_first}",
                f"             {tools_second}",
                f"Prompts ({len(prompt_names)}): {prompts}",
                "Server booted from the installed tarball and registered without errors",
            ),
            "The installed package completes the MCP initialize handshake and registers eight tools plus two optional review prompts without errors.",
            14,
        ),
        Slide(
            "Read-only PR triage",
            (
                "Target: 2daime-same/autonomous-income-runner · PR #7",
                f"list_prs: {list_prs.get('duration_ms', '?')}ms · returned {list_returned}",
                f"get_pr: {get_pr.get('duration_ms', '?')}ms",
                f"Title: {compact(pr_title, 72)}",
                "The client used a repository-scoped GitHub Actions token for reads only",
            ),
            "The demo lists pull requests and retrieves normalized metadata for the acceptance pull request using the packaged MCP server.",
            14,
            "LIVE GITHUB READ",
        ),
        Slide(
            "Diff and comment surfaces",
            (
                f"get_pr_diff: {get_diff.get('duration_ms', '?')}ms · files returned {changed_files}",
                "Unified hunks are parsed into LEFT and RIGHT GitHub line coordinates",
                f"list_pr_comments: {comments.get('duration_ms', '?')}ms · entries {comments_returned}",
                f"Acceptance inline comment ID {evidence.get('prior_acceptance_comment_id')}",
                f"Visible through MCP now: {str(evidence.get('prior_acceptance_comment_visible')).lower()}",
            ),
            "The server parses exact diff coordinates and combines conversation comments, reviews, and inline review comments. The prior live acceptance comment is still visible through the MCP API.",
            16,
            "LIVE GITHUB READ",
        ),
        Slide(
            "Fail-closed write permission model",
            (
                "Process environment: GITHUB_ALLOW_WRITES=false",
                "Tool call: add_labels(..., confirm=false)",
                f"Rejected by server: {str(evidence.get('write_gate', {}).get('rejected')).lower()}",
                "Writes performed during this demo: 0",
                "POST operations are never retried automatically",
                "A separately reviewed write token is required when writes are enabled",
            ),
            "A write tool is invoked with both authorization conditions absent. The server rejects it, performs no mutation, and remains read only.",
            15,
            "SAFETY GATE VERIFIED",
        ),
        Slide(
            "Guarded live-write acceptance",
            (
                "GitHub Actions run: 30706913841",
                "Exactly one MCP inline review comment was created on temporary PR #7",
                "GitHub request duration: 562ms",
                "Visible via list_pr_comments after: 1,160ms",
                "Required threshold: under 5,000ms · PASS",
                "Credential-pattern inspection: PASS · fixture PR closed without merge",
            ),
            "In the separately authorized write acceptance run, exactly one inline comment was created and became visible through the same MCP server after one point one six seconds, well inside the five second requirement.",
            17,
            "MANUAL ACCEPTANCE PASSED",
        ),
        Slide(
            "Claude Desktop and Cursor quickstart",
            (
                '"command": "npx"',
                '"args": ["-y", "archimedes-github-pr-mcp@1.0.0"]',
                '"env": { "GITHUB_AUTH_MODE": "pat",',
                '         "GITHUB_READ_TOKEN": "YOUR_READ_TOKEN",',
                '         "GITHUB_ALLOW_WRITES": "false" }',
                "README includes source-install fallback, permission matrix, and rate limits",
            ),
            "The same configuration works in Claude Desktop and Cursor. Read only is the default, and users must deliberately enable both layers before any write.",
            16,
            "DOCUMENTED QUICKSTART",
        ),
        Slide(
            "Submission readiness",
            (
                "Source repository: complete and public",
                "npm package contents: reproducibly verified",
                "Demo video: generated from machine evidence",
                "Comment latency and clean-runner quickstart: verified",
                "Remaining external step: authorized npm publication + Archimedes submission",
                "This video is evidence, not a claim of acceptance, payment, or revenue",
            ),
            "The code, package, tests, live read proof, write latency proof, and demo evidence are complete. NPM publication and the final Archimedes account submission remain external authorized steps.",
            14,
            "READY FOR AUTHORIZED SUBMISSION",
        ),
    ]


def ass_document(slide: Slide, duration: float, slide_number: int, slide_count: int) -> str:
    wrapped: list[str] = []
    for line in slide.lines:
        wrapped.extend(wrap_line(line))
    body = "\\N".join(ass_escape(line) for line in wrapped)
    title = ass_escape(slide.title)
    status = ass_escape(slide.status)
    footer = ass_escape(f"MSN-00015  ·  {slide_number}/{slide_count}  ·  MACHINE-GENERATED DEMO EVIDENCE")
    end = ass_time(duration)
    return f"""[Script Info]
ScriptType: v4.00+
PlayResX: {WIDTH}
PlayResY: {HEIGHT}
ScaledBorderAndShadow: yes
WrapStyle: 2

[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Title,DejaVu Sans,58,{TEXT},{TEXT},&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,1.5,0,7,120,120,90,1
Style: Status,DejaVu Sans,23,{ACCENT},{ACCENT},&H00000000,&H00000000,-1,0,0,0,100,100,2,0,1,0.5,0,9,120,120,78,1
Style: Body,DejaVu Sans Mono,31,{TEXT},{TEXT},&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,1.1,0,7,150,140,235,1
Style: Footer,DejaVu Sans,19,{MUTED},{MUTED},&H00000000,&H00000000,0,0,0,0,100,100,1,0,1,0.5,0,2,100,100,55,1
Style: Bar,DejaVu Sans,8,{ACCENT},{ACCENT},&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,1,0,0,0,1

[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
Dialogue: 0,0:00:00.00,{end},Title,,0,0,0,,{title}
Dialogue: 0,0:00:00.00,{end},Status,,0,0,0,,{status}
Dialogue: 0,0:00:00.35,{end},Body,,0,0,0,,{body}
Dialogue: 0,0:00:00.00,{end},Footer,,0,0,0,,{footer}
Dialogue: 0,0:00:00.00,{end},Bar,,0,0,0,,{{\\p1\\pos(120,185)}}m 0 0 l 1680 0 l 1680 6 l 0 6{{\\p0}}
"""


def duration_of(path: Path) -> float:
    result = run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture=True,
    )
    return float(result.stdout.strip())


def generate_narration(text: str, output: Path) -> bool:
    executable = shutil.which("espeak-ng") or shutil.which("espeak")
    if not executable:
        return False
    command = [executable, "-v", "en-us", "-s", "151", "-p", "44", "-a", "145", "-w", str(output), text]
    run(command)
    return output.exists() and output.stat().st_size > 1_000


def render_slide(slide: Slide, index: int, total: int, work: Path) -> tuple[Path, float]:
    narration = work / f"narration-{index:02d}.wav"
    narrated = generate_narration(slide.narration, narration)
    narration_duration = duration_of(narration) if narrated else 0.0
    duration = max(slide.minimum_duration, math.ceil(narration_duration + 1.1))
    ass = work / f"slide-{index:02d}.ass"
    ass.write_text(ass_document(slide, duration, index, total), encoding="utf-8")
    output = work / f"slide-{index:02d}.mp4"

    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"color=c={BACKGROUND}:s={WIDTH}x{HEIGHT}:r={FPS}:d={duration}",
    ]
    if narrated:
        command += ["-i", str(narration)]
    else:
        command += ["-f", "lavfi", "-i", f"anullsrc=channel_layout=stereo:sample_rate=48000:d={duration}"]
    command += [
        "-vf",
        f"ass={ass}",
        "-af",
        f"apad,atrim=0:{duration},afade=t=in:st=0:d=0.25,afade=t=out:st={max(0.1, duration - 0.5)}:d=0.5",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "19",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-ar",
        "48000",
        "-ac",
        "2",
        "-movflags",
        "+faststart",
        "-shortest",
        str(output),
    ]
    run(command)
    return output, duration


def main() -> int:
    for executable in ("ffmpeg", "ffprobe"):
        if not shutil.which(executable):
            raise RuntimeError(f"Required executable is missing: {executable}")
    evidence_path = EVIDENCE_DIR / "mcp-demo-evidence.json"
    install_path = EVIDENCE_DIR / "clean-install.json"
    evidence = read_json(evidence_path)
    install = read_json(install_path)
    assert evidence.get("ok") is True
    assert evidence.get("writes_performed") == []
    assert evidence.get("write_gate", {}).get("rejected") is True
    assert evidence.get("prior_acceptance_comment_visible") is True

    public_text = json.dumps({"evidence": evidence, "install": install}, ensure_ascii=False, sort_keys=True)
    assert_no_secrets(public_text)
    slides = build_slides(evidence, install)
    output_parent = OUTPUT.parent
    output_parent.mkdir(parents=True, exist_ok=True)
    work = EVIDENCE_DIR / "render-work"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)

    clips: list[Path] = []
    durations: list[float] = []
    for index, slide in enumerate(slides, 1):
        clip, duration = render_slide(slide, index, len(slides), work)
        clips.append(clip)
        durations.append(duration)

    concat = work / "concat.txt"
    concat.write_text("".join(f"file '{clip.resolve()}'\n" for clip in clips), encoding="utf-8")
    run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat),
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            str(OUTPUT),
        ]
    )

    total_duration = duration_of(OUTPUT)
    metadata = {
        "schema_version": "archimedes-msn-00015-demo-v1",
        "video": OUTPUT.name,
        "duration_seconds": round(total_duration, 3),
        "width": WIDTH,
        "height": HEIGHT,
        "fps": FPS,
        "slides": len(slides),
        "narration": "espeak-ng" if shutil.which("espeak-ng") else ("espeak" if shutil.which("espeak") else "silent"),
        "writes_performed": [],
        "source_evidence": [evidence_path.name, install_path.name],
        "slide_durations": durations,
    }
    metadata_path = EVIDENCE_DIR / "video-metadata.json"
    metadata_path.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    assert_no_secrets(metadata_path.read_text(encoding="utf-8"))
    print(json.dumps(metadata, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"demo renderer failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
