import unittest

import trusted_bounty_execution_filter as execution_filter


class TrustedBountyExecutionFilterTests(unittest.TestCase):
    def test_large_accessibility_api_scope_is_hard_excluded(self):
        item = {
            "title": "Integration with OS accessibility APIs",
            "body_excerpt": (
                "Explore accessibility API integration across Windows, Linux, and Mac "
                "with operating system agnostic grammar APIs."
            ),
        }
        reasons = execution_filter.hard_scope_exclusions(item)
        self.assertEqual(
            reasons,
            ["large or cross-platform scope is unsuitable for first-income execution"],
        )

    def test_small_focused_fix_has_no_scope_exclusion(self):
        item = {
            "title": "Fix duplicate pagination fallback",
            "body_excerpt": "Add a regression test and change one parser fallback.",
        }
        self.assertEqual(execution_filter.hard_scope_exclusions(item), [])

    def test_large_scope_penalty_remains_visible_in_score_evidence(self):
        score, reasons = execution_filter.scope_score(
            {
                "selector_score": 100,
                "title": "Cross-platform accessibility API",
                "body_excerpt": "Support all platforms and operating system integrations.",
                "repo_language": "Python",
                "reward_usd": 200,
            }
        )
        self.assertLess(score, 100)
        self.assertIn("large or cross-platform scope", reasons)


if __name__ == "__main__":
    unittest.main()
