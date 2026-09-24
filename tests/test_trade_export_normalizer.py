import sys
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from trade_export_normalizer import (  # noqa: E402
    main,
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
        self.assertAlmostEqual(result.iloc[0]["fees"], 0.2)

    def normalize_bybit_orders(self, orders):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "orders.csv"
            pd.DataFrame(
                [
                    {
                        "Symbol": "ETHUSDT",
                        "Side": side,
                        "Order Time": f"2026-01-01 {10 + index:02d}:00:00",
                        "Avg Price": price,
                        "Filled Quantity": qty,
                        "Fee": 0.1,
                    }
                    for index, (side, qty, price) in enumerate(orders)
                ]
            ).to_csv(path, index=False)
            return normalize_bybit_export(path)

    def test_partial_close_is_rejected_instead_of_closing_the_whole_position(self):
        with self.assertRaisesRegex(ValueError, "partial close"):
            self.normalize_bybit_orders(
                [("Buy", 10, 100), ("Sell", 4, 110), ("Sell", 6, 120)]
            )

    def test_scale_in_and_position_reversal_are_rejected(self):
        for orders, message in [
            ([("Buy", 2, 100), ("Buy", 3, 105), ("Sell", 5, 110)], "scale-in"),
            ([("Buy", 2, 100), ("Sell", 3, 105)], "position reversal"),
            ([("Sell", 2, 100), ("Buy", 1, 90)], "partial close"),
        ]:
            with self.subTest(orders=orders):
                with self.assertRaisesRegex(ValueError, message):
                    self.normalize_bybit_orders(orders)

    def test_unclosed_position_is_reported(self):
        with self.assertRaisesRegex(ValueError, "unclosed"):
            self.normalize_bybit_orders([("Buy", 2, 100)])

    def test_complete_long_and_short_round_trips_are_preserved(self):
        result = self.normalize_bybit_orders(
            [("Buy", 2, 100), ("Sell", 2, 110), ("Sell", 3, 120), ("Buy", 3, 105)]
        )
        self.assertEqual(list(result["side"]), ["LONG", "SHORT"])
        self.assertEqual(list(result["qty"]), [2, 3])
        self.assertEqual(list(result["exit_price"]), [110, 105])
        self.assertEqual(list(result["fees"]), [0.2, 0.2])

    def test_invalid_side_or_price_cannot_silently_drop_a_filled_order(self):
        for side, price in [("Unknown", 110), ("Sell", float("nan"))]:
            with self.subTest(side=side, price=price):
                with self.assertRaisesRegex(ValueError, "invalid filled order"):
                    self.normalize_bybit_orders([("Buy", 2, 100), (side, 2, price)])

    def test_rejected_input_does_not_overwrite_existing_output(self):
        with TemporaryDirectory() as directory:
            source = Path(directory) / "partial.csv"
            output = Path(directory) / "normalized.csv"
            source.write_text(
                "Symbol,Side,Order Time,Avg Price,Filled Quantity,Fee\n"
                "ETHUSDT,Buy,2026-01-01 10:00:00,100,10,0.1\n"
                "ETHUSDT,Sell,2026-01-01 11:00:00,110,4,0.1\n",
                encoding="utf-8",
            )
            output.write_text("existing verified output\n", encoding="utf-8")
            with patch.object(
                sys, "argv", ["normalizer", "bybit", "--input", str(source), "--output", str(output)]
            ), redirect_stdout(StringIO()) as console:
                self.assertEqual(main(), 1)
            self.assertIn("unsupported partial close", console.getvalue())
            self.assertEqual(output.read_text(encoding="utf-8"), "existing verified output\n")


if __name__ == "__main__":
    unittest.main()
