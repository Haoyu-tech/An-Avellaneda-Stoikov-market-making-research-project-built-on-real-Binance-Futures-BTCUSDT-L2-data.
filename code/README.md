# Market-Making Research Scripts

[Project overview](../README.md) · [Reproduction guide](../docs/REPRODUCIBILITY.md)

## Main workflow

| Script | Purpose |
|---|---|
| [run_as_pipeline.py](run_as_pipeline.py) | Collection, experiment runs and HTML export |
| [collect_as_l2.py](collect_as_l2.py) | Binance Futures snapshot, depth and trade collection |
| [as_backtest.py](as_backtest.py) | Inventory, fees and approximate execution |
| [plot_as_backtest.py](plot_as_backtest.py) | Interactive HTML report |
| [run_as_l2_background.ps1](run_as_l2_background.ps1) | Background collection helper |

## Quick start

Run from the **repository root**, rather than this subdirectory:

```powershell
python -m pip install -r requirements.txt
python code/run_as_pipeline.py --symbol BTCUSDT --max-seconds 60 --backtest-seconds 60 --collector-quiet
```

For collection only:

```powershell
python code/collect_as_l2.py --symbol BTCUSDT --max-seconds 180 --include-trades --quiet --flush-every 500
```

Use `--help` on each script for its arguments. For saved-session analysis, point `as_backtest.py --session-dir` at the collected session, then pass its JSON output to `plot_as_backtest.py --summary-json`.

## Legacy experiments

`data`, `export_l2_html.py` and `replay_l2.py` are earlier experimental files. The four main Python scripts above define the current collection/backtest/report route.
