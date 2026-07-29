import unittest

import public_bounty_site_probe as probe


class PublicBountySiteProbeTests(unittest.TestCase):
    def test_extracts_github_issue_and_pull_urls(self):
        text = (
            'See https://github.com/acme/repo/issues/12 and '
            'https://github.com/acme/repo/pull/19.'
        )
        self.assertEqual(
            probe.github_urls(text),
            [
                "https://github.com/acme/repo/issues/12",
                "https://github.com/acme/repo/pull/19",
            ],
        )

    def test_script_urls_stay_on_allowlisted_origin(self):
        html = (
            '<script src="/_next/a.js"></script>'
            '<script src="https://gitwork.io/assets/b.js"></script>'
            '<script src="https://evil.example/x.js"></script>'
        )
        urls = probe.extract_script_urls(html, "https://gitwork.io/", "https://gitwork.io")
        self.assertEqual(
            urls,
            [
                "https://gitwork.io/_next/a.js",
                "https://gitwork.io/assets/b.js",
            ],
        )

    def test_extract_candidate_urls_normalizes_api_paths(self):
        text = "fetch('/api/bounties?status=open'); const issue='https://github.com/a/b/issues/3'"
        values = probe.extract_candidate_urls(text, "https://gitwork.io")
        self.assertIn("https://gitwork.io/api/bounties?status=open", values)
        self.assertTrue(any("github.com/a/b/issues/3" in value for value in values))

    def test_compact_response_does_not_publish_full_script(self):
        response = {
            "ok": True,
            "status": 200,
            "url": "https://example.com/a.js",
            "content_type": "application/javascript",
            "bytes_read": 10000,
            "json": None,
            "text": "x" * 7000 + " https://github.com/a/b/issues/1",
        }
        compact = probe.compact_response(response)
        self.assertLessEqual(len(compact["text_preview"]), 6000)
        self.assertEqual(compact["github_issue_urls"], ["https://github.com/a/b/issues/1"])


if __name__ == "__main__":
    unittest.main()
