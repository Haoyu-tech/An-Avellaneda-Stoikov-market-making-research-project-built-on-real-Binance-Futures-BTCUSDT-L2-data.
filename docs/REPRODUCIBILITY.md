# Reproduction guide

## Entry point and inputs

Run from the repository root with Python 3.10+. Install [requirements.txt](../requirements.txt). The core collection workflow needs internet access to Binance Futures public market data; it sends no trading orders.

```powershell
python code/run_as_pipeline.py --help
python code/run_as_pipeline.py --symbol BTCUSDT --max-seconds 60 --backtest-seconds 60 --collector-quiet
```

The pipeline generates a new session under `data/as_l2/btcusdt/`. Retain snapshot, depth, trade and metadata files together. For a repeatable comparison, replay the same saved session rather than collecting a new price path for each run. See [README](../README.md) for existing-session backtest commands.

## Outputs and interpretation

Session outputs include JSON summaries and HTML reports grouped into baseline, fees, latency and size experiments. The original short-sample results described in the README are historical results; their raw session is not committed. A fresh live collection is not expected to reproduce those numbers.

Capture fee, latency, order-size and calibration settings alongside each result. The queue and fill model is approximate.

## Run record

For every result you intend to compare or share, retain the repository commit, exact command/configuration, input-data identity, environment versions and output location. Save a dependency snapshot after a successful reference run; newly added requirements lists are intentionally unpinned until that validation exists.

## Validation status

Cleanup review: 14 October 2026. File paths and documented entry points were checked against the checkout. Full empirical results were not regenerated. Project-specific external prerequisites and known blockers are listed above.
