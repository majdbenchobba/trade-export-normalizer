# Trade Export Normalizer

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
