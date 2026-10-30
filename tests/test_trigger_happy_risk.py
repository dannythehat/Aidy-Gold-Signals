"""Research-only guardrails for configurable Trigger Happy risk sweeps."""
import unittest

import numpy as np

from research.strategy_lab.trigger_happy.grid_sweep import replay
from research.strategy_lab.trigger_happy.risk_sweep import RISK_PROFILES, run_sweep


class RiskSweepTests(unittest.TestCase):
    def test_up_shock_follow_vs_fade_opposite_fill(self):
        ts = np.array([0, 1_000_000, 1_250_000, 2_000_000], dtype=np.int64)
        bid = np.array([99.9, 102.9, 103.0, 99.0])
        ask = bid + .2
        follow = replay(ts, bid, ask, 1_500_000, 3., 200_000, 2., 2., 4., 8.,
                        300_000_000, .8, 1)
        fade = replay(ts, bid, ask, 1_500_000, 3., 200_000, 2., 2., 4., 8.,
                      300_000_000, .8, -1)
        self.assertEqual(int(follow[0]), 1)
        self.assertEqual(int(fade[0]), 1)
        self.assertEqual(int(follow[4]), 3)
        self.assertEqual(int(fade[3]), 1)
        self.assertLess(follow[7], 0)
        self.assertGreater(fade[7], 0)

    def test_variable_targets_and_stop(self):
        ts = np.array([0, 1_000_000, 1_250_000, 2_000_000,
                       3_000_000, 4_000_000], dtype=np.int64)
        b = np.array([99.9, 102.9, 103., 105.3, 107.3, 111.3])
        v = replay(ts, b, b + .2, 1_500_000, 3., 200_000, 3.,
                   2., 4., 8., 300_000_000, .8, 1)
        self.assertEqual(int(v[3]), 3)
        self.assertAlmostEqual(v[7], 14.)

    def test_grid_complete_on_mini_tape(self):
        ts = np.array([0, 1_000_000, 1_250_000, 3_000_000], dtype=np.int64)
        bid = np.array([99.9, 102.9, 103., 104.])
        got = run_sweep(ts, bid, bid + .2)
        self.assertEqual(len(got), 540)
        self.assertEqual(len(RISK_PROFILES), 10)
        self.assertTrue(all(x["broker_execution_verified"] is False for x in got))


if __name__ == "__main__":
    unittest.main()
