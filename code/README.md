# Code Folder

## Keep Using These

- `run_as_pipeline.py`
  One-click pipeline for collection, categorized backtests, and HTML export.

- `collect_as_l2.py`
  Aligned Binance Futures L2 collector for A-S backtests.

- `as_backtest.py`
  Continuous A-S backtest engine with dynamic `sigma / intensity / k`, queue-aware fills, practical account constraints, and fee-aware quote spacing.

- `plot_as_backtest.py`
  HTML visualization for mid, quotes, sigma, k, inventory, fills, and equity.

- `run_as_l2_background.ps1`
  Background launcher for asynchronous collection.

## Legacy Files

- `data`
- `export_l2_html.py`
- `replay_l2.py`

These are old experiment files and are not part of the current A-S workflow.

## Recommended Commands

Run the whole pipeline in one command:

```powershell
& D:\software\anaconda3\envs\quant\python.exe .\code\run_as_pipeline.py --symbol BTCUSDT --max-seconds 60 --backtest-seconds 60 --collector-quiet
```

Collect 3 minutes with trades:

```powershell
& D:\software\anaconda3\envs\quant\python.exe .\code\collect_as_l2.py --symbol BTCUSDT --max-seconds 180 --include-trades --quiet --flush-every 500
```

Run continuous A-S backtest:

```powershell
& D:\software\anaconda3\envs\quant\python.exe .\code\as_backtest.py --session-dir .\data\as_l2\btcusdt\btcusdt_20260320_181151 --initial-cash 1000 --dynamic-window-seconds 10 --order-size 0.003 --max-order-notional 300 --inventory-limit 0.03 --output-json .\data\as_l2\btcusdt\btcusdt_20260320_181151\as_summary_continuous_180s.json
```

Render the backtest chart:

```powershell
& D:\software\anaconda3\envs\quant\python.exe .\code\plot_as_backtest.py --summary-json .\data\as_l2\btcusdt\btcusdt_20260320_181151\as_summary_continuous_180s.json --output-html .\data\as_l2\btcusdt\btcusdt_20260320_181151\as_plot_dynamic_180s.html
```
