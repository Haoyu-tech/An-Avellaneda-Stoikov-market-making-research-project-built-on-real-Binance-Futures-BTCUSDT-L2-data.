<div align="center">

# BTC L2 Market Making

Avellaneda–Stoikov research on real Binance Futures order-book data.

![Python: 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=flat-square) ![Data: Binance Futures](https://img.shields.io/badge/Data-Binance%20Futures-0F766E?style=flat-square) ![Scope: Research](https://img.shields.io/badge/Scope-Research-64748B?style=flat-square)

[Quick start](#quick-start) · [Project map](#project-map) · [Reproduction guide](docs/REPRODUCIBILITY.md)

</div>

---

## Overview

Collect market data, reconstruct the order book, test inventory-aware quotes, and inspect fees and execution assumptions in an HTML report.

```text
Public market data → L2 reconstruction → A-S backtest → JSON results → HTML reports
```

## Highlights

- Snapshot, diff-depth and aggregated-trade collection.
- Inventory and account constraints, fee-aware quoting, and order/cancel latency.
- Experiments grouped by baseline, fees, latency and order size.
- Structured PnL and execution statistics alongside visual reports.

## Quick start

Run from the repository root in a Python 3.10+ environment:

```powershell
python -m pip install -r requirements.txt
python code/run_as_pipeline.py --symbol BTCUSDT --max-seconds 60 --backtest-seconds 60 --collector-quiet
```

The pipeline collects a new market-data session and writes results under `data/as_l2/btcusdt/`. Internet access is required for collection. Use the same saved session when comparing parameter settings.

## Project map

| Path | Role |
|---|---|
| [code/collect_as_l2.py](code/collect_as_l2.py) | Public market-data collector |
| [code/as_backtest.py](code/as_backtest.py) | Inventory, fees and approximate execution model |
| [code/run_as_pipeline.py](code/run_as_pipeline.py) | End-to-end experiment runner |
| [code/plot_as_backtest.py](code/plot_as_backtest.py) | HTML report renderer |
| [code/README.md](code/README.md) | Script-level commands |

## Recorded findings

The original five-minute baseline reported **+0.0453 USDT gross PnL**, **0.1690 USDT fees**, and **−0.1237 USDT net PnL**. This illustrates how fees can dominate a thin gross edge; it does not establish a stable trading advantage.

Results depend on the session, order size, latency, calibration and approximate queue model. Original-session replay commands, parameter defaults and output definitions are preserved in [the detailed reference](docs/PROJECT_REFERENCE.md).

## Scope

Research and education only. The simulator approximates queue position and exchange execution; it does not send trading orders.

## Documentation

- [Reproduction guide](docs/REPRODUCIBILITY.md): inputs, execution order and validation limits.
- [Code and artifact map](docs/REPOSITORY_MAP.md): source and configuration paths.

<sub>Research artifacts reflect the recorded experiment settings. Full results were not regenerated during documentation cleanup.</sub>
