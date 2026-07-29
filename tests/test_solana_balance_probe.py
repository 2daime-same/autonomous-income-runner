from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import solana_balance_probe as probe


class SolanaBalanceProbeTests(unittest.TestCase):
    def test_stable_view_excludes_observation_metadata(self):
        value = {
            "network": "solana-mainnet",
            "wallet": "wallet",
            "lamports": 10,
            "sol": "0.000000010",
            "usdc_mint": probe.USDC_MAINNET_MINT,
            "usdc_raw": "1",
            "usdc": "0.000001",
            "positive_token_accounts": [],
            "first_observed_or_changed_at": "time-a",
            "rpc_url": "rpc-a",
        }
        other = dict(value)
        other["first_observed_or_changed_at"] = "time-b"
        other["rpc_url"] = "rpc-b"
        self.assertEqual(probe.stable_view(value), probe.stable_view(other))

    def test_main_writes_only_when_balance_changes(self):
        first = {
            "network": "solana-mainnet",
            "wallet": "wallet",
            "lamports": 0,
            "sol": "0.000000000",
            "usdc_mint": probe.USDC_MAINNET_MINT,
            "usdc_raw": "0",
            "usdc": "0.000000",
            "positive_token_accounts": [],
        }
        second = dict(first)
        second["usdc_raw"] = "10000"
        second["usdc"] = "0.010000"
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "balance.json"
            with patch.object(probe, "OUTPUT", output), patch.object(
                probe, "RPC_URLS", ["https://rpc.invalid"]
            ), patch.object(probe, "fetch_snapshot", return_value=dict(first)):
                self.assertEqual(probe.main(), 0)
                initial_text = output.read_text(encoding="utf-8")
                self.assertEqual(probe.main(), 0)
                self.assertEqual(initial_text, output.read_text(encoding="utf-8"))
            with patch.object(probe, "OUTPUT", output), patch.object(
                probe, "RPC_URLS", ["https://rpc.invalid"]
            ), patch.object(probe, "fetch_snapshot", return_value=dict(second)):
                self.assertEqual(probe.main(), 0)
                self.assertIn('"usdc": "0.010000"', output.read_text(encoding="utf-8"))

    def test_positive_usdc_accounts_are_summed(self):
        responses = {
            "getBalance": {"value": 1_500_000_000},
            probe.TOKEN_PROGRAMS["spl-token"]: {
                "value": [
                    {
                        "pubkey": "account-a",
                        "account": {
                            "data": {
                                "parsed": {
                                    "info": {
                                        "mint": probe.USDC_MAINNET_MINT,
                                        "tokenAmount": {
                                            "amount": "25000",
                                            "decimals": 6,
                                            "uiAmountString": "0.025",
                                        },
                                    }
                                }
                            }
                        },
                    }
                ]
            },
            probe.TOKEN_PROGRAMS["token-2022"]: {"value": []},
        }

        def fake_rpc(url, method, params, request_id):
            if method == "getBalance":
                return responses[method]
            return responses[params[1]["programId"]]

        with patch.object(probe, "rpc_call", side_effect=fake_rpc):
            snapshot = probe.fetch_snapshot("https://rpc.invalid")
        self.assertEqual(snapshot["sol"], "1.500000000")
        self.assertEqual(snapshot["usdc"], "0.025000")
        self.assertEqual(len(snapshot["positive_token_accounts"]), 1)


if __name__ == "__main__":
    unittest.main()
