import unittest

import sanitize_market_output as sanitizer


class MarketOutputSanitizerTests(unittest.TestCase):
    def test_redacts_payment_and_contact_fields_recursively(self):
        value = {
            "stripeSessionId": "cs_live_example123456789",
            "nested": {
                "paypalOrderId": "ORDER-123",
                "email": "person@example.com",
                "safe": 1,
            },
        }
        clean = sanitizer.sanitize(value)
        self.assertEqual(clean["stripeSessionId"], "[REDACTED]")
        self.assertEqual(clean["nested"]["paypalOrderId"], "[REDACTED]")
        self.assertEqual(clean["nested"]["email"], "[REDACTED]")
        self.assertEqual(clean["nested"]["safe"], 1)
        self.assertEqual(sanitizer.find_credentials(clean), [])

    def test_strips_secret_url_query_values_and_fragments(self):
        url = "https://example.com/path?token=secret&status=open#fragment"
        clean = sanitizer.sanitize_url(url)
        self.assertIn("token=%5BREDACTED%5D", clean)
        self.assertIn("status=open", clean)
        self.assertNotIn("secret", clean)
        self.assertNotIn("fragment", clean)

    def test_finds_credential_pattern_in_unexpected_value(self):
        value = {"unexpected": "cs_live_abcdefghijklmnop"}
        self.assertEqual(sanitizer.find_credentials(value), ["$.unexpected"])

    def test_preserves_normal_github_and_marketplace_urls(self):
        value = {
            "issue": "https://github.com/acme/repo/issues/1",
            "market": "https://api.example.com/bounties?status=open",
        }
        clean = sanitizer.sanitize(value)
        self.assertEqual(clean["issue"], value["issue"])
        self.assertEqual(clean["market"], value["market"])


if __name__ == "__main__":
    unittest.main()
