"""Grid method must reproduce original Trigger Happy frozen engine exactly."""
from __future__ import annotations

import unittest
import numpy as np

from research.strategy_lab.trigger_happy.backtest import Config, Quote, simulate
from research.strategy_lab.trigger_happy.grid_sweep import replay, run_grid


class GridParity(unittest.TestCase):
    def compare_tape(self, tape: list[Quote], latency: int = 200) -> None:
        original = simulate(tape, Config(latency_ms=latency))
        arr = replay(np.array([q.ts_us for q in tape], dtype=np.int64),
                     np.array([q.bid for q in tape], dtype=np.float64),
                     np.array([q.ask for q in tape], dtype=np.float64),
                     1_500_000, 3., latency * 1_000)
        self.assertEqual(int(arr[0]), original["summary"]["signals"])
        self.assertEqual(int(arr[1]), original["summary"]["filled_signals"])
        self.assertEqual(int(arr[2]), original["summary"]["canceled_entries"])
        self.assertEqual(int(arr[3]), sum(x["exit_reason"] == "TP" for x in original["closed_legs"]))
        self.assertEqual(int(arr[4]), sum(x["exit_reason"] == "STOP" for x in original["closed_legs"]))
        self.assertEqual(int(arr[5]), sum(x["exit_reason"] == "TIME" for x in original["closed_legs"]))
        self.assertEqual(int(arr[6]), original["summary"]["closed_legs"])
        self.assertAlmostEqual(arr[7], original["summary"]["closed_net_pnl_usd_model"], places=4)
        self.assertEqual(int(arr[10]), sum(x["status"] == "filled" and x["direction"] == "LONG"
                                        for x in original["signals"]))
        self.assertEqual(int(arr[11]), sum(x["status"] == "filled" and x["direction"] == "SHORT"
                                        for x in original["signals"]))

    def test_three_tps_buy(self):
        self.compare_tape([Quote(t*1000, b, a) for t, b, a in (
            (0, 99.9, 100.1), (1000, 102.9, 103.1), (1250, 103.0, 103.2),
            (2000, 105.3, 105.5), (3000, 107.3, 107.5), (4000, 111.3, 111.5))])

    def test_gap_stop(self):
        self.compare_tape([Quote(t*1000, b, a) for t, b, a in (
            (0, 99.9, 100.1), (1000, 102.9, 103.1), (1250, 103.0, 103.2),
            (1400, 99.0, 99.2))])

    def test_sell_with_gap_and_rearm_and_spread(self):
        # Two separate bursts, a width-induced history reset and time expiry.
        data = [(0, 104., 104.2), (700, 100.8, 101.),
                (1100, 100.8, 101.), (1450, 105.5, 105.7),
                (2200, 99., 101.), (15000, 100., 100.2),
                (15200, 103.3, 103.5), (15500, 103.2, 103.4),
                (316000, 104., 104.2), (320000, 100., 100.2)]
        self.compare_tape([Quote(t * 1000, b, a) for t,b,a in data])

    def test_seeded_uneven_tick_sequence_replay_parity(self):
        gen = np.random.default_rng(20261030)
        t = 0
        price = 4000.
        tape = []
        for i in range(3000):
            t += int(gen.integers(1, 2000))
            price += float(gen.normal(0, .14) + (3.9 if i % 153 == 0
                        else (-3.7 if i % 117 == 0 else 0)))
            spread = .2 if i % 71 else 1.05
            tape.append(Quote(t*1000, price - spread/2., price + spread/2.))
        for latency in (50, 200, 500, 1000):
            self.compare_tape(tape, latency)

    def test_parameter_grid_and_fee(self):
        t = np.array([0, 1_000_000, 1_250_000, 2_000_000, 3_000_000,
                      4_000_000], dtype=np.int64)
        b = np.array([99.9, 102.9, 103., 105.3, 107.3, 111.3])
        a = b + .2
        v = run_grid(t, b, a, windows=(1500,), thresholds=(3., 5., 10.))
        self.assertEqual(len(v), 3)
        self.assertEqual(v[0]["filled_bundles"], 1)
        self.assertAlmostEqual(v[0]["fee10_model_net_usd"], 13.7)
        self.assertEqual(v[1]["filled_bundles"], 0)


if __name__ == "__main__":
    unittest.main()
