import argparse
import shutil
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
CODE_DIR = REPO_ROOT / "code"
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "data" / "as_l2"


def format_seconds_tag(seconds: float) -> str:
    if seconds <= 0:
        return "full"
    if float(seconds).is_integer():
        return f"{int(seconds)}s"
    text = str(seconds).replace(".", "p")
    return f"{text}s"


def run_command(args: list[str]) -> None:
    print(flush=True)
    print(">", " ".join(args), flush=True)
    subprocess.run(args, check=True, cwd=REPO_ROOT)


def write_plot(summary_json: Path, output_html: Path) -> None:
    run_command(
        [
            sys.executable,
            str(CODE_DIR / "plot_as_backtest.py"),
            "--summary-json",
            str(summary_json),
            "--output-html",
            str(output_html),
        ]
    )


def write_backtest(
    session_dir: Path,
    output_json: Path,
    *,
    initial_cash: float,
    dynamic_window_seconds: float,
    max_backtest_seconds: float,
    order_size: float | None = None,
    max_order_notional: float | None = None,
    inventory_limit: float | None = None,
    maker_fee_rate: float | None = None,
    order_latency_ms: int | None = None,
    cancel_latency_ms: int | None = None,
) -> None:
    cmd = [
        sys.executable,
        str(CODE_DIR / "as_backtest.py"),
        "--session-dir",
        str(session_dir),
        "--initial-cash",
        str(initial_cash),
        "--dynamic-window-seconds",
        str(dynamic_window_seconds),
        "--output-json",
        str(output_json),
    ]
    if max_backtest_seconds > 0:
        cmd.extend(["--max-backtest-seconds", str(max_backtest_seconds)])
    if order_size is not None:
        cmd.extend(["--order-size", str(order_size)])
    if max_order_notional is not None:
        cmd.extend(["--max-order-notional", str(max_order_notional)])
    if inventory_limit is not None:
        cmd.extend(["--inventory-limit", str(inventory_limit)])
    if maker_fee_rate is not None:
        cmd.extend(["--maker-fee-rate", str(maker_fee_rate)])
    if order_latency_ms is not None:
        cmd.extend(["--order-latency-ms", str(order_latency_ms)])
    if cancel_latency_ms is not None:
        cmd.extend(["--cancel-latency-ms", str(cancel_latency_ms)])
    run_command(cmd)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="One-click pipeline for collection, categorized backtests, and HTML output."
    )
    parser.add_argument("--symbol", type=str, default="BTCUSDT", help="Trading symbol, for example BTCUSDT.")
    parser.add_argument("--max-seconds", type=float, default=60.0, help="Collection duration in seconds.")
    parser.add_argument(
        "--backtest-seconds",
        type=float,
        default=0.0,
        help="Backtest only the first N seconds. Use 0 to use the full collected session.",
    )
    parser.add_argument("--initial-cash", type=float, default=1000.0, help="Initial cash in USDT.")
    parser.add_argument("--dynamic-window-seconds", type=float, default=10.0, help="Dynamic estimation window.")
    parser.add_argument("--order-latency-ms", type=int, default=150, help="Order activation latency.")
    parser.add_argument("--cancel-latency-ms", type=int, default=100, help="Cancel/replace latency.")
    parser.add_argument(
        "--output-root",
        type=str,
        default=str(DEFAULT_OUTPUT_ROOT),
        help="Root directory for collected sessions.",
    )
    parser.add_argument("--session-name", type=str, default="", help="Optional explicit session name.")
    parser.add_argument("--collector-quiet", action="store_true", help="Pass --quiet to the collector.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_root = Path(args.output_root)
    backtest_seconds = args.backtest_seconds if args.backtest_seconds > 0 else args.max_seconds
    duration_tag = format_seconds_tag(backtest_seconds)

    collect_cmd = [
        sys.executable,
        str(CODE_DIR / "collect_as_l2.py"),
        "--symbol",
        args.symbol,
        "--max-seconds",
        str(args.max_seconds),
        "--include-trades",
        "--flush-every",
        "500",
        "--output-root",
        str(output_root),
    ]
    if args.session_name:
        collect_cmd.extend(["--session-name", args.session_name])
    if args.collector_quiet:
        collect_cmd.append("--quiet")
    run_command(collect_cmd)

    symbol_dir = output_root / args.symbol.lower()
    if args.session_name:
        session_dir = symbol_dir / args.session_name
    else:
        session_dirs = [path for path in symbol_dir.iterdir() if path.is_dir()]
        if not session_dirs:
            raise RuntimeError(f"No session directory found under {symbol_dir}")
        session_dir = max(session_dirs, key=lambda path: path.stat().st_mtime)

    baseline_dir = session_dir / "baseline"
    fee_tests_dir = session_dir / "fee_tests"
    latency_tests_dir = session_dir / "latency_tests"
    size_tests_dir = session_dir / "size_tests"
    for path in (baseline_dir, fee_tests_dir, latency_tests_dir, size_tests_dir):
        path.mkdir(parents=True, exist_ok=True)

    baseline_json = baseline_dir / f"summary_continuous_{duration_tag}.json"
    baseline_html = baseline_dir / f"plot_continuous_{duration_tag}.html"
    fee_aware_json = fee_tests_dir / "summary_fee_aware.json"
    fee_breakdown_json = fee_tests_dir / "summary_fee_breakdown.json"
    fee_breakdown_html = fee_tests_dir / "plot_fee_breakdown.html"
    fee0_json = fee_tests_dir / "summary_fee0.json"
    fee0_html = fee_tests_dir / "plot_fee0.html"
    latency_json = latency_tests_dir / "summary_latency_queue_stats.json"

    write_backtest(
        session_dir,
        baseline_json,
        initial_cash=args.initial_cash,
        dynamic_window_seconds=args.dynamic_window_seconds,
        max_backtest_seconds=backtest_seconds,
        order_latency_ms=args.order_latency_ms,
        cancel_latency_ms=args.cancel_latency_ms,
    )
    write_backtest(
        session_dir,
        fee_aware_json,
        initial_cash=args.initial_cash,
        dynamic_window_seconds=args.dynamic_window_seconds,
        max_backtest_seconds=backtest_seconds,
        order_latency_ms=args.order_latency_ms,
        cancel_latency_ms=args.cancel_latency_ms,
    )
    shutil.copy2(fee_aware_json, fee_breakdown_json)
    write_backtest(
        session_dir,
        fee0_json,
        initial_cash=args.initial_cash,
        dynamic_window_seconds=args.dynamic_window_seconds,
        max_backtest_seconds=backtest_seconds,
        maker_fee_rate=0.0,
        order_latency_ms=args.order_latency_ms,
        cancel_latency_ms=args.cancel_latency_ms,
    )
    write_backtest(
        session_dir,
        latency_json,
        initial_cash=args.initial_cash,
        dynamic_window_seconds=args.dynamic_window_seconds,
        max_backtest_seconds=backtest_seconds,
        order_latency_ms=args.order_latency_ms,
        cancel_latency_ms=args.cancel_latency_ms,
    )

    size_sweeps = [
        ("summary_fee0_size001.json", 0.001, 100.0, 0.01),
        ("summary_fee0_size002.json", 0.002, 200.0, 0.02),
        ("summary_fee0_size003.json", 0.003, 300.0, 0.03),
        ("summary_fee0_size005.json", 0.005, 500.0, 0.05),
    ]
    for filename, order_size, max_order_notional, inventory_limit in size_sweeps:
        write_backtest(
            session_dir,
            size_tests_dir / filename,
            initial_cash=args.initial_cash,
            dynamic_window_seconds=args.dynamic_window_seconds,
            max_backtest_seconds=backtest_seconds,
            order_size=order_size,
            max_order_notional=max_order_notional,
            inventory_limit=inventory_limit,
            maker_fee_rate=0.0,
            order_latency_ms=args.order_latency_ms,
            cancel_latency_ms=args.cancel_latency_ms,
        )
    shutil.copy2(size_tests_dir / "summary_fee0_size003.json", size_tests_dir / "summary_fee0_new_defaults.json")

    write_plot(baseline_json, baseline_html)
    write_plot(fee_breakdown_json, fee_breakdown_html)
    write_plot(fee0_json, fee0_html)

    print(flush=True)
    print("Pipeline completed successfully.", flush=True)
    print(f"Session directory: {session_dir}", flush=True)


if __name__ == "__main__":
    main()
