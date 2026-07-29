from datetime import datetime, timezone
import unittest

import market_probe


class MarketProbeTests(unittest.TestCase):
    def test_token_amount(self):
        self.assertEqual(
            market_probe.token_amount({"amount": "2000000", "decimals": 6}),
            2.0,
        )

    def test_zero_cost_claimable_candidate(self):
        item = {
            "opportunity_id": "candidate",
            "source_id": "0x" + "1" * 40,
            "source_status": "claimable",
            "work_state": "claimable",
            "payment_state": "escrowed",
            "payment_committed": True,
            "verification_ready": True,
            "verification_method": "deterministic_module",
            "reward": {"amount": "100000", "decimals": 6},
            "bond": {"amount": "0", "decimals": 6},
            "deadline": "2030-01-01T00:00:00+00:00",
            "title": "Write a bounded technical report",
            "goal": "Deliver a JSON report",
            "evidence_requirements": {"required": ["artifact_reference"]},
        }
        result = market_probe.compact_agent_bounty(
            item, datetime.now(timezone.utc)
        )
        self.assertTrue(result["claimable_paid_candidate"])
        self.assertTrue(result["zero_cost_candidate"])

    def test_child_bounty_is_not_zero_cost(self):
        item = {
            "opportunity_id": "meta",
            "source_id": "0x" + "2" * 40,
            "source_status": "claimable",
            "work_state": "claimable",
            "payment_state": "escrowed",
            "payment_committed": True,
            "verification_ready": True,
            "reward": {"amount": "2000000", "decimals": 6},
            "bond": {"amount": "10000", "decimals": 6},
            "deadline": "2030-01-01T00:00:00+00:00",
            "title": "Create a child bounty",
            "goal": "Create and fully fund a 1 USDC child bounty",
            "evidence_requirements": {"required": ["child_bounty_contract"]},
        }
        result = market_probe.compact_agent_bounty(
            item, datetime.now(timezone.utc)
        )
        self.assertTrue(result["claimable_paid_candidate"])
        self.assertTrue(result["detected_child_funding"])
        self.assertFalse(result["zero_cost_candidate"])
        self.assertFalse(result["low_cost_candidate"])

    def test_expired_item_is_not_claimable(self):
        item = {
            "source_status": "claimable",
            "work_state": "claimable",
            "payment_state": "escrowed",
            "payment_committed": True,
            "verification_ready": True,
            "deadline": "2020-01-01T00:00:00+00:00",
            "title": "Expired",
            "goal": "Do work",
        }
        result = market_probe.compact_agent_bounty(
            item, datetime.now(timezone.utc)
        )
        self.assertFalse(result["claimable_paid_candidate"])

    def test_generic_unwrap(self):
        self.assertEqual(market_probe.unwrap_list({"jobs": [{"id": 1}]}), [{"id": 1}])


if __name__ == "__main__":
    unittest.main()
