#!/usr/bin/env python3
"""Build and statically validate the one-file Bubble Brawl Taskmarket artifact."""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

SOURCE = Path(os.environ.get("BUBBLE_BRAWL_SOURCE", "deliverables/taskmarket-bubble-brawl/source.html"))
THREE = Path(os.environ.get("BUBBLE_BRAWL_THREE", "/tmp/three.min.js"))
OUTPUT = Path(os.environ.get("BUBBLE_BRAWL_OUTPUT", "deliverables/taskmarket-bubble-brawl/index.html"))
REPORT = Path(os.environ.get("BUBBLE_BRAWL_REPORT", "deliverables/taskmarket-bubble-brawl/validation-report.json"))
MARKER = '<script data-three-bundle src="https://cdn.jsdelivr.net/npm/three@0.158.0/build/three.min.js"></script>'
CREDENTIAL = re.compile(
    r"(-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|"
    r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b|github_pat_[A-Za-z0-9_]{20,}|"
    r"\beyJ[A-Za-z0-9._-]{20,}\b)"
)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    source = SOURCE.read_text(encoding="utf-8")
    library = THREE.read_text(encoding="utf-8")
    if source.count(MARKER) != 1:
        raise SystemExit("expected exactly one pinned Three.js bundle marker")
    if len(library) < 500_000 or "REVISION" not in library:
        raise SystemExit("Three.js bundle is unexpectedly small or malformed")
    library = library.replace("</script", "<\\/script")
    final = source.replace(
        MARKER,
        '<script data-vendor="three@0.158.0">\n'
        '/* Vendored from the official three@0.158.0 npm package at build time. */\n'
        + library
        + "\n</script>",
    )
    encoded = final.encode("utf-8")

    failures: list[str] = []
    if '<script src=' in final.lower() or "data-three-bundle" in final:
        failures.append("runtime script dependency remains")
    if re.search(r"\b(?:src|href)=[\"']https?://", final, re.I):
        failures.append("runtime network asset remains")
    if not 550_000 <= len(encoded) <= 2_500_000:
        failures.append(f"unexpected artifact size: {len(encoded)}")
    required = {
        "Three.js renderer": "new THREE.WebGLRenderer",
        "enemy trapping": "captureEnemy",
        "bubble escape timer": "escapeBubble",
        "gather field": "GATHER FIELD",
        "chain scheduler": "schedulePop",
        "quadratic chain score": "100*n*n",
        "distinct chaser": "type==='chaser'",
        "distinct zigzag": "type==='zigzag'",
        "distinct dasher": "type==='dasher'",
        "distinct splitter": "type==='splitter'",
        "keyboard controls": "WASD",
        "touch controls": "id=\"touch\"",
        "health fail state": "state.health--",
        "biggest chain": "id=\"bestChain\"",
        "high score": "bubbleBrawlHigh",
        "instant restart": "RESTART BRAWL",
    }
    for label, token in required.items():
        if token not in final:
            failures.append(f"missing requirement marker: {label}")
    if CREDENTIAL.search(final):
        failures.append("credential-like material detected")
    if failures:
        raise SystemExit("; ".join(failures))

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT.with_suffix(".html.tmp")
    temporary.write_bytes(encoded)
    os.replace(temporary, OUTPUT)

    report = {
        "schema_version": "bubble-brawl-validation-v1",
        "task_id": "0xc0654d7b1a1dc86ad4d9bb00187b1e32f929094f614c3fe4ca0305c0bffcedf9",
        "artifact": {
            "path": str(OUTPUT),
            "file_name": "index.html",
            "mime_type": "text/html",
            "size_bytes": len(encoded),
            "sha256": sha256(encoded),
            "runtime_external_assets": 0,
            "three_version": "0.158.0",
        },
        "static_checks": {label: True for label in required},
        "credential_scan": "passed",
        "expenses_usdc": 0,
        "verified_income_usdc": 0,
        "browser_smoke": "pending",
    }
    REPORT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "size": len(encoded), "sha256": sha256(encoded)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
