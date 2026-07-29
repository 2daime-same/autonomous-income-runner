import unittest

import bountyhub_selector as selector


def base_item(**overrides):
    item = {
        "title": "Fix duplicate pagination fallback",
        "body": "Add a unit test and fix the duplicate fallback edge case.",
        "additionalDescription": "",
        "amount": "25.00",
        "totalAmount": "25.00",
        "paymentStatus": "PAID",
        "issueState": "open",
        "claimed": False,
        "solved": False,
        "retracted": False,
        "isFrozen": False,
        "assignee": None,
        "assignmentType": "open",
        "repositoryFullName": "trusted/project",
        "issueNumber": 12,
        "language": "Python",
    }
    item.update(overrides)
    return item


class BountyHubSelectorTests(unittest.TestCase):
    def test_accepts_paid_open_unclaimed_software_task(self):
        self.assertEqual(selector.base_exclusions(base_item()), [])

    def test_rejects_promised_not_paid(self):
        reasons = selector.base_exclusions(base_item(paymentStatus="PROMISED"))
        self.assertIn("not escrow-paid: PROMISED", reasons)

    def test_rejects_physical_mobile_flow(self):
        reasons = selector.base_exclusions(
            base_item(body="Test SMS verification on an Android device")
        )
        self.assertTrue(any("physical device" in reason for reason in reasons))

    def test_rejects_adult_project(self):
        reasons = selector.base_exclusions(base_item(title="Add lewd sprites"))
        self.assertIn("adult or sexual-content project", reasons)

    def test_detects_competing_attempt_comment(self):
        comments = [
            {
                "user": {"login": "solver"},
                "body": "I am working on this issue and opened PR #9",
            }
        ]
        attempts = selector.comment_attempts(comments)
        self.assertEqual(attempts[0]["login"], "solver")

    def test_small_scope_scores_above_large_cross_platform_feature(self):
        repo = {"stargazers_count": 200, "language": "Python"}
        small_score, _ = selector.candidate_score(base_item(), repo, [], [])
        large_score, _ = selector.candidate_score(
            base_item(body="Implement across desktop and mobile as a full rewrite"),
            repo,
            [],
            [],
        )
        self.assertGreater(small_score, large_score)


if __name__ == "__main__":
    unittest.main()
