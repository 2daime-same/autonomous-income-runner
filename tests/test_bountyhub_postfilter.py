import unittest
from unittest.mock import patch

import bountyhub_postfilter as postfilter


def candidate(**overrides):
    value = {
        "repository": "trusted/project",
        "issue_number": 12,
        "title": "Fix duplicate pagination fallback",
        "scope_excerpt": "Add a focused unit test and fix one fallback edge case.",
        "additional_description": "",
        "exclusions": [],
    }
    value.update(overrides)
    return value


class BountyHubPostfilterTests(unittest.TestCase):
    def test_bot_is_ignored_and_vacated_claim_is_removed(self):
        comments = [
            {
                "user": {"login": "bountyhub-bot"},
                "body": "Claim this bounty by submitting a pull request.",
            },
            {
                "user": {"login": "alice"},
                "body": "/claim — I will work on implementing this feature.",
            },
            {
                "user": {"login": "bob"},
                "body": "Submitted a full desktop and mobile design package.",
            },
            {
                "user": {"login": "alice"},
                "body": "After reviewing the scope, I am vacating my claim.",
            },
        ]
        signals = postfilter.current_attempt_signals(comments)
        self.assertEqual([signal["login"] for signal in signals], ["bob"])

    @patch("bountyhub_postfilter.github.fetch_comments", return_value=[])
    def test_large_cross_platform_scope_is_excluded(self, _fetch_comments):
        data = {
            "actionable": [
                candidate(
                    additional_description=(
                        "To claim this bounty, this must be implemented across desktop and mobile"
                    )
                )
            ],
            "inspected": [],
        }
        result = postfilter.postfilter(data)
        self.assertEqual(result["actionable_count"], 0)
        reasons = result["postfilter"]["exclusions_applied"][0]["reasons"]
        self.assertTrue(any("large full-stack" in reason for reason in reasons))

    @patch(
        "bountyhub_postfilter.github.fetch_comments",
        return_value=[
            {
                "user": {"login": "solver"},
                "body": "I can take this on and opened PR #41.",
            }
        ],
    )
    def test_live_competing_work_is_excluded(self, _fetch_comments):
        data = {"actionable": [candidate()], "inspected": []}
        result = postfilter.postfilter(data)
        self.assertEqual(result["actionable_count"], 0)
        exclusion = result["postfilter"]["exclusions_applied"][0]
        self.assertEqual(exclusion["live_comment_competition"][0]["login"], "solver")

    @patch("bountyhub_postfilter.github.fetch_comments", return_value=[])
    def test_small_candidate_without_live_competition_is_kept(self, _fetch_comments):
        data = {"actionable": [candidate()], "inspected": [candidate()]}
        result = postfilter.postfilter(data)
        self.assertEqual(result["actionable_count"], 1)
        self.assertEqual(result["postfilter"]["excluded_count"], 0)

    @patch(
        "bountyhub_postfilter.github.fetch_comments",
        side_effect=RuntimeError("temporary validation failure"),
    )
    def test_comment_validation_failure_is_fail_closed(self, _fetch_comments):
        data = {"actionable": [candidate()], "inspected": []}
        result = postfilter.postfilter(data)
        self.assertEqual(result["actionable_count"], 0)
        reasons = result["postfilter"]["exclusions_applied"][0]["reasons"]
        self.assertTrue(any("validation failed" in reason for reason in reasons))


if __name__ == "__main__":
    unittest.main()
