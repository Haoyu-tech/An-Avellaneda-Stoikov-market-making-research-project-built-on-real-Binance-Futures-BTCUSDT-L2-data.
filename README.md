# Chapter3-BitcoinUSDT

An Avellaneda-Stoikov market-making research project built on real Binance Futures `BTCUSDT` L2 data.

This repository is not meant to be a production trading system. Its goal is to make the full research workflow reproducible:

1. Collect real order book snapshots, diff-depth updates, and trades
2. Reconstruct the order book from `snapshot + diff depth`
3. Run an A-S backtest with inventory risk
4. Add fees, cash constraints, inventory constraints, and order/cancel latency
5. Export structured JSON results and HTML reports

The project now supports a one-command pipeline for collection, backtesting, categorized result output, and HTML generation.

## Features

- Uses real Binance Futures `BTCUSDT` L2 data instead of synthetic samples
- Includes A-S quote logic, inventory risk, cash limits, and max-notional limits
- Supports fee-aware quoting
- Supports order latency, cancel latency, and a stricter order lifecycle model
- Exports `pnl_breakdown` and `execution_stats`
- Saves outputs automatically into `baseline / fee_tests / latency_tests / size_tests`
- Provides a one-click pipeline script for end-to-end experiments

## Current Findings

The main findings so far are:

- The strategy can generate a very thin gross edge on some short samples
- Once realistic fees are added, net PnL often turns negative
- Latency and quote refresh behavior materially affect fills and outcomes
- Larger `order_size` tends to increase both returns and drawdown
- The simulator is much more realistic than a toy backtest, but still not an exchange-grade matching engine

## Repository Structure

Project root:

```text
Chapter3-BitcoinUSDT/
|- README.md
|- code/
|- data/
`- logs/
```

Code directory:

```text
code/
|- collect_as_l2.py
|- as_backtest.py
|- plot_as_backtest.py
|- run_as_pipeline.py
|- run_as_l2_background.ps1
|- README.md
|- replay_l2.py
|- export_l2_html.py
`- data/
```

Main files:

- `collect_as_l2.py`
  Collects Binance Futures `snapshot / depth / aggTrade`
- `as_backtest.py`
  Main A-S backtest engine
- `plot_as_backtest.py`
  Renders backtest results to HTML
- `run_as_pipeline.py`
  Runs the full pipeline: collect -> backtest -> categorized outputs -> HTML
- `run_as_l2_background.ps1`
  Helper script for background collection

`replay_l2.py`, `export_l2_html.py`, and `code/data/` are older experimental leftovers and are not part of the current main workflow.

## Output Layout

Each run creates a session directory with this structure:

```text
data/as_l2/btcusdt/<session_name>/
|- snapshot.ndjson
|- depth.ndjson
|- aggtrade.ndjson
|- meta.json
|- baseline/
|- fee_tests/
|- latency_tests/
`- size_tests/
```

Raw files:

- `snapshot.ndjson`
  Initial depth snapshot
- `depth.ndjson`
  Incremental depth events
- `aggtrade.ndjson`
  Aggregated trade stream
- `meta.json`
  Collection metadata

Result categories:

- `baseline/`
  Base backtest outputs
- `fee_tests/`
  Fee-related experiments
- `latency_tests/`
  Latency and execution-stat experiments
- `size_tests/`
  `order_size` sweep experiments

Naming convention:

- `summary_*.json`
  Single-run backtest result
- `plot_*.html`
  Single-run visualization
- `compare_*.json`
  Parameter comparison result
- `compare_*.html`
  Parameter comparison visualization

## What The Backtest Models

Implemented:

- `snapshot + diff depth` order book reconstruction
- `aggTrade` replay
- A-S style reservation price and spread
- Inventory limits
- Cash limits and max-order-notional limits
- Fee-aware minimum quote width
- Order latency
- Cancel/replace latency
- Separation between `target quote` and `active quote`
- `pnl_breakdown`
- `execution_stats`

Still approximate:

- Exact exchange queue position
- Full market-by-order queue reconstruction
- Network jitter and exchange ACK timing
- Hidden liquidity
- Same-price competition
- Fully accurate queue depletion from full matching data

## Default Parameters

Current defaults in `as_backtest.py`:

- `order_size = 0.003`
- `max_order_notional = 300`
- `inventory_limit = 0.03`
- `maker_fee_rate = 0.0002`
- `dynamic_window_seconds = 10`
- `order_latency_ms = 150`
- `cancel_latency_ms = 100`
- `fee_spread_multiplier = 1.0`

These defaults are research-oriented and should not be treated as production parameters.

## Environment

The project is currently used in a Windows + Conda setup. Example commands assume:

```powershell
D:\software\anaconda3\envs\quant\python.exe
```

If your Python path is different, replace it with your own interpreter.

The code mainly depends on the standard library plus common scientific / plotting packages. If something is missing, install the dependency reported by the error message in your current environment.

## Quick Start

### 1. Collect data only

```powershell
& D:\software\anaconda3\envs\quant\python.exe .\code\collect_as_l2.py --symbol BTCUSDT --max-seconds 60 --include-trades --quiet --flush-every 500
```

### 2. Run a backtest on an existing session

```powershell
& D:\software\anaconda3\envs\quant\python.exe .\code\as_backtest.py --session-dir .\data\as_l2\btcusdt\btcusdt_20260321_101335 --initial-cash 1000 --dynamic-window-seconds 10 --max-backtest-seconds 60 --output-json .\data\as_l2\btcusdt\btcusdt_20260321_101335\baseline\summary_continuous_60s.json
```

### 3. Render HTML

```powershell
& D:\software\anaconda3\envs\quant\python.exe .\code\plot_as_backtest.py --summary-json .\data\as_l2\btcusdt\btcusdt_20260321_101335\baseline\summary_continuous_60s.json --output-html .\data\as_l2\btcusdt\btcusdt_20260321_101335\baseline\plot_continuous_60s.html
```

## One-Command Pipeline

The recommended entry point is:

```powershell
& D:\software\anaconda3\envs\quant\python.exe .\code\run_as_pipeline.py --symbol BTCUSDT --max-seconds 60 --backtest-seconds 60 --collector-quiet
```

It automatically:

1. Collects a new session
2. Creates `baseline / fee_tests / latency_tests / size_tests`
3. Runs the baseline backtest
4. Runs fee-related tests
5. Exports latency-related results
6. Runs the size sweep
7. Generates HTML reports

To force a session name:

```powershell
& D:\software\anaconda3\envs\quant\python.exe .\code\run_as_pipeline.py --symbol BTCUSDT --max-seconds 300 --backtest-seconds 300 --collector-quiet --session-name btcusdt_pipeline_5min
```

## Pipeline Arguments

Common `run_as_pipeline.py` arguments:

- `--symbol`
  Trading symbol, default `BTCUSDT`
- `--max-seconds`
  Collection duration
- `--backtest-seconds`
  Backtest only the first N seconds, or `0` for the full session
- `--initial-cash`
  Initial cash
- `--dynamic-window-seconds`
  Rolling estimation window
- `--order-latency-ms`
  Order activation latency
- `--cancel-latency-ms`
  Cancel latency
- `--session-name`
  Explicit session name
- `--collector-quiet`
  Reduce collector console output

## How To Read The Outputs

Important JSON fields:

- `summary`
  Top-level backtest metrics
- `summary.pnl_breakdown`
  Gross PnL, inventory PnL, fees, and net PnL
- `summary.execution_stats`
  Refresh counts, submits, cancels, activated qty, filled qty, and unfilled qty
- `first_fills`
  First few fills
- `equity_curve`
  Per-event state over time

Important HTML sections:

- Summary cards
- Best bid/ask
- `target quote`
- `active quote`
- Fill markers
- Equity and cash changes
- `PnL Breakdown`
- `Execution Stats`

## Existing Experiment Results

### 5-Minute Pipeline Run

The latest full 5-minute run is stored in:

- `data/as_l2/btcusdt/btcusdt_pipeline_5min`

Key files:

- baseline
  - `baseline/summary_continuous_300s.json`
  - `baseline/plot_continuous_300s.html`
- fee
  - `fee_tests/summary_fee_aware.json`
  - `fee_tests/summary_fee0.json`
  - `fee_tests/plot_fee_breakdown.html`
- size
  - `size_tests/summary_fee0_size001.json`
  - `size_tests/summary_fee0_size002.json`
  - `size_tests/summary_fee0_size003.json`
  - `size_tests/summary_fee0_size005.json`

The main baseline result for that 5-minute sample is roughly:

- `events = 2925`
- `trades_seen = 5304`
- `fills = 5`
- `gross_pnl_before_fees = +0.0453 USDT`
- `fees_paid = 0.1690 USDT`
- `net_pnl = -0.1237 USDT`

So on this sample the strategy had positive gross PnL, but fees still pushed the final result negative.

Under zero fees:

- `size = 0.005` was roughly break-even, with `net_pnl ≈ +0.00625 USDT`

## Limitations

- This is still not an exchange-grade matching simulator
- `aggTrade` is not a full market-by-order matching feed
- The queue model remains approximate
- Results are sensitive to the exact sample window
- Auto-selected `gamma` and `k` are useful for research, not proof of robustness
- Short-sample positive results should not be interpreted as stable live alpha

## Next Steps

- Run longer out-of-sample backtests
- Sweep `fee x latency x size`
- Tighten queue depletion modeling further
- Separate “classic A-S” from “engineering-enhanced A-S”
- Add more session-level comparison reports

## Disclaimer

This project is for research and educational purposes only.  
Nothing here should be treated as investment advice.  
All backtest results depend on sample selection, parameter choices, and an approximate execution model.
