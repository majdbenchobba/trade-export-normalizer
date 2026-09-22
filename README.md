# Trade Export Normalizer

[![Python tests](https://github.com/majdbenchobba/trade-export-normalizer/actions/workflows/tests.yml/badge.svg)](https://github.com/majdbenchobba/trade-export-normalizer/actions/workflows/tests.yml)

CLI for cleaning up broker or exchange CSV exports into one consistent trade format.

Right now it supports:

- Exness exports
- Bybit order history exports

## Install

```bash
pip install -r requirements.txt
```

## Usage

Exness:

```bash
python trade_export_normalizer.py exness --output normalized_exness.csv exness_account_1.csv exness_account_2.csv
```

Bybit:

```bash
python trade_export_normalizer.py bybit --input bybit_orders.csv --output normalized_bybit.csv
```

The `examples/` directory contains fictional CSV records that can be used for a
safe local trial. It contains no real account or trading data.

## Tests

```bash
python -m unittest discover -s tests -v
```

## Output columns

The normalized CSV uses:

- `exchange`
- `symbol`
- `chart_exchange`
- `chart_symbol`
- `side`
- `entry_time`
- `entry_price`
- `exit_time`
- `exit_price`
- `qty`
- `fees`
- `pnl`

## Notes

- symbol mapping is pretty minimal on purpose
- unknown symbols stay in the export, but chart fields may be empty
- this tool only works with local CSV files
- never commit real broker exports; they can contain financial and account data
- Bybit normalization currently models straightforward open-then-close sequences,
  not every partial-fill, scale-in, scale-out, or position-reversal case
