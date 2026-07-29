from pathlib import Path
import json
import os
import tempfile
import unittest
from unittest.mock import patch

import clawgig_runner as runner


class ClawGigRunnerTests(unittest.TestCase):
    def test_sanitize_redacts_nested_credentials_and_codes(self):
        value = {
            "api_key": "cg_secret",
            "nested": {"claim_url": "https://example.test/claim", "code": "123456"},
        }
        clean = runner.sanitize(value)
        self.assertEqual(clean["api_key"], "[REDACTED]")
        self.assertEqual(clean["nested"]["claim_url"], "[REDACTED]")
        self.assertEqual(clean["nested"]["code"], "[REDACTED_CODE]")

    def test_atomic_write_json_roundtrip(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "state.json"
            runner.atomic_write_json(path, {"a": 1}, mode=0o600)
            self.assertEqual(json.loads(path.read_text()), {"a": 1})
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_registration_payload_requires_complete_profile(self):
        with self.assertRaises(runner.RunnerError):
            runner.registration_payload({"profile": {"name": "Agent"}})

    def test_proposal_payload_validation(self):
        payload = runner.proposal_payload(
            {
                "gig_id": "gig",
                "cover_letter": "I can deliver a tested report and source package.",
                "proposed_amount_usdc": 5,
                "estimated_hours": 2,
            }
        )
        self.assertEqual(payload["proposed_amount_usdc"], 5.0)
        self.assertEqual(payload["estimated_hours"], 2.0)

    def test_registration_disables_retry(self):
        response = runner.HttpResponse(
            201,
            {
                "agent_id": "agent",
                "api_key": "cg_test",
                "claim_token": "claim",
                "claim_url": "https://clawgig.ai/dashboard/agents/claim/claim",
            },
        )
        request = {
            "profile": {
                "name": "Agent",
                "username": "agent-name",
                "description": "A sufficiently long description for the agent.",
                "skills": ["python"],
                "categories": ["code"],
                "webhook_url": "https://example.com/webhook",
                "avatar_url": "https://example.com/avatar.svg",
                "contact_email": "agent@example.com",
                "languages": ["English"],
            }
        }
        with tempfile.TemporaryDirectory() as temp:
            state_file = Path(temp) / "state.json"
            with patch.object(runner, "STATE_FILE", state_file), patch.object(
                runner, "http_json", return_value=response
            ) as mocked:
                state, created = runner.register_if_needed(request)
        self.assertTrue(created)
        self.assertEqual(state["api_key"], "cg_test")
        self.assertEqual(mocked.call_args.kwargs["retries"], 0)

    def test_confirm_requires_six_digit_code(self):
        with patch.dict(os.environ, {"CLAWGIG_VERIFY_CODE": "abc"}, clear=False):
            with self.assertRaises(runner.RunnerError):
                runner.confirm_verification({"api_key": "cg_test"})

    def test_list_gigs_builds_bounded_query(self):
        response = runner.HttpResponse(200, {"data": []})
        with patch.object(runner, "http_json", return_value=response) as mocked:
            runner.list_gigs(
                {"api_key": "cg_test"},
                {"gigs": {"limit": 999, "sort": "budget_low", "min_budget": 1}},
            )
        path = mocked.call_args.args[1]
        self.assertIn("limit=50", path)
        self.assertIn("sort=budget_low", path)
        self.assertIn("min_budget=1.0", path)


if __name__ == "__main__":
    unittest.main()
