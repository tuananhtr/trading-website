"""Exit timing and P&L regressions for the S2 MACD strategy."""
import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backtest import BUY_FEE, SELL_FEE, SELL_TAX, run_backtest
from strategy import compute_indicators, detect_macd_cross_down, prepare_sell_signals


class S2ExitTests(unittest.TestCase):
    def bars(self):
        frame = pd.DataFrame({
            "open": 20_000.0, "high": 21_000.0, "low": 19_000.0,
            "close": 20_500.0, "buy_signal": False,
            "macd": 2.0, "macd_signal": 1.0,
        }, index=pd.date_range("2024-01-01", periods=210, name="date"))
        frame.loc[frame.index[200], "buy_signal"] = True
        return frame

    def cross(self, frame, bar=203):
        frame.loc[frame.index[bar:], "macd"] = 0.5

    def trade(self, frame, **kwargs):
        return run_backtest(frame, "TEST", strategy=2, **kwargs)["trades"][0]

    def test_cross_fills_next_open_and_recalculates_net_pnl(self):
        frame = self.bars()
        self.cross(frame)
        frame.loc[frame.index[204], "open"] = 22_000.0
        trade = self.trade(frame)
        self.assertFalse(trade["is_active"])
        self.assertEqual(trade["exit_reason"], "MACD Cross Down")
        self.assertEqual(trade["exit_date"], frame.index[204].strftime("%Y-%m-%d"))
        self.assertEqual(trade["exit_price"], 22_000.0)
        self.assertEqual(trade["days_held"], 3)
        expected = trade["shares"] * (22_000 * (1 - SELL_FEE - SELL_TAX) - 20_000 * (1 + BUY_FEE))
        self.assertEqual(trade["net_pnl_vnd"], round(expected, 0))

    def test_no_cross_stays_active_at_latest_close(self):
        trade = self.trade(self.bars())
        self.assertTrue(trade["is_active"])
        self.assertEqual(trade["exit_price"], 20_500)

    def test_final_bar_cross_has_no_execution_bar(self):
        frame = self.bars()
        self.cross(frame, 209)
        self.assertTrue(self.trade(frame)["is_active"])

    def test_cross_on_entry_bar_is_honored(self):
        frame = self.bars()
        self.cross(frame, 201)
        trade = self.trade(frame)
        self.assertEqual(trade["exit_date"], frame.index[202].strftime("%Y-%m-%d"))

    def test_cross_from_equality_is_honored(self):
        frame = self.bars()
        frame.loc[frame.index[202], "macd"] = 1.0
        self.cross(frame)
        self.assertEqual(self.trade(frame)["exit_reason"], "MACD Cross Down")

    def test_stop_before_cross_wins(self):
        frame = self.bars()
        self.cross(frame)
        frame.loc[frame.index[202], "low"] = 17_000.0
        self.assertEqual(self.trade(frame, cut_loss_pct=0.1)["exit_reason"], "Stop-Loss (10%)")

    def test_later_stop_does_not_override_macd_exit(self):
        frame = self.bars()
        self.cross(frame)
        frame.loc[frame.index[206], "low"] = 17_000.0
        self.assertEqual(self.trade(frame, cut_loss_pct=0.1)["exit_reason"], "MACD Cross Down")

    def test_intrabar_stop_on_cross_bar_wins(self):
        frame = self.bars()
        self.cross(frame)
        frame.loc[frame.index[203], "low"] = 17_000.0
        self.assertEqual(self.trade(frame, cut_loss_pct=0.1)["exit_reason"], "Stop-Loss (10%)")

    def test_s1_does_not_exit_on_macd_cross_down(self):
        frame = self.bars()
        self.cross(frame)
        trade = run_backtest(frame, "TEST", strategy=1)["trades"][0]
        self.assertTrue(trade["is_active"])

    def test_chart_sell_signal_precedes_execution_date(self):
        frame = self.bars()
        self.cross(frame)
        frame["sell_signal"] = detect_macd_cross_down(frame)
        signals = prepare_sell_signals(frame)
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0]["time"], int(frame.index[203].timestamp()))
        trade = self.trade(frame)
        self.assertEqual(trade["exit_date"], frame.index[204].strftime("%Y-%m-%d"))

    def test_final_bar_sell_signal_is_displayed_while_trade_is_active(self):
        frame = self.bars()
        self.cross(frame, 209)
        frame["sell_signal"] = detect_macd_cross_down(frame)
        signals = prepare_sell_signals(frame)
        self.assertEqual(signals[0]["time"], int(frame.index[-1].timestamp()))
        self.assertTrue(self.trade(frame)["is_active"])

    def test_s1_has_no_sell_markers(self):
        frame = compute_indicators(self.bars(), strategy=1)
        self.assertEqual(prepare_sell_signals(frame), [])


if __name__ == "__main__":
    unittest.main()
