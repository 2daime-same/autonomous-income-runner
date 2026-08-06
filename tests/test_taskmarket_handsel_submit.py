from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import taskmarket_handsel_submit as submitter

TASK_ID = "0x7eeff4e1991bd0d40eee406777fc568abf341ecff3368d991f89cf9d0d6f6e04"


class SubmitterTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="handsel-submit-test-")
        self.root = Path(self.temp.name)
        self.auth = self.root / "authorization.json"
        self.state = self.root / "state"
        self.secret = self.root / "secret"
        self.report = self.root / "HANDSEL_NETWORK_LABEL_AUDIT.md"
        self.evidence = self.root / "evidence.json"
        self.top = self.root / "TOP_SHEET.md"
        self.report.write_text("# audit\nNo literal mainnet/testnet labels.\n", encoding="utf-8")
        self.evidence.write_text('{"answer":"no"}\n', encoding="utf-8")
        self.top.write_text("# top sheet\nAI-assisted public audit.\n", encoding="utf-8")
        current = datetime.now(timezone.utc)
        authorization = {
            "schema_version": "taskmarket-handsel-submission-authorization-v1",
            "attempt_id": "handsel-label-audit-test-01",
            "authorized": True,
            "authorization_source": "unit-test",
            "authorized_at": (current - timedelta(minutes=1)).isoformat(),
            "expires_at": (current + timedelta(hours=1)).isoformat(),
            "zero_spend_required": True,
            "task_id": TASK_ID,
            "expected_title_terms": ["handsel", "mainnet", "testnet"],
            "minimum_reward_usdc": 5,
            "maximum_existing_submissions": 30,
            "artifacts": [
                {
                    "path": str(self.report),
                    "file_name": self.report.name,
                    "mime_type": "text/markdown",
                    "role": "final",
                },
                {
                    "path": str(self.evidence),
                    "file_name": self.evidence.name,
                    "mime_type": "application/json",
                    "role": "attachment",
                },
                {
                    "path": str(self.top),
                    "file_name": self.top.name,
                    "mime_type": "text/markdown",
                    "role": "attachment",
                },
            ],
        }
        self.auth.write_text(json.dumps(authorization), encoding="utf-8")
        self.old = {
            "AUTHORIZATION": submitter.AUTHORIZATION,
            "STATE_DIRECTORY": submitter.STATE_DIRECTORY,
            "ATTEMPT_STATE": submitter.ATTEMPT_STATE,
            "EVIDENCE": submitter.EVIDENCE,
            "ENCRYPTED_WALLET": submitter.ENCRYPTED_WALLET,
            "CERTIFICATE": submitter.CERTIFICATE,
            "SECRET_DIRECTORY": submitter.SECRET_DIRECTORY,
        }
        submitter.AUTHORIZATION = self.auth
        submitter.STATE_DIRECTORY = self.state
        submitter.ATTEMPT_STATE = self.state / "attempt.json"
        submitter.EVIDENCE = self.state / "submission-evidence.json"
        submitter.ENCRYPTED_WALLET = self.state / "private-wallet.cms.b64"
        submitter.CERTIFICATE = ROOT / "crypto/superteam-state-public.crt"
        submitter.SECRET_DIRECTORY = self.secret

    def tearDown(self) -> None:
        for key, value in self.old.items():
            setattr(submitter, key, value)
        self.temp.cleanup()

    @staticmethod
    def task(status: str = "open") -> dict:
        return {
            "id": TASK_ID,
            "title": "Check whether Handsel's mainnet vs. testnet labels are stated",
            "description": "Audit the public environment labels and explain the answer.",
            "status": status,
            "mode": "bounty",
            "reward": "5000000",
            "submissionWindowOpen": status == "open",
            "expiry": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
            "requesterAddress": "0x" + "11" * 20,
        }

    def test_prepare_and_submit_success_once(self) -> None:
        captured = {"posts": 0, "worker": None}

        def fake_request(method: str, path: str, body=None):
            if method == "GET" and path.endswith("/submissions"):
                rows = [
                    {"id": f"old-{index}", "workerAddress": "0x" + f"{index + 1:040x}"}
                    for index in range(12)
                ]
                if captured["worker"]:
                    rows.append({"id": "submission-1", "workerAddress": captured["worker"]})
                return 200, rows
            if method == "GET":
                return 200, self.task()
            if method == "POST":
                captured["posts"] += 1
                captured["worker"] = body["workerAddress"]
                self.assertEqual(body["taskId"], TASK_ID)
                self.assertEqual(len(body["artifacts"]), 3)
                self.assertTrue(body["signature"].startswith("0x"))
                return 201, {"success": True, "submissionId": "submission-1"}
            raise AssertionError((method, path))

        with patch.object(submitter, "request_json", side_effect=fake_request):
            self.assertEqual(submitter.prepare(), 0)
            state = json.loads(submitter.ATTEMPT_STATE.read_text())
            self.assertEqual(state["status"], "in_progress")
            state_text = json.dumps(state).lower()
            self.assertNotIn('"signature":', state_text)
            self.assertNotIn('"private_key":', state_text)
            self.assertTrue(submitter.ENCRYPTED_WALLET.is_file())
            self.assertEqual(submitter.submit(), 0)

        self.assertEqual(captured["posts"], 1)
        final = json.loads(submitter.EVIDENCE.read_text())
        self.assertEqual(final["status"], "success")
        self.assertEqual(final["submission_id"], "submission-1")
        self.assertEqual(final["external_writes_performed"][0]["count"], 1)
        self.assertFalse(submitter.secret_path("handsel-label-audit-test-01").exists())

    def test_known_http_rejection_is_not_retried(self) -> None:
        captured = {"posts": 0}

        def fake_request(method: str, path: str, body=None):
            if method == "GET" and path.endswith("/submissions"):
                return 200, []
            if method == "GET":
                return 200, self.task()
            if method == "POST":
                captured["posts"] += 1
                return 400, {"error": "submission rejected"}
            raise AssertionError((method, path))

        with patch.object(submitter, "request_json", side_effect=fake_request):
            self.assertEqual(submitter.prepare(), 0)
            self.assertEqual(submitter.submit(), 2)

        self.assertEqual(captured["posts"], 1)
        final = json.loads(submitter.EVIDENCE.read_text())
        self.assertEqual(final["status"], "rejected")
        self.assertEqual(len(final["external_writes_performed"]), 1)

    def test_closed_task_before_write_causes_zero_writes(self) -> None:
        captured = {"posts": 0, "get_task_calls": 0}

        def fake_request(method: str, path: str, body=None):
            if method == "GET" and path.endswith("/submissions"):
                return 200, []
            if method == "GET":
                captured["get_task_calls"] += 1
                return 200, self.task(
                    status="open" if captured["get_task_calls"] == 1 else "closed"
                )
            if method == "POST":
                captured["posts"] += 1
                return 201, {"success": True, "submissionId": "unexpected"}
            raise AssertionError((method, path))

        with patch.object(submitter, "request_json", side_effect=fake_request):
            self.assertEqual(submitter.prepare(), 0)
            self.assertEqual(submitter.submit(), 2)

        self.assertEqual(captured["posts"], 0)
        final = json.loads(submitter.EVIDENCE.read_text())
        self.assertEqual(final["status"], "pre_submit_failure")
        self.assertEqual(final["external_writes_performed"], [])

    def test_prepare_refuses_expired_authorization(self) -> None:
        value = json.loads(self.auth.read_text())
        value["expires_at"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        self.auth.write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "expired"):
            submitter.prepare()


if __name__ == "__main__":
    unittest.main()
