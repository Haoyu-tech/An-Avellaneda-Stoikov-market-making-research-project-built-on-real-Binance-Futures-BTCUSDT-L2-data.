import argparse
import json
from datetime import datetime
from pathlib import Path


def load_ndjson(path: Path) -> list[dict]:
    records: list[dict] = []
    with path.open("r", encoding="utf-8") as file_obj:
        for line in file_obj:
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))
    return records


def build_book(levels: list[list[str]]) -> dict[float, float]:
    book: dict[float, float] = {}
    for price_str, qty_str in levels:
        price = float(price_str)
        qty = float(qty_str)
        if qty > 0:
            book[price] = qty
    return book


def apply_updates(book: dict[float, float], updates: list[list[str]]) -> None:
    for price_str, qty_str in updates:
        price = float(price_str)
        qty = float(qty_str)
        if qty == 0:
            book.pop(price, None)
        else:
            book[price] = qty


def best_levels(bids: dict[float, float], asks: dict[float, float], depth: int) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
    top_bids = sorted(bids.items(), key=lambda item: item[0], reverse=True)[:depth]
    top_asks = sorted(asks.items(), key=lambda item: item[0])[:depth]
    return top_bids, top_asks


def fmt_num(value: float | None, digits: int = 4) -> str:
    if value is None:
        return "N/A"
    return f"{value:.{digits}f}"


def quantity_bar(qty: float, max_qty: float, width: int = 18) -> str:
    if max_qty <= 0:
        return ""
    filled = max(1, round(width * qty / max_qty)) if qty > 0 else 0
    return "#" * filled


def print_book_table(top_bids: list[tuple[float, float]], top_asks: list[tuple[float, float]]) -> None:
    all_qty = [qty for _, qty in top_bids + top_asks]
    max_qty = max(all_qty) if all_qty else 0.0
    print("  " + "-" * 88)
    print("  bid_price    bid_qty   bid_bar              | ask_price    ask_qty   ask_bar")
    print("  " + "-" * 88)
    rows = max(len(top_bids), len(top_asks))
    for idx in range(rows):
        bid_price, bid_qty = top_bids[idx] if idx < len(top_bids) else (None, None)
        ask_price, ask_qty = top_asks[idx] if idx < len(top_asks) else (None, None)
        bid_bar = quantity_bar(bid_qty or 0.0, max_qty)
        ask_bar = quantity_bar(ask_qty or 0.0, max_qty)
        bid_price_str = f"{bid_price:.2f}" if bid_price is not None else ""
        ask_price_str = f"{ask_price:.2f}" if ask_price is not None else ""
        bid_qty_str = fmt_num(bid_qty) if bid_qty is not None else ""
        ask_qty_str = fmt_num(ask_qty) if ask_qty is not None else ""
        print(
            f"  {bid_price_str:>10} {bid_qty_str:>10} {bid_bar:<18} | "
            f"{ask_price_str:>10} {ask_qty_str:>10} {ask_bar:<18}"
        )


def capture_changes(book: dict[float, float], updates: list[list[str]], side: str) -> list[dict]:
    changes: list[dict] = []
    for price_str, qty_str in updates:
        price = float(price_str)
        new_qty = float(qty_str)
        old_qty = book.get(price, 0.0)
        if old_qty == new_qty:
            continue
        if new_qty == 0:
            action = "remove"
        elif old_qty == 0:
            action = "add"
        else:
            action = "update"
        changes.append(
            {
                "side": side,
                "price": price,
                "old_qty": old_qty,
                "new_qty": new_qty,
                "delta": new_qty - old_qty,
                "action": action,
            }
        )
    return changes


def print_changes(changes: list[dict], max_items: int) -> None:
    if not changes:
        print("  changes: no price level updates")
        return

    print("  changes:")
    printed = 0
    for change in changes:
        if printed >= max_items:
            break
        print(
            f"    {change['side']:>3} {change['price']:.2f} "
            f"{change['action']:<6} {fmt_num(change['old_qty'])} -> {fmt_num(change['new_qty'])} "
            f"(delta {change['delta']:+.4f})"
        )
        printed += 1
    if len(changes) > max_items:
        print(f"    ... {len(changes) - max_items} more updates")


def extract_trade_lookup(trades_records: list[dict]) -> dict[int, list[dict]]:
    lookup: dict[int, list[dict]] = {}
    for record in trades_records:
        payload = record.get("payload", {})
        event_time = payload.get("E")
        if event_time is None:
            continue
        lookup.setdefault(event_time, []).append(payload)
    return lookup


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Replay Binance L2 book from snapshot + diff depth.")
    parser.add_argument(
        "--snapshot",
        type=str,
        default="data/l2_snapshot.ndjson",
        help="NDJSON snapshot file path.",
    )
    parser.add_argument(
        "--diff",
        type=str,
        default="data/l2_diff_depth.ndjson",
        help="NDJSON diff depth file path.",
    )
    parser.add_argument(
        "--trades",
        type=str,
        default="data/raw_aggtrade.ndjson",
        help="Optional aggTrade file path. Use empty string to disable.",
    )
    parser.add_argument(
        "--steps",
        type=int,
        default=5,
        help="How many diff-depth records to replay.",
    )
    parser.add_argument(
        "--levels",
        type=int,
        default=5,
        help="How many price levels to print on each side.",
    )
    parser.add_argument(
        "--show-changes",
        type=int,
        default=10,
        help="How many changed price levels to show per step.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    snapshot_path = Path(args.snapshot)
    diff_path = Path(args.diff)
    trades_path = Path(args.trades) if args.trades else None

    snapshot_records = load_ndjson(snapshot_path)
    if not snapshot_records:
        raise ValueError(f"No snapshot records found in {snapshot_path}")

    snapshot_payload = snapshot_records[-1]["payload"]
    bids = build_book(snapshot_payload["bids"])
    asks = build_book(snapshot_payload["asks"])
    last_update_id = snapshot_payload["lastUpdateId"]

    diff_records = load_ndjson(diff_path)
    trade_lookup = extract_trade_lookup(load_ndjson(trades_path)) if trades_path and trades_path.exists() else {}

    print("=" * 88)
    print("Replay Binance L2 From Snapshot + Diff")
    print("=" * 88)
    print(f"snapshot file: {snapshot_path}")
    print(f"diff file:     {diff_path}")
    if trades_path:
        print(f"trades file:   {trades_path}")
    print(f"snapshot lastUpdateId: {last_update_id}")
    print("-" * 88)

    replayed = 0
    for record in diff_records:
        payload = record.get("payload", {})
        start_id = payload.get("U")
        end_id = payload.get("u")
        prev_end_id = payload.get("pu")

        if end_id is None or end_id < last_update_id:
            continue

        bid_changes = capture_changes(bids, payload.get("b", []), "bid")
        ask_changes = capture_changes(asks, payload.get("a", []), "ask")
        apply_updates(bids, payload.get("b", []))
        apply_updates(asks, payload.get("a", []))
        last_update_id = end_id
        replayed += 1

        top_bids, top_asks = best_levels(bids, asks, args.levels)
        best_bid = top_bids[0][0] if top_bids else None
        best_ask = top_asks[0][0] if top_asks else None
        mid = (best_bid + best_ask) / 2.0 if best_bid is not None and best_ask is not None else None
        event_time = payload.get("E")
        event_dt = datetime.fromtimestamp(event_time / 1000).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3] if event_time else "N/A"

        print(f"step {replayed}: E={event_dt} U={start_id} u={end_id} pu={prev_end_id}")
        print(f"  best bid={best_bid:.2f} best ask={best_ask:.2f} mid={mid:.2f}")
        print_book_table(top_bids, top_asks)
        print_changes(bid_changes + ask_changes, args.show_changes)

        related_trades = trade_lookup.get(event_time, [])
        for trade in related_trades:
            side = "sell" if trade.get("m") else "buy"
            print(f"  trade: px={trade.get('p')} qty={trade.get('q')} side={side}")
        print()

        if replayed >= args.steps:
            break

    if replayed == 0:
        print("No diff records were replayed. Check whether snapshot/diff files line up.")


if __name__ == "__main__":
    main()
raise SystemExit(
    "Deprecated script: use the new A-S workflow instead of the old replay helper."
)
