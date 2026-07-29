from datetime import datetime, timezone
import unittest

import github_bounty_radar as radar


class GitHubBountyRadarTests(unittest.TestCase):
    def test_extract_amounts_handles_currency_formats(self):
        values = radar.extract_amounts(
            "$100 bounty", "Reward: 25 USDC", "£50", "not money 2026"
        )
        self.assertIn(100.0, values)
        self.assertIn(25.0, values)
        self.assertIn(50.0, values)
        self.assertNotIn(2026.0, values)

    def test_repo_from_issue(self):
        issue = {"repository_url": "https://api.github.com/repos/owner/repo"}
        self.assertEqual(radar.repo_from_issue(issue), "owner/repo")

    def test_reward_evidence_detects_attempt_and_bot(self):
        issue = {
            "title": "Fix parser",
            "body": "A paid task",
            "labels": [{"name": "💎 Bounty"}, {"name": "$75"}],
        }
        comments = [
            {
                "user": {"login": "algora-pbc[bot]"},
                "body": "## 💎 $75 bounty\nReceive payment after merge",
            },
            {"user": {"login": "solver"}, "body": "/attempt #12"},
        ]
        evidence = radar.reward_evidence(issue, comments)
        self.assertEqual(evidence["max_amount_usd"], 75.0)
        self.assertTrue(evidence["explicit_platform"])
        self.assertEqual(evidence["attempt_count"], 1)

    def test_final_score_prefers_no_competitor_active_repo(self):
        issue = {
            "state": "open",
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "comments": 2,
            "assignees": [],
        }
        evidence = {
            "max_amount_usd": 50.0,
            "explicit_platform": True,
            "funded_or_bounty_label": True,
            "attempt_count": 0,
            "reward_links_count": 0,
        }
        repo = {
            "pushed_at": datetime.now(timezone.utc).isoformat(),
            "archived": False,
        }
        score, reasons = radar.final_score(issue, evidence, repo, [])
        self.assertGreater(score, 70)
        self.assertIn("no open competing PR found", reasons)

    def test_final_score_penalizes_assignee_and_competitors(self):
        issue = {
            "state": "open",
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "comments": 20,
            "assignees": [{"login": "someone"}],
        }
        evidence = {
            "max_amount_usd": 20.0,
            "explicit_platform": False,
            "funded_or_bounty_label": True,
            "attempt_count": 3,
            "reward_links_count": 1,
        }
        repo = {
            "pushed_at": datetime.now(timezone.utc).isoformat(),
            "archived": False,
        }
        score, _ = radar.final_score(
            issue,
            evidence,
            repo,
            [{"url": "https://github.com/a/b/pull/1"}],
        )
        self.assertLess(score, 50)


if __name__ == "__main__":
    unittest.main()
