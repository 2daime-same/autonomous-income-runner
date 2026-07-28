from pathlib import Path
import json
import os
import tempfile
import unittest
from unittest.mock import patch

import runner


class RunnerTests(unittest.TestCase):
    def test_sanitize_redacts_nested_secrets(self):
        value = {
            "apiKey": "sk_test",
            "nested": [{"claimCode": "ABC", "access_token": "secret", "ok": 1}],
        }
        clean = runner.sanitize(value)
        self.assertEqual(clean["apiKey"], "[REDACTED]")
        self.assertEqual(clean["nested"][0]["claimCode"], "[REDACTED]")
        self.assertEqual(clean["nested"][0]["access_token"], "[REDACTED]")

    def test_atomic_write_json_roundtrip(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "state.json"
            runner.atomic_write_json(path, {"a": 1}, mode=0o600)
            self.assertEqual(json.loads(path.read_text()), {"a": 1})
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_stable_agent_name(self):
        with patch.dict(os.environ, {"GITHUB_REPOSITORY": "owner/private-runner"}):
            first = runner.stable_agent_name({"agentName": "Agent"})
            second = runner.stable_agent_name({"agentName": "Agent"})
        self.assertEqual(first, second)
        self.assertTrue(first.startswith("Agent-"))

    def test_submission_rejects_missing_content_before_network(self):
        with self.assertRaises(runner.RunnerError):
            runner.submission_payload({"submission": {"listingId": "id"}})

    def test_submission_accepts_link_without_other_info(self):
        payload = runner.submission_payload(
            {"submission": {"listingId": "id", "link": "https://example.com"}}
        )
        self.assertEqual(payload["listingId"], "id")
        self.assertEqual(payload["link"], "https://example.com")

    def test_comment_rejects_missing_fields_before_network(self):
        with self.assertRaises(runner.RunnerError):
            runner.operation_comment_create({"comment": {}}, {"apiKey": "sk_test"})

    def test_list_builds_bounded_query(self):
        response = runner.HttpResponse(200, {"items": []})
        with patch.object(runner, "http_json", return_value=response) as mocked:
            result = runner.operation_list(
                {"list": {"take": 999, "deadline": "2026-12-31"}},
                {"apiKey": "sk_test"},
            )
        self.assertEqual(result["httpStatus"], 200)
        path = mocked.call_args.args[1]
        self.assertIn("take=100", path)
        self.assertIn("deadline=2026-12-31", path)

    def test_registration_disables_retry(self):
        response = runner.HttpResponse(
            201,
            {
                "apiKey": "sk_test",
                "claimCode": "CLAIM",
                "agentId": "agent",
                "username": "agent-name",
            },
        )
        with tempfile.TemporaryDirectory() as temp:
            state_file = Path(temp) / "state.json"
            with patch.object(runner, "STATE_FILE", state_file), patch.object(
                runner, "http_json", return_value=response
            ) as mocked:
                runner.register_if_needed({"agentName": "Agent"})
        self.assertEqual(mocked.call_args.kwargs["retries"], 0)


if __name__ == "__main__":
    unittest.main()
