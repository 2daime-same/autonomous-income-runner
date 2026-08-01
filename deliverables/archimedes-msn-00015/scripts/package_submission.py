#!/usr/bin/env python3
"""Create a deterministic, reviewable MSN-00015 submission archive."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import tempfile
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "dist-submission"
ARCHIVE = OUT / "archimedes-msn-00015-github-pr-mcp.zip"
SOURCE_DATE_EPOCH = int(os.environ.get("SOURCE_DATE_EPOCH", "1785542400"))
FIXED_DATETIME = datetime.fromtimestamp(SOURCE_DATE_EPOCH, tz=timezone.utc)

ROOT_FILES = [
    ".env.example",
    ".gitignore",
    ".npmignore",
    "CHANGELOG.md",
    "LICENSE",
    "README.md",
    "SAFETY.md",
    "SECURITY.md",
    "SUBMISSION.md",
    "package.json",
    "package-lock.json",
    "server.json",
    "tsconfig.json",
    "tsconfig.tests.json",
]
DIRECTORIES = ["docs", "scripts", "src", "tests", "dist"]
EXCLUDED_NAMES = {
    "node_modules",
    "dist-submission",
    ".git",
    ".test-dist",
    ".core-dist",
    "coverage",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def copy_sources(stage: Path) -> None:
    for name in ROOT_FILES:
        source = ROOT / name
        if not source.is_file():
            raise SystemExit(f"Required submission file is missing: {name}")
        destination = stage / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)

    for name in DIRECTORIES:
        source = ROOT / name
        if not source.is_dir():
            raise SystemExit(f"Required submission directory is missing: {name}")
        shutil.copytree(
            source,
            stage / name,
            ignore=shutil.ignore_patterns(*EXCLUDED_NAMES, "*.pyc", "__pycache__"),
        )

    sbom = OUT / "sbom.cdx.json"
    if sbom.is_file():
        shutil.copy2(sbom, stage / "SBOM.cdx.json")

    live_smoke = OUT / "live-smoke.json"
    if live_smoke.is_file():
        shutil.copy2(live_smoke, stage / "LIVE-SMOKE.json")


def write_evidence(stage: Path) -> None:
    evidence = {
        "mission": "MSN-00015",
        "artifact": "GitHub pull-request triage and review MCP server",
        "generated_at": FIXED_DATETIME.isoformat().replace("+00:00", "Z"),
        "source_commit": os.environ.get("GITHUB_SHA") or None,
        "verification_command": "npm run verify",
        "verification_status": os.environ.get("VERIFICATION_STATUS", "not_recorded"),
        "live_smoke_status": os.environ.get("LIVE_SMOKE_STATUS", "not_recorded"),
        "security_audit": os.environ.get("SECURITY_AUDIT_STATUS", "not_recorded"),
        "npm_publication": False,
        "demo_video": False,
        "claims": {
            "platform_submission": False,
            "acceptance": False,
            "payment": False,
            "revenue": False,
        },
    }
    (stage / "TEST-EVIDENCE.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_manifest(stage: Path) -> None:
    lines: list[str] = []
    for path in sorted(p for p in stage.rglob("*") if p.is_file()):
        relative = path.relative_to(stage).as_posix()
        if relative != "MANIFEST.sha256":
            lines.append(f"{sha256(path)}  {relative}")
    (stage / "MANIFEST.sha256").write_text("\n".join(lines) + "\n", encoding="utf-8")


def create_archive(stage: Path) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    ARCHIVE.unlink(missing_ok=True)
    timestamp = (
        max(1980, FIXED_DATETIME.year),
        FIXED_DATETIME.month,
        FIXED_DATETIME.day,
        FIXED_DATETIME.hour,
        FIXED_DATETIME.minute,
        FIXED_DATETIME.second - (FIXED_DATETIME.second % 2),
    )
    with zipfile.ZipFile(ARCHIVE, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(p for p in stage.rglob("*") if p.is_file()):
            relative = path.relative_to(stage).as_posix()
            info = zipfile.ZipInfo(relative, date_time=timestamp)
            executable = relative == "dist/index.js" or relative.startswith("scripts/")
            mode = stat.S_IFREG | (0o755 if executable else 0o644)
            info.external_attr = mode << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            archive.writestr(info, path.read_bytes())

    digest = sha256(ARCHIVE)
    (OUT / f"{ARCHIVE.name}.sha256").write_text(
        f"{digest}  {ARCHIVE.name}\n", encoding="utf-8"
    )
    print(json.dumps({"archive": str(ARCHIVE), "sha256": digest}, indent=2))


def main() -> None:
    os.environ["TZ"] = "UTC"
    if hasattr(time, "tzset"):
        time.tzset()
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="msn-00015-") as temporary:
        stage = Path(temporary) / "archimedes-msn-00015-github-pr-mcp"
        stage.mkdir(parents=True)
        copy_sources(stage)
        write_evidence(stage)
        write_manifest(stage)
        create_archive(stage)


if __name__ == "__main__":
    main()
