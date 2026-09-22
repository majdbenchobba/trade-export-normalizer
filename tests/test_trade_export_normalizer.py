import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from trade_export_normalizer import (  # noqa: E402
    map_chart_symbol,
    normalize_bybit_export,
    normalize_columns,
    normalize_exness_file,
)


class TradeExportNormalizerTest(unittest.TestCase):
    def test_normalize_columns(self):
        frame = pd.DataFrame(columns=[" Opening Time (UTC) ", "Original Position Size"])
        self.assertEqual(
            list(normalize_columns(frame).columns),
            ["opening_time_utc", "original_position_size"],
        )

    def test_chart_symbol_mapping(self):
        self.assertEqual(map_chart_symbol("BTCUSD"), ("binance", "BTCUSDT"))
        self.assertEqual(map_chart_symbol("SOLUSDT"), ("binance", "SOLUSDT"))
        self.assertEqual(map_chart_symbol("UNKNOWN"), (None, None))

    def test_normalize_synthetic_exness_export(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "demo.csv"
            pd.DataFrame(
                [
                    {
                        "Symbol": "BTCUSD",
                        "Type": "buy",
                        "Opening Time (UTC)": "2026-01-01 10:00:00",
                        "Closing Time (UTC)": "2026-01-01 11:00:00",
                        "Opening Price": 90000,
                        "Closing Price": 90500,
                        "Original Position Size": 0.01,
                        "Commission USD": -0.5,
                        "Profit USD": 5.0,
                    }
                ]
            ).to_csv(path, index=False)

            result = normalize_exness_file(path, "demo")

        self.assertEqual(len(result), 1)
        self.assertEqual(result.iloc[0]["exchange"], "exness_demo")
        self.assertEqual(result.iloc[0]["side"], "LONG")
        self.assertEqual(result.iloc[0]["chart_symbol"], "BTCUSDT")
        self.assertEqual(result.iloc[0]["pnl"], 5.0)

    def test_normalize_synthetic_bybit_round_trip(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "demo.csv"
            pd.DataFrame(
                [
                    {
                        "Symbol": "ETHUSDT",
                        "Side": "Buy",
                        "Order Time": "2026-01-01 10:00:00",
                        "Avg Price": 3000,
                        "Closed Size": 0.1,
                        "Fee": 0.1,
                        "Closed PnL": "",
                    },
                    {
                        "Symbol": "ETHUSDT",
                        "Side": "Sell",
                        "Order Time": "2026-01-01 11:00:00",
                        "Avg Price": 3100,
                        "Closed Size": 0.1,
                        "Fee": 0.1,
                        "Closed PnL": 10.0,
                    },
                ]
            ).to_csv(path, index=False)

            result = normalize_bybit_export(path)

        self.assertEqual(len(result), 1)
        self.assertEqual(result.iloc[0]["side"], "LONG")
        self.assertEqual(result.iloc[0]["chart_symbol"], "ETHUSDT")
        self.assertEqual(result.iloc[0]["entry_price"], 3000)
        self.assertEqual(result.iloc[0]["exit_price"], 3100)


if __name__ == "__main__":
    unittest.main()
