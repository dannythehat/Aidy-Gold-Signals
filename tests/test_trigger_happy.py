"""Adversarial synthetic fixture checks; NOT historical profitability evidence."""
from __future__ import annotations

import unittest

from research.strategy_lab.trigger_happy.backtest import Config, Quote, simulate


def q(ms: int, bid: float, ask: float) -> Quote:
    return Quote(ms * 1000, bid, ask)


class TriggerHappyPrototypeTests(unittest.TestCase):
    def test_long_three_independent_tps(self):
        tape = [q(0, 99.9, 100.1), q(1000, 102.9, 103.1),
                q(1250, 103.0, 103.2),
                q(2000, 105.3, 105.5), q(3000, 107.3, 107.5),
                q(4000, 111.3, 111.5)]
        result = simulate(tape)
        self.assertEqual(result["summary"]["signals"], 1)
        self.assertEqual(result["summary"]["closed_legs"], 3)
        self.assertEqual([leg["exit_reason"] for leg in result["closed_legs"]],
                         ["TP", "TP", "TP"])
        self.assertAlmostEqual(result["summary"]["closed_net_pnl_usd_model"], 14)
        self.assertEqual(result["summary"]["open_legs"], 0)
        self.assertEqual(result["signals"][0]["entry_us"], 1250000)

    def test_gap_stop_uses_worse_bid_not_perfect_stop(self):
        result = simulate([q(0, 99.9, 100.1), q(1000, 102.9, 103.1),
                           q(1250, 103.0, 103.2), q(1400, 99.0, 99.2)])
        self.assertEqual(result["summary"]["closed_legs"], 3)
        self.assertTrue(all(leg["exit_reason"] == "STOP"
                            for leg in result["closed_legs"]))
        self.assertTrue(all(leg["exit"] == 99.0 for leg in result["closed_legs"]))
        self.assertAlmostEqual(result["summary"]["closed_net_pnl_usd_model"], -12.6)

    def test_short_direction_and_three_tps(self):
        tape = [q(0, 100.0, 100.2), q(1000, 97.0, 97.2),
                q(1250, 96.9, 97.1), q(2000, 94.7, 94.8),
                q(3000, 92.7, 92.8), q(4000, 88.7, 88.8)]
        result = simulate(tape)
        self.assertEqual(result["signals"][0]["direction"], "SHORT")
        self.assertEqual([leg["exit_reason"] for leg in result["closed_legs"]],
                         ["TP", "TP", "TP"])
        self.assertAlmostEqual(result["summary"]["closed_net_pnl_usd_model"], 14)

    def test_spread_only_change_not_mistaken_for_price_jump(self):
        result = simulate([q(0, 99.9, 100.1), q(500, 99.0, 101.0),
                           q(1000, 99.9, 100.1)])
        self.assertEqual(result["summary"]["signals"], 0)
        self.assertEqual(result["summary"]["ineligible_spread_quotes"], 1)

    def test_delayed_fill_never_on_trigger_quote(self):
        result = simulate([q(0, 99.9, 100.1), q(1000, 102.9, 103.1),
                           q(1100, 104.9, 105.1), q(1250, 105.9, 106.1)])
        self.assertEqual(result["signals"][0]["entry_us"], 1250000)
        self.assertAlmostEqual(result["signals"][0]["entry_price"], 106.1)
        self.assertEqual(result["summary"]["closed_legs"], 0)
        self.assertEqual(result["summary"]["open_legs"], 3)

    def test_price_rise_just_under_threshold_no_signal(self):
        result = simulate([q(0, 99.9, 100.1), q(1000, 102.8, 103.0)])
        self.assertEqual(result["summary"]["signals"], 0)

    def test_reject_unsorted_source(self):
        with self.assertRaisesRegex(ValueError, "Nonchronological"):
            simulate([q(1000, 99.9, 100.1), q(999, 100.0, 100.2)])

    def test_unfilled_is_not_fictional_trade(self):
        result = simulate([q(0, 99.9, 100.1), q(1000, 102.9, 103.1)])
        self.assertEqual(result["summary"]["signals"], 1)
        self.assertEqual(result["summary"]["filled_signals"], 0)
        self.assertEqual(result["signals"][0]["status"], "unfilled_at_data_end")

    def test_high_spread_at_entry_cancels(self):
        result = simulate([q(0, 99.9, 100.1), q(1000, 102.9, 103.1),
                           q(1250, 102.5, 103.5)])
        self.assertEqual(result["summary"]["filled_signals"], 0)
        self.assertEqual(result["summary"]["canceled_entries"], 1)

    def test_fee_deducted_for_each_leg(self):
        result = simulate([q(0, 99.9, 100.1), q(1000, 102.9, 103.1),
                           q(1250, 103.0, 103.2), q(2000, 111.3, 111.5)],
                          Config(roundtrip_fee_usd_per_lot=10))
        self.assertEqual(result["summary"]["closed_legs"], 3)
        self.assertAlmostEqual(result["summary"]["closed_net_pnl_usd_model"], 13.7)


if __name__ == "__main__":
    unittest.main()
