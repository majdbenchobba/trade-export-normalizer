import argparse
import json
import math
import re
from pathlib import Path

import pandas as pd


OUTPUT_COLUMNS = [
    "exchange",
    "symbol",
    "chart_exchange",
    "chart_symbol",
    "side",
    "entry_time",
    "entry_price",
    "exit_time",
    "exit_price",
    "qty",
    "fees",
    "pnl",
]


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    normalized = []
    for col in df.columns:
        name = str(col).strip().lower()
        name = re.sub(r"[^a-z0-9]+", "_", name)
        name = re.sub(r"_+", "_", name).strip("_")
        normalized.append(name)
    df.columns = normalized
    return df


def map_chart_symbol(symbol: str) -> tuple[str | None, str | None]:
    symbol = str(symbol).upper()
    mappings = {
        "BTC": ("binance", "BTCUSDT"),
        "ETH": ("binance", "ETHUSDT"),
        "SOL": ("binance", "SOLUSDT"),
        "BNB": ("binance", "BNBUSDT"),
        "ADA": ("binance", "ADAUSDT"),
        "XAU": ("bybit", "XAUUSDT"),
    }

    for prefix, mapped in mappings.items():
        if symbol.startswith(prefix):
            return mapped

    if symbol.endswith("USDT"):
        return "binance", symbol

    return None, None


def first_present_column(df: pd.DataFrame, candidates: list[str]) -> str:
    for column in candidates:
        if column in df.columns:
            return column
    raise KeyError(f"Missing expected columns. Tried: {', '.join(candidates)}")


def normalize_exness_file(path: Path, account_tag: str) -> pd.DataFrame:
    df = normalize_columns(pd.read_csv(path))

    required = [
        "symbol",
        "type",
        "opening_time_utc",
        "closing_time_utc",
        "opening_price",
        "closing_price",
        "original_position_size",
    ]
    missing = [column for column in required if column not in df.columns]
    if missing:
        raise KeyError(f"{path.name} is missing required columns: {', '.join(missing)}")

    df["side"] = df["type"].map(
        {
            "buy": "LONG",
            "sell": "SHORT",
            "Buy": "LONG",
            "Sell": "SHORT",
        }
    )
    df["entry_time"] = pd.to_datetime(df["opening_time_utc"], errors="coerce")
    df["exit_time"] = pd.to_datetime(df["closing_time_utc"], errors="coerce")
    df["entry_price"] = pd.to_numeric(df["opening_price"], errors="coerce")
    df["exit_price"] = pd.to_numeric(df["closing_price"], errors="coerce")
    df["qty"] = pd.to_numeric(df["original_position_size"], errors="coerce")

    fee_columns = [col for col in df.columns if col.startswith("commission_") or col.startswith("swap_")]
    df["fees"] = df[fee_columns].sum(axis=1) if fee_columns else 0.0

    profit_columns = [col for col in df.columns if col.startswith("profit")]
    df["pnl"] = pd.to_numeric(df[profit_columns[0]], errors="coerce") if profit_columns else None

    chart_mapping = df["symbol"].apply(map_chart_symbol)
    df["chart_exchange"] = chart_mapping.apply(lambda value: value[0])
    df["chart_symbol"] = chart_mapping.apply(lambda value: value[1])
    df["exchange"] = f"exness_{account_tag}"

    out = df[
        [
            "exchange",
            "symbol",
            "chart_exchange",
            "chart_symbol",
            "side",
            "entry_time",
            "entry_price",
            "exit_time",
            "exit_price",
            "qty",
            "fees",
            "pnl",
        ]
    ].copy()

    out = out.dropna(subset=["side", "entry_time", "exit_time", "entry_price", "exit_price", "qty"])
    out["entry_time"] = out["entry_time"].dt.strftime("%Y-%m-%d %H:%M:%S")
    out["exit_time"] = out["exit_time"].dt.strftime("%Y-%m-%d %H:%M:%S")
    return out


def normalize_exness_exports(paths: list[Path]) -> pd.DataFrame:
    frames = []
    for index, path in enumerate(paths, start=1):
        account_tag = path.stem.replace(" ", "_") or f"account_{index}"
        frames.append(normalize_exness_file(path, account_tag))

    if not frames:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    result = pd.concat(frames, ignore_index=True)
    result.sort_values("entry_time", inplace=True)
    return result


def normalize_bybit_export(path: Path) -> pd.DataFrame:
    df = normalize_columns(pd.read_csv(path))

    symbol_col = first_present_column(df, ["symbol", "market"])
    side_col = first_present_column(df, ["side", "direction"])
    order_time_col = first_present_column(df, ["order_time", "order_time_utc_0", "create_time"])
    filled_price_col = first_present_column(df, ["avg_price", "filled_price"])
    filled_qty_col = first_present_column(df, ["closed_size", "filled_quantity"])
    fee_col = first_present_column(df, ["fee", "feeinfo"])

    pnl_col = None
    for candidate in ["realized_pnl", "closed_pnl"]:
        if candidate in df.columns:
            pnl_col = candidate
            break

    required = [order_time_col, symbol_col, side_col, filled_price_col, filled_qty_col, fee_col]
    missing = [column for column in required if column not in df.columns]
    if missing:
        raise KeyError(f"{path.name} is missing required columns: {', '.join(missing)}")

    df = df[pd.to_numeric(df[filled_qty_col], errors="coerce").fillna(0) > 0].copy()
    df[order_time_col] = pd.to_datetime(df[order_time_col], errors="coerce")
    df["side_mapped"] = df[side_col].astype(str).str.upper().map(
        {
            "BUY": "LONG",
            "SELL": "SHORT",
            "LONG": "LONG",
            "SHORT": "SHORT",
        }
    )

    if fee_col == "feeinfo":
        def parse_fee_info(value):
            if pd.isna(value) or value == "":
                return 0.0
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError:
                return 0.0
            if isinstance(parsed, dict):
                try:
                    return sum(float(amount) for amount in parsed.values())
                except ValueError:
                    return 0.0
            return 0.0

        df["normalized_fee"] = df[fee_col].apply(parse_fee_info)
    else:
        df["normalized_fee"] = pd.to_numeric(df[fee_col], errors="coerce").fillna(0.0)

    trades = []

    for symbol in df[symbol_col].dropna().unique():
        df_symbol = df[df[symbol_col] == symbol].sort_values(order_time_col, kind="stable")

        position = 0.0
        entry_price = None
        entry_time = None
        entry_fee = 0.0

        for index, row in df_symbol.iterrows():
            side = row["side_mapped"]
            qty = float(row[filled_qty_col])
            price = float(row[filled_price_col])
            time = row[order_time_col]

            if (
                side not in ("LONG", "SHORT")
                or pd.isna(time)
                or not math.isfinite(qty)
                or not math.isfinite(price)
                or qty <= 0
                or price <= 0
            ):
                raise ValueError(
                    f"{path.name}, row {index + 2}: invalid filled order for {symbol}."
                )

            if position == 0:
                entry_time = time
                entry_price = price
                entry_fee = float(row["normalized_fee"])
                position = qty if side == "LONG" else -qty
                continue

            same_direction = (side == "LONG") == (position > 0)
            if same_direction or qty != abs(position):
                sequence = "scale-in" if same_direction else "partial close or position reversal"
                raise ValueError(
                    f"{path.name}, row {index + 2}: unsupported {sequence} for {symbol}. "
                    "Bybit normalization requires one opening fill followed by one "
                    "opposite fill of the same quantity. Use complete, unscaled round trips."
                )

            chart_exchange, chart_symbol = map_chart_symbol(symbol)
            trades.append(
                {
                    "exchange": "bybit",
                    "symbol": symbol,
                    "chart_exchange": chart_exchange,
                    "chart_symbol": chart_symbol,
                    "side": "LONG" if position > 0 else "SHORT",
                    "entry_time": entry_time.strftime("%Y-%m-%d %H:%M:%S") if entry_time is not None else None,
                    "entry_price": entry_price,
                    "exit_time": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "exit_price": price,
                    "qty": abs(position),
                    "fees": entry_fee + float(row["normalized_fee"]),
                    "pnl": float(row[pnl_col]) if pnl_col and not pd.isna(row[pnl_col]) else None,
                }
            )

            position = 0.0
            entry_price = None
            entry_time = None
            entry_fee = 0.0

        if position != 0:
            raise ValueError(
                f"{path.name}: unclosed {symbol} position at the end of the export. "
                "Provide complete opening and closing pairs."
            )

    result = pd.DataFrame(trades, columns=OUTPUT_COLUMNS)
    return result.dropna(subset=["entry_time", "entry_price", "exit_time", "exit_price", "qty"], how="any")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Normalize trade export CSV files.")
    subparsers = parser.add_subparsers(dest="source", required=True)

    exness_parser = subparsers.add_parser("exness", help="Normalize Exness exports.")
    exness_parser.add_argument("files", nargs="+", type=Path, help="One or more Exness CSV files.")
    exness_parser.add_argument("--output", type=Path, default=Path("normalized_exness.csv"))

    bybit_parser = subparsers.add_parser("bybit", help="Normalize a Bybit export.")
    bybit_parser.add_argument("--input", required=True, type=Path, help="Bybit CSV export path.")
    bybit_parser.add_argument("--output", type=Path, default=Path("normalized_bybit.csv"))

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        if args.source == "exness":
            result = normalize_exness_exports(args.files)
            output_path = args.output
        else:
            result = normalize_bybit_export(args.input)
            output_path = args.output
    except (FileNotFoundError, KeyError, ValueError, pd.errors.ParserError) as exc:
        print(f"Error: {exc}")
        return 1

    result.to_csv(output_path, index=False)
    print(f"Saved {len(result)} normalized trades to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
