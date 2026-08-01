import os
import unittest
from unittest.mock import patch

import taskmarket_execution_filter as execution_filter


def candidate(**overrides):
    value = {
        "task_id": "0x" + "a" * 64,
        "title": "Clean a small CSV file",
        "description_excerpt": "Use Python and pandas and submit one CSV.",
        "tags": ["python", "csv"],
        "zero_spend_candidate": True,
        "submission_count": 1,
        "capability_matches": ["code", "research"],
        "net_reward_usdc": 4.625,
        "reward_usdc": 5.0,
        "hours_left": 24.0,
    }
    value.update(overrides)
    return value


class TaskmarketExecutionFilterTests(unittest.TestCase):
    def test_route_is_unavailable_without_wallet_signer_and_client(self):
        with patch.dict(os.environ, {}, clear=True):
            route = execution_filter.route_state()
        self.assertEqual(
            route,
            {
                "worker_wallet_configured": False,
                "eip191_signer_available": False,
                "submission_client_available": False,
            },
        )
        reasons = execution_filter.execution_reasons(candidate(), route)
        self.assertIn("worker_wallet_not_configured", reasons)
        self.assertIn("eip191_signer_unavailable", reasons)
        self.assertIn("authenticated_submission_client_unavailable", reasons)

    def test_low_competition_code_task_is_ready_when_route_is_configured(self):
        route = {
            "worker_wallet_configured": True,
            "eip191_signer_available": True,
            "submission_client_available": True,
        }
        self.assertEqual(execution_filter.execution_reasons(candidate(), route), [])

    def test_high_competition_image_contest_is_not_execution_ready(self):
        route = {
            "worker_wallet_configured": True,
            "eip191_signer_available": True,
            "submission_client_available": True,
        }
        reasons = execution_filter.execution_reasons(
            candidate(
                title="Make one still image as a polished data-plate",
                description_excerpt="Design a 1:1 still image for a visual contest.",
                capability_matches=["research", "design"],
                submission_count=26,
            ),
            route,
        )
        self.assertIn("high_competition_at_least_10_submissions", reasons)
        self.assertIn("subjective_image_or_design_contest", reasons)

    def test_expiring_task_is_rejected(self):
        route = {
            "worker_wallet_configured": True,
            "eip191_signer_available": True,
            "submission_client_available": True,
        }
        reasons = execution_filter.execution_reasons(candidate(hours_left=1.5), route)
        self.assertIn("insufficient_or_unknown_time_remaining", reasons)


if __name__ == "__main__":
    unittest.main()
