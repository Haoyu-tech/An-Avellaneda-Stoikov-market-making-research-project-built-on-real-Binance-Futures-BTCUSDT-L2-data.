import argparse
import json
import math
import random
from dataclasses import dataclass
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


def best_bid_ask(bids: dict[float, float], asks: dict[float, float]) -> tuple[float | None, float | None]:
    bid = max(bids) if bids else None
    ask = min(asks) if asks else None
    return bid, ask


def floor_to_tick(price: float, tick_size: float) -> float:
    return math.floor(price / tick_size) * tick_size


def ceil_to_tick(price: float, tick_size: float) -> float:
    return math.ceil(price / tick_size) * tick_size


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def fee_aware_min_half_spread(mid_price: float, maker_fee_rate: float, fee_spread_multiplier: float) -> float:
    if mid_price <= 0 or maker_fee_rate <= 0 or fee_spread_multiplier <= 0:
        return 0.0
    # A full maker round trip pays fees on both the buy and sell legs.
    return mid_price * maker_fee_rate * fee_spread_multiplier


@dataclass
class BookEvent:
    event_time_ms: int
    best_bid: float
    best_bid_qty: float
    best_ask: float
    best_ask_qty: float
    mid: float
    spread: float


@dataclass
class AccountState:
    cash_usdt: float
    position_btc: float
    fees_paid_usdt: float
    inventory_cost_usdt: float
    realized_gross_pnl_usdt: float
    max_equity_usdt: float
    max_drawdown_pct: float


@dataclass
class RestingOrder:
    side: str
    price: float
    size: float
    queue_ahead: float
    placed_time_ms: int


@dataclass
class PendingOrder:
    side: str
    price: float
    size: float
    activate_time_ms: int


@dataclass
class OrderController:
    side: str
    active_order: RestingOrder | None = None
    pending_order: PendingOrder | None = None
    cancel_time_ms: int | None = None


def round_down_qty(qty: float, step_size: float) -> float:
    if step_size <= 0:
        return qty
    return math.floor(qty / step_size) * step_size


def normalize_inventory_state(account: AccountState, eps: float = 1e-12) -> None:
    if abs(account.position_btc) < eps:
        account.position_btc = 0.0
        account.inventory_cost_usdt = 0.0
    if abs(account.inventory_cost_usdt) < eps:
        account.inventory_cost_usdt = 0.0


def apply_inventory_fill(account: AccountState, side: str, fill_price: float, fill_qty: float) -> None:
    if fill_qty <= 0:
        return

    position = account.position_btc
    cost = account.inventory_cost_usdt

    if side == "buy":
        if position >= 0:
            account.position_btc = position + fill_qty
            account.inventory_cost_usdt = cost + fill_price * fill_qty
        else:
            cover_qty = min(fill_qty, -position)
            avg_short_price = cost / position
            account.realized_gross_pnl_usdt += (avg_short_price - fill_price) * cover_qty
            account.position_btc = position + cover_qty
            account.inventory_cost_usdt = cost + avg_short_price * cover_qty

            remaining_qty = fill_qty - cover_qty
            normalize_inventory_state(account)
            if remaining_qty > 0:
                account.position_btc += remaining_qty
                account.inventory_cost_usdt += fill_price * remaining_qty
    else:
        if position <= 0:
            account.position_btc = position - fill_qty
            account.inventory_cost_usdt = cost - fill_price * fill_qty
        else:
            close_qty = min(fill_qty, position)
            avg_long_price = cost / position
            account.realized_gross_pnl_usdt += (fill_price - avg_long_price) * close_qty
            account.position_btc = position - close_qty
            account.inventory_cost_usdt = cost - avg_long_price * close_qty

            remaining_qty = fill_qty - close_qty
            normalize_inventory_state(account)
            if remaining_qty > 0:
                account.position_btc -= remaining_qty
                account.inventory_cost_usdt -= fill_price * remaining_qty

    normalize_inventory_state(account)


def same_order_config(order: RestingOrder | PendingOrder | None, price: float | None, size: float, min_order_size: float) -> bool:
    if order is None:
        return price is None and size < min_order_size
    if price is None or size < min_order_size:
        return False
    return order.price == price and order.size == size


def update_queue_from_book(order: RestingOrder | None, event: BookEvent) -> float:
    if order is None:
        return 0.0
    old_queue = order.queue_ahead
    if order.side == "buy":
        if order.price > event.best_bid:
            order.queue_ahead = 0.0
        elif order.price == event.best_bid:
            order.queue_ahead = min(order.queue_ahead, event.best_bid_qty)
    else:
        if order.price < event.best_ask:
            order.queue_ahead = 0.0
        elif order.price == event.best_ask:
            order.queue_ahead = min(order.queue_ahead, event.best_ask_qty)
    return max(0.0, old_queue - order.queue_ahead)


def activate_pending_order(
    pending: PendingOrder,
    reference_event: BookEvent,
) -> RestingOrder | None:
    return make_resting_order(
        side=pending.side,
        price=pending.price,
        size=pending.size,
        best_bid=reference_event.best_bid,
        best_bid_qty=reference_event.best_bid_qty,
        best_ask=reference_event.best_ask,
        best_ask_qty=reference_event.best_ask_qty,
        placed_time_ms=pending.activate_time_ms,
    )


def advance_order_controller(
    controller: OrderController,
    time_ms: int,
    reference_event: BookEvent,
    stats: dict[str, float],
) -> None:
    if controller.active_order is not None and controller.cancel_time_ms is not None and controller.cancel_time_ms <= time_ms:
        stats["cancelled_orders"] += 1
        stats["cancelled_qty"] += controller.active_order.size
        controller.active_order = None
        controller.cancel_time_ms = None

    if controller.pending_order is not None and controller.pending_order.activate_time_ms <= time_ms and controller.active_order is None:
        activated = activate_pending_order(controller.pending_order, reference_event)
        if activated is not None:
            controller.active_order = activated
            stats["activated_orders"] += 1
            stats["activated_qty"] += activated.size
        controller.pending_order = None


def schedule_order_update(
    controller: OrderController,
    target_price: float | None,
    target_size: float,
    now_ms: int,
    min_order_size: float,
    order_latency_ms: int,
    cancel_latency_ms: int,
    stats: dict[str, float],
) -> None:
    has_target = target_price is not None and target_size >= min_order_size
    active = controller.active_order
    pending = controller.pending_order

    if active is not None and controller.cancel_time_ms is None and same_order_config(active, target_price, target_size, min_order_size):
        stats["quote_no_change_events"] += 1
        return
    if active is None and pending is not None and same_order_config(pending, target_price, target_size, min_order_size):
        stats["quote_no_change_events"] += 1
        return

    stats["quote_refresh_events"] += 1

    if active is None:
        if not has_target:
            if pending is not None:
                stats["cancelled_pending_orders"] += 1
                stats["cancelled_pending_qty"] += pending.size
                controller.pending_order = None
            return
        activate_at = now_ms + order_latency_ms
        if pending is None:
            stats["submit_requests"] += 1
        else:
            stats["pending_replacements"] += 1
        controller.pending_order = PendingOrder(
            side=controller.side,
            price=target_price,
            size=target_size,
            activate_time_ms=activate_at,
        )
        return

    if controller.cancel_time_ms is None:
        controller.cancel_time_ms = now_ms + cancel_latency_ms
        stats["cancel_requests"] += 1
        if has_target:
            stats["replace_requests"] += 1

    if has_target:
        activate_at = controller.cancel_time_ms + order_latency_ms
        if pending is None:
            stats["submit_requests"] += 1
        else:
            stats["pending_replacements"] += 1
        controller.pending_order = PendingOrder(
            side=controller.side,
            price=target_price,
            size=target_size,
            activate_time_ms=activate_at,
        )
    elif pending is not None:
        stats["cancelled_pending_orders"] += 1
        stats["cancelled_pending_qty"] += pending.size
        controller.pending_order = None


def make_resting_order(
    side: str,
    price: float,
    size: float,
    best_bid: float,
    best_bid_qty: float,
    best_ask: float,
    best_ask_qty: float,
    placed_time_ms: int,
) -> RestingOrder | None:
    if size <= 0:
        return None
    if side == "buy":
        queue_ahead = best_bid_qty if price >= best_bid else 0.0
    else:
        queue_ahead = best_ask_qty if price <= best_ask else 0.0
    return RestingOrder(side, price, size, queue_ahead, placed_time_ms)


def refresh_resting_order(
    current_order: RestingOrder | None,
    side: str,
    target_price: float,
    target_size: float,
    event: BookEvent,
    min_order_size: float,
) -> RestingOrder | None:
    if target_size < min_order_size:
        return None
    if current_order is None:
        return make_resting_order(
            side=side,
            price=target_price,
            size=target_size,
            best_bid=event.best_bid,
            best_bid_qty=event.best_bid_qty,
            best_ask=event.best_ask,
            best_ask_qty=event.best_ask_qty,
            placed_time_ms=event.event_time_ms,
        )

    if current_order.price == target_price:
        current_order.size = target_size
        return current_order

    return make_resting_order(
        side=side,
        price=target_price,
        size=target_size,
        best_bid=event.best_bid,
        best_bid_qty=event.best_bid_qty,
        best_ask=event.best_ask,
        best_ask_qty=event.best_ask_qty,
        placed_time_ms=event.event_time_ms,
    )


def process_trade(
    trade: dict,
    bid_order: RestingOrder | None,
    ask_order: RestingOrder | None,
    account: AccountState,
    maker_fee_rate: float,
    min_order_size: float,
    qty_step: float,
    fill_log: list[dict],
    stats: dict[str, float],
) -> tuple[RestingOrder | None, RestingOrder | None]:
    seller_aggressive = trade["seller_aggressive"]
    remaining_trade_qty = trade["qty"]

    if seller_aggressive and bid_order is not None and bid_order.size >= min_order_size and bid_order.price >= trade["price"]:
        consume = min(bid_order.queue_ahead, remaining_trade_qty)
        bid_order.queue_ahead -= consume
        remaining_trade_qty -= consume
        stats["queue_consumed_by_trades_qty"] += consume
        fill_qty = round_down_qty(min(bid_order.size, remaining_trade_qty), qty_step)
        if fill_qty >= min_order_size and bid_order.queue_ahead <= 0:
            gross = bid_order.price * fill_qty
            fee = gross * maker_fee_rate
            apply_inventory_fill(account, side="buy", fill_price=bid_order.price, fill_qty=fill_qty)
            account.cash_usdt -= gross + fee
            account.fees_paid_usdt += fee
            bid_order.size = round_down_qty(max(0.0, bid_order.size - fill_qty), qty_step)
            fill_log.append(
                {
                    "time_ms": trade["time_ms"],
                    "side": "buy",
                    "fill_price": bid_order.price,
                    "fill_qty": fill_qty,
                    "trade_price": trade["price"],
                    "position_btc": account.position_btc,
                    "cash_usdt": account.cash_usdt,
                    "fee_usdt": fee,
                    "queue_wait_cleared": True,
                }
            )
            stats["fill_qty"] += fill_qty
            if bid_order.size < min_order_size:
                bid_order = None

    elif (not seller_aggressive) and ask_order is not None and ask_order.size >= min_order_size and ask_order.price <= trade["price"]:
        consume = min(ask_order.queue_ahead, remaining_trade_qty)
        ask_order.queue_ahead -= consume
        remaining_trade_qty -= consume
        stats["queue_consumed_by_trades_qty"] += consume
        fill_qty = round_down_qty(min(ask_order.size, remaining_trade_qty), qty_step)
        if fill_qty >= min_order_size and ask_order.queue_ahead <= 0:
            gross = ask_order.price * fill_qty
            fee = gross * maker_fee_rate
            apply_inventory_fill(account, side="sell", fill_price=ask_order.price, fill_qty=fill_qty)
            account.cash_usdt += gross - fee
            account.fees_paid_usdt += fee
            ask_order.size = round_down_qty(max(0.0, ask_order.size - fill_qty), qty_step)
            fill_log.append(
                {
                    "time_ms": trade["time_ms"],
                    "side": "sell",
                    "fill_price": ask_order.price,
                    "fill_qty": fill_qty,
                    "trade_price": trade["price"],
                    "position_btc": account.position_btc,
                    "cash_usdt": account.cash_usdt,
                    "fee_usdt": fee,
                    "queue_wait_cleared": True,
                }
            )
            stats["fill_qty"] += fill_qty
            if ask_order.size < min_order_size:
                ask_order = None

    return bid_order, ask_order


def reconstruct_book_events(session_dir: Path) -> list[BookEvent]:
    snapshot_records = load_ndjson(session_dir / "snapshot.ndjson")
    if not snapshot_records:
        raise ValueError(f"No snapshot found in {session_dir}")

    snapshot = snapshot_records[-1]["payload"]
    bids = build_book(snapshot["bids"])
    asks = build_book(snapshot["asks"])
    last_update_id = int(snapshot["lastUpdateId"])

    events: list[BookEvent] = []
    started = False
    for record in load_ndjson(session_dir / "depth.ndjson"):
        payload = record.get("payload", {})
        event_time = payload.get("E")
        start_id = payload.get("U")
        end_id = payload.get("u")
        if event_time is None or start_id is None or end_id is None:
            continue

        start_id = int(start_id)
        end_id = int(end_id)

        if end_id < last_update_id:
            continue
        if not started:
            if not (start_id <= last_update_id + 1 <= end_id):
                continue
            started = True

        apply_updates(bids, payload.get("b", []))
        apply_updates(asks, payload.get("a", []))
        last_update_id = end_id

        bid, ask = best_bid_ask(bids, asks)
        if bid is None or ask is None or ask <= bid:
            continue
        mid = 0.5 * (bid + ask)
        events.append(
            BookEvent(
                event_time_ms=int(event_time),
                best_bid=bid,
                best_bid_qty=bids.get(bid, 0.0),
                best_ask=ask,
                best_ask_qty=asks.get(ask, 0.0),
                mid=mid,
                spread=ask - bid,
            )
        )
    if not events:
        raise ValueError("No reconstructable book events were produced from the session.")
    return events


def load_trades(session_dir: Path) -> list[dict]:
    trades_path = session_dir / "aggtrade.ndjson"
    if not trades_path.exists():
        return []
    trades = []
    for record in load_ndjson(trades_path):
        payload = record.get("payload", {})
        trade_time = payload.get("T") or payload.get("E")
        if trade_time is None:
            continue
        trades.append(
            {
                "time_ms": int(trade_time),
                "price": float(payload["p"]),
                "qty": float(payload["q"]),
                "seller_aggressive": bool(payload.get("m")),
            }
        )
    trades.sort(key=lambda item: item["time_ms"])
    return trades


def estimate_sigma(events: list[BookEvent], horizon_seconds: float) -> float:
    returns: list[float] = []
    prev_mid = None
    for event in events:
        if prev_mid is not None and event.mid > 0 and prev_mid > 0:
            returns.append(math.log(event.mid / prev_mid))
        prev_mid = event.mid
    if not returns:
        return 1e-6
    mean_sq = sum(r * r for r in returns) / len(returns)
    sigma_event = math.sqrt(mean_sq)
    event_duration = horizon_seconds / max(1, len(events))
    if event_duration <= 0:
        return sigma_event
    return sigma_event / math.sqrt(event_duration)


def truncate_events_and_trades(
    events: list[BookEvent],
    trades: list[dict],
    max_backtest_seconds: float,
) -> tuple[list[BookEvent], list[dict]]:
    if max_backtest_seconds <= 0 or not events:
        return events, trades
    cutoff_ms = events[0].event_time_ms + int(max_backtest_seconds * 1000)
    clipped_events = [event for event in events if event.event_time_ms <= cutoff_ms]
    if not clipped_events:
        clipped_events = [events[0]]
    clipped_trades = [trade for trade in trades if trade["time_ms"] <= clipped_events[-1].event_time_ms]
    return clipped_events, clipped_trades


def estimate_sigma_from_slice(events: list[BookEvent]) -> float:
    if len(events) < 2:
        return 1e-6
    returns: list[float] = []
    prev_mid = events[0].mid
    for event in events[1:]:
        if event.mid > 0 and prev_mid > 0:
            returns.append(math.log(event.mid / prev_mid))
        prev_mid = event.mid
    if not returns:
        return 1e-6
    mean_sq = sum(r * r for r in returns) / len(returns)
    horizon_seconds = max((events[-1].event_time_ms - events[0].event_time_ms) / 1000.0, 1e-6)
    event_duration = horizon_seconds / max(1, len(events))
    return math.sqrt(mean_sq) / math.sqrt(max(event_duration, 1e-6))


def infer_tick_size(events: list[BookEvent]) -> float:
    diffs = []
    prev = None
    for event in events[:200]:
        for price in (event.best_bid, event.best_ask):
            if prev is not None:
                diff = abs(price - prev)
                if diff > 0:
                    diffs.append(diff)
            prev = price
    if not diffs:
        return 0.1
    tick = min(diffs)
    return max(0.1, round(tick, 8))


def build_event_lookup(events: list[BookEvent]) -> dict[int, BookEvent]:
    return {event.event_time_ms: event for event in events}


def estimate_k_from_trades(events: list[BookEvent], trades: list[dict], tick_size: float) -> float:
    if not trades:
        return 1.5
    event_times = [event.event_time_ms for event in events]
    event_idx = 0
    max_delta_ticks = 6
    horizon_seconds = max((events[-1].event_time_ms - events[0].event_time_ms) / 1000.0, 1e-6)
    hit_counts = [0 for _ in range(max_delta_ticks + 1)]

    for trade in trades:
        while event_idx + 1 < len(event_times) and event_times[event_idx + 1] <= trade["time_ms"]:
            event_idx += 1
        event = events[event_idx]

        for delta_ticks in range(max_delta_ticks + 1):
            price_offset = delta_ticks * tick_size
            if trade["seller_aggressive"]:
                quote_price = event.best_bid - price_offset
                if trade["price"] <= quote_price:
                    hit_counts[delta_ticks] += 1
            else:
                quote_price = event.best_ask + price_offset
                if trade["price"] >= quote_price:
                    hit_counts[delta_ticks] += 1

    points: list[tuple[float, float]] = []
    for delta_ticks, hits in enumerate(hit_counts):
        intensity = hits / horizon_seconds
        if intensity > 0:
            points.append((float(delta_ticks), math.log(intensity)))

    if len(points) < 2:
        return 1.5

    xs = [x for x, _ in points]
    ys = [y for _, y in points]
    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    denom = sum((x - mean_x) ** 2 for x in xs)
    if denom <= 0:
        return 1.5
    slope = sum((x - mean_x) * (y - mean_y) for x, y in points) / denom
    fitted_k = max(-slope, 0.0)
    return clamp(fitted_k, 0.1, 50.0)


def fit_intensity_curve(events: list[BookEvent], trades: list[dict], tick_size: float, max_delta_ticks: int = 6) -> tuple[float, float]:
    if not trades or not events:
        return 0.0, 1.5
    event_times = [event.event_time_ms for event in events]
    event_idx = 0
    horizon_seconds = max((events[-1].event_time_ms - events[0].event_time_ms) / 1000.0, 1e-6)
    hit_counts = [0 for _ in range(max_delta_ticks + 1)]

    for trade in trades:
        while event_idx + 1 < len(event_times) and event_times[event_idx + 1] <= trade["time_ms"]:
            event_idx += 1
        event = events[event_idx]
        for delta_ticks in range(max_delta_ticks + 1):
            price_offset = delta_ticks * tick_size
            if trade["seller_aggressive"]:
                if trade["price"] <= event.best_bid - price_offset:
                    hit_counts[delta_ticks] += 1
            else:
                if trade["price"] >= event.best_ask + price_offset:
                    hit_counts[delta_ticks] += 1

    points: list[tuple[float, float]] = []
    intensities: list[float] = []
    for delta_ticks, hits in enumerate(hit_counts):
        intensity = hits / horizon_seconds
        if intensity > 0:
            points.append((float(delta_ticks), math.log(intensity)))
            intensities.append(intensity)
    if len(points) < 2:
        base_intensity = intensities[0] if intensities else 0.0
        return base_intensity, 1.5

    xs = [x for x, _ in points]
    ys = [y for _, y in points]
    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    denom = sum((x - mean_x) ** 2 for x in xs)
    if denom <= 0:
        base_intensity = intensities[0] if intensities else 0.0
        return base_intensity, 1.5
    slope = sum((x - mean_x) * (y - mean_y) for x, y in points) / denom
    intercept = mean_y - slope * mean_x
    fitted_k = clamp(max(-slope, 0.0), 0.1, 50.0)
    base_intensity = max(math.exp(intercept), 0.0)
    return base_intensity, fitted_k


def estimate_dynamic_params(
    events: list[BookEvent],
    trades: list[dict],
    tick_size: float,
    window_seconds: float,
) -> list[dict]:
    params: list[dict] = []
    for idx, event in enumerate(events):
        window_start_ms = event.event_time_ms - int(window_seconds * 1000)
        event_slice = [item for item in events[: idx + 1] if item.event_time_ms >= window_start_ms]
        trade_slice = [item for item in trades if window_start_ms <= item["time_ms"] <= event.event_time_ms]
        sigma = estimate_sigma_from_slice(event_slice)
        intensity, k = fit_intensity_curve(event_slice, trade_slice, tick_size)
        params.append(
            {
                "time_ms": event.event_time_ms,
                "sigma": sigma,
                "intensity": intensity,
                "k": k,
            }
        )
    return params


def estimate_gamma_auto(
    events: list[BookEvent],
    sigma: float,
    initial_cash: float,
    inventory_limit: float,
    risk_fraction: float,
) -> float:
    horizon_seconds = max((events[-1].event_time_ms - events[0].event_time_ms) / 1000.0, 1.0)
    mid = events[-1].mid
    inventory_risk_usdt = inventory_limit * mid * sigma * math.sqrt(horizon_seconds)
    budget_usdt = initial_cash * risk_fraction
    if inventory_risk_usdt <= 0:
        return 0.1
    gamma = budget_usdt / max(inventory_risk_usdt * mid, 1e-9)
    return clamp(gamma, 0.01, 2.0)


def gamma_grid_candidates(base_gamma: float) -> list[float]:
    rng = random.Random(42)
    sampled = [rng.uniform(0.0, 1.0) for _ in range(50)]
    candidates = sampled + [clamp(base_gamma, 0.0, 1.0)]
    unique = sorted({max(value, 1e-6) for value in candidates})
    return unique


def backtest_score(summary: dict) -> float:
    inventory_penalty = abs(summary["final_position_btc"]) * summary["final_mid"] * 0.05
    drawdown_penalty = summary["max_drawdown_pct"] * 0.1
    fill_bonus = summary["fills"] * 0.001
    return summary["net_pnl_usdt"] - inventory_penalty - drawdown_penalty + fill_bonus - summary["gamma"] * 1e-6


def simulate_as_strategy(
    events: list[BookEvent],
    trades: list[dict],
    gamma: float | None,
    k: float | None,
    order_size: float,
    inventory_limit: float,
    tick_size: float,
    initial_cash: float,
    maker_fee_rate: float,
    min_order_size: float,
    qty_step: float,
    max_order_notional: float,
    risk_fraction: float,
    dynamic_window_seconds: float,
    fee_spread_multiplier: float,
    order_latency_ms: int,
    cancel_latency_ms: int,
    max_backtest_seconds: float,
) -> tuple[dict, list[dict], list[dict]]:
    events, trades = truncate_events_and_trades(events, trades, max_backtest_seconds)
    start_ms = events[0].event_time_ms
    end_ms = events[-1].event_time_ms
    horizon_seconds = max((end_ms - start_ms) / 1000.0, 1e-6)
    sigma = estimate_sigma(events, horizon_seconds=horizon_seconds)

    effective_order_size = order_size
    if max_order_notional > 0:
        effective_order_size = min(effective_order_size, max_order_notional / events[0].mid)
    effective_order_size = round_down_qty(effective_order_size, qty_step)
    if effective_order_size < min_order_size:
        raise ValueError("Order size is smaller than the configured minimum order size.")

    dynamic_params = estimate_dynamic_params(events, trades, tick_size, dynamic_window_seconds)
    avg_sigma = sum(item["sigma"] for item in dynamic_params) / len(dynamic_params)
    avg_intensity = sum(item["intensity"] for item in dynamic_params) / len(dynamic_params)
    avg_k = sum(item["k"] for item in dynamic_params) / len(dynamic_params)

    auto_k = avg_k if k is None else k
    if gamma is None:
        base_gamma = estimate_gamma_auto(events, avg_sigma, initial_cash, inventory_limit, risk_fraction)
        best_result = None
        grid_results = []
        for candidate_gamma in gamma_grid_candidates(base_gamma):
            candidate_summary, candidate_fills, candidate_curve = simulate_as_strategy(
                events=events,
                trades=trades,
                gamma=candidate_gamma,
                k=k,
                order_size=order_size,
                inventory_limit=inventory_limit,
                tick_size=tick_size,
                initial_cash=initial_cash,
                maker_fee_rate=maker_fee_rate,
                min_order_size=min_order_size,
                qty_step=qty_step,
                max_order_notional=max_order_notional,
                risk_fraction=risk_fraction,
                dynamic_window_seconds=dynamic_window_seconds,
                fee_spread_multiplier=fee_spread_multiplier,
                order_latency_ms=order_latency_ms,
                cancel_latency_ms=cancel_latency_ms,
                max_backtest_seconds=max_backtest_seconds,
            )
            score = backtest_score(candidate_summary)
            grid_results.append(
                {
                    "gamma": candidate_gamma,
                    "score": score,
                    "fills": candidate_summary["fills"],
                    "net_pnl_usdt": candidate_summary["net_pnl_usdt"],
                }
            )
            if best_result is None or score > best_result[0]:
                best_result = (score, candidate_summary, candidate_fills, candidate_curve, grid_results)
        assert best_result is not None
        best_summary = best_result[1]
        best_summary["gamma_source"] = "grid_search"
        best_summary["k_source"] = "intensity_fit" if k is None else "manual"
        best_summary["gamma_grid_results"] = grid_results
        return best_summary, best_result[2], best_result[3]

    auto_gamma = gamma

    account = AccountState(
        cash_usdt=initial_cash,
        position_btc=0.0,
        fees_paid_usdt=0.0,
        inventory_cost_usdt=0.0,
        realized_gross_pnl_usdt=0.0,
        max_equity_usdt=initial_cash,
        max_drawdown_pct=0.0,
    )
    trades_idx = 0
    fill_log: list[dict] = []
    equity_curve: list[dict] = []
    bid_controller = OrderController(side="buy")
    ask_controller = OrderController(side="sell")
    execution_stats: dict[str, float] = {
        "quote_refresh_events": 0.0,
        "quote_no_change_events": 0.0,
        "submit_requests": 0.0,
        "replace_requests": 0.0,
        "cancel_requests": 0.0,
        "pending_replacements": 0.0,
        "activated_orders": 0.0,
        "activated_qty": 0.0,
        "cancelled_orders": 0.0,
        "cancelled_qty": 0.0,
        "cancelled_pending_orders": 0.0,
        "cancelled_pending_qty": 0.0,
        "queue_consumed_by_book_qty": 0.0,
        "queue_consumed_by_trades_qty": 0.0,
        "fill_qty": 0.0,
    }
    quote_horizon = 1.0
    prev_event_time_ms = events[0].event_time_ms
    last_reference_event = events[0]

    for event in events:
        while trades_idx < len(trades) and trades[trades_idx]["time_ms"] < event.event_time_ms:
            if trades[trades_idx]["time_ms"] >= prev_event_time_ms:
                advance_order_controller(
                    bid_controller,
                    trades[trades_idx]["time_ms"],
                    last_reference_event,
                    execution_stats,
                )
                advance_order_controller(
                    ask_controller,
                    trades[trades_idx]["time_ms"],
                    last_reference_event,
                    execution_stats,
                )
                bid_controller.active_order, ask_controller.active_order = process_trade(
                    trade=trades[trades_idx],
                    bid_order=bid_controller.active_order,
                    ask_order=ask_controller.active_order,
                    account=account,
                    maker_fee_rate=maker_fee_rate,
                    min_order_size=min_order_size,
                    qty_step=qty_step,
                    fill_log=fill_log,
                    stats=execution_stats,
                )
            trades_idx += 1

        advance_order_controller(bid_controller, event.event_time_ms, event, execution_stats)
        advance_order_controller(ask_controller, event.event_time_ms, event, execution_stats)
        execution_stats["queue_consumed_by_book_qty"] += update_queue_from_book(bid_controller.active_order, event)
        execution_stats["queue_consumed_by_book_qty"] += update_queue_from_book(ask_controller.active_order, event)

        event_idx = len(equity_curve)
        dyn = dynamic_params[event_idx]
        sigma_now = dyn["sigma"]
        k_now = k if k is not None else dyn["k"]
        intensity_now = dyn["intensity"]
        reservation = event.mid - account.position_btc * auto_gamma * (sigma_now**2) * quote_horizon
        raw_half_spread = 0.5 * (
            auto_gamma * (sigma_now**2) * quote_horizon + (2.0 / auto_gamma) * math.log(1.0 + auto_gamma / k_now)
        )
        min_half_spread_from_fees = fee_aware_min_half_spread(
            mid_price=event.mid,
            maker_fee_rate=maker_fee_rate,
            fee_spread_multiplier=fee_spread_multiplier,
        )
        half_spread = max(raw_half_spread, 0.5 * event.spread, min_half_spread_from_fees)

        bid_quote = floor_to_tick(min(reservation - half_spread, event.best_bid), tick_size)
        ask_quote = ceil_to_tick(max(reservation + half_spread, event.best_ask), tick_size)

        max_buy_size = round_down_qty(account.cash_usdt / max(bid_quote * (1.0 + maker_fee_rate), 1e-9), qty_step)
        max_buy_size = clamp(max_buy_size, 0.0, max(0.0, inventory_limit - account.position_btc))
        buy_order_size = round_down_qty(min(effective_order_size, max_buy_size), qty_step)

        max_sell_size = clamp(account.position_btc + inventory_limit, 0.0, 2.0 * inventory_limit)
        sell_order_size = round_down_qty(min(effective_order_size, max_sell_size), qty_step)

        schedule_order_update(
            controller=bid_controller,
            target_price=bid_quote,
            target_size=buy_order_size,
            now_ms=event.event_time_ms,
            min_order_size=min_order_size,
            order_latency_ms=order_latency_ms,
            cancel_latency_ms=cancel_latency_ms,
            stats=execution_stats,
        )
        schedule_order_update(
            controller=ask_controller,
            target_price=ask_quote,
            target_size=sell_order_size,
            now_ms=event.event_time_ms,
            min_order_size=min_order_size,
            order_latency_ms=order_latency_ms,
            cancel_latency_ms=cancel_latency_ms,
            stats=execution_stats,
        )

        while trades_idx < len(trades) and trades[trades_idx]["time_ms"] == event.event_time_ms:
            advance_order_controller(
                bid_controller,
                trades[trades_idx]["time_ms"],
                event,
                execution_stats,
            )
            advance_order_controller(
                ask_controller,
                trades[trades_idx]["time_ms"],
                event,
                execution_stats,
            )
            bid_controller.active_order, ask_controller.active_order = process_trade(
                trade=trades[trades_idx],
                bid_order=bid_controller.active_order,
                ask_order=ask_controller.active_order,
                account=account,
                maker_fee_rate=maker_fee_rate,
                min_order_size=min_order_size,
                qty_step=qty_step,
                fill_log=fill_log,
                stats=execution_stats,
            )
            trades_idx += 1

        equity_usdt = account.cash_usdt + account.position_btc * event.mid
        if equity_usdt > account.max_equity_usdt:
            account.max_equity_usdt = equity_usdt
        if account.max_equity_usdt > 0:
            drawdown_pct = (account.max_equity_usdt - equity_usdt) / account.max_equity_usdt * 100.0
            account.max_drawdown_pct = max(account.max_drawdown_pct, drawdown_pct)
        equity_curve.append(
            {
                "time_ms": event.event_time_ms,
                "best_bid": event.best_bid,
                "best_ask": event.best_ask,
                "mid": event.mid,
                "sigma": sigma_now,
                "intensity": intensity_now,
                "k": k_now,
                "raw_half_spread": raw_half_spread,
                "min_half_spread_from_fees": min_half_spread_from_fees,
                "effective_half_spread": half_spread,
                "bid_quote": bid_controller.active_order.price if bid_controller.active_order is not None else None,
                "ask_quote": ask_controller.active_order.price if ask_controller.active_order is not None else None,
                "bid_target_quote": bid_quote if buy_order_size >= min_order_size else None,
                "ask_target_quote": ask_quote if sell_order_size >= min_order_size else None,
                "bid_queue_ahead": bid_controller.active_order.queue_ahead if bid_controller.active_order is not None else None,
                "ask_queue_ahead": ask_controller.active_order.queue_ahead if ask_controller.active_order is not None else None,
                "bid_cancel_pending": bid_controller.cancel_time_ms is not None,
                "ask_cancel_pending": ask_controller.cancel_time_ms is not None,
                "bid_pending_activate_ms": bid_controller.pending_order.activate_time_ms if bid_controller.pending_order is not None else None,
                "ask_pending_activate_ms": ask_controller.pending_order.activate_time_ms if ask_controller.pending_order is not None else None,
                "cash_usdt": account.cash_usdt,
                "position_btc": account.position_btc,
                "equity_usdt": equity_usdt,
            }
        )
        prev_event_time_ms = event.event_time_ms
        last_reference_event = event

    final_mid = events[-1].mid
    inventory_value = account.position_btc * final_mid
    unrealized_inventory_pnl = inventory_value - account.inventory_cost_usdt
    gross_pnl_before_fees = account.realized_gross_pnl_usdt + unrealized_inventory_pnl
    net_pnl_after_fees = gross_pnl_before_fees - account.fees_paid_usdt
    final_equity = account.cash_usdt + inventory_value
    pnl = final_equity - initial_cash
    pnl_breakdown = {
        "realized_gross_pnl_usdt": account.realized_gross_pnl_usdt,
        "unrealized_inventory_pnl_usdt": unrealized_inventory_pnl,
        "gross_pnl_before_fees_usdt": gross_pnl_before_fees,
        "fees_paid_usdt": account.fees_paid_usdt,
        "net_pnl_after_fees_usdt": net_pnl_after_fees,
        "inventory_cost_usdt": account.inventory_cost_usdt,
        "inventory_value_usdt": inventory_value,
    }
    execution_summary = {
        "order_latency_ms": order_latency_ms,
        "cancel_latency_ms": cancel_latency_ms,
        "quote_refresh_events": int(execution_stats["quote_refresh_events"]),
        "quote_no_change_events": int(execution_stats["quote_no_change_events"]),
        "submit_requests": int(execution_stats["submit_requests"]),
        "replace_requests": int(execution_stats["replace_requests"]),
        "cancel_requests": int(execution_stats["cancel_requests"]),
        "pending_replacements": int(execution_stats["pending_replacements"]),
        "activated_orders": int(execution_stats["activated_orders"]),
        "activated_qty": execution_stats["activated_qty"],
        "cancelled_orders": int(execution_stats["cancelled_orders"]),
        "cancelled_qty": execution_stats["cancelled_qty"],
        "cancelled_pending_orders": int(execution_stats["cancelled_pending_orders"]),
        "cancelled_pending_qty": execution_stats["cancelled_pending_qty"],
        "queue_consumed_by_book_qty": execution_stats["queue_consumed_by_book_qty"],
        "queue_consumed_by_trades_qty": execution_stats["queue_consumed_by_trades_qty"],
        "fill_qty": execution_stats["fill_qty"],
        "unfilled_active_orders_end": int(bid_controller.active_order is not None) + int(ask_controller.active_order is not None),
        "unfilled_pending_orders_end": int(bid_controller.pending_order is not None) + int(ask_controller.pending_order is not None),
        "unfilled_active_qty_end": (bid_controller.active_order.size if bid_controller.active_order is not None else 0.0)
        + (ask_controller.active_order.size if ask_controller.active_order is not None else 0.0),
        "unfilled_pending_qty_end": (bid_controller.pending_order.size if bid_controller.pending_order is not None else 0.0)
        + (ask_controller.pending_order.size if ask_controller.pending_order is not None else 0.0),
        "fill_rate_vs_activated_qty": execution_stats["fill_qty"] / max(execution_stats["activated_qty"], 1e-9),
    }
    summary = {
        "events": len(events),
        "trades_seen": len(trades),
        "fills": len(fill_log),
        "final_position_btc": account.position_btc,
        "final_cash_usdt": account.cash_usdt,
        "final_mid": final_mid,
        "inventory_value_usdt": inventory_value,
        "final_equity_usdt": final_equity,
        "net_pnl_usdt": pnl,
        "roi_pct": (pnl / initial_cash * 100.0) if initial_cash > 0 else 0.0,
        "fees_paid_usdt": account.fees_paid_usdt,
        "realized_gross_pnl_usdt": account.realized_gross_pnl_usdt,
        "unrealized_inventory_pnl_usdt": unrealized_inventory_pnl,
        "gross_pnl_before_fees_usdt": gross_pnl_before_fees,
        "max_drawdown_pct": account.max_drawdown_pct,
        "estimated_sigma_per_sqrt_second": avg_sigma,
        "estimated_intensity_per_second": avg_intensity,
        "gamma": auto_gamma,
        "k": auto_k,
        "gamma_source": "manual",
        "k_source": "intensity_fit" if k is None else "manual",
        "configured_order_size_btc": order_size,
        "effective_order_size_btc": effective_order_size,
        "inventory_limit_btc": inventory_limit,
        "tick_size": tick_size,
        "initial_cash_usdt": initial_cash,
        "maker_fee_rate": maker_fee_rate,
        "min_order_size_btc": min_order_size,
        "qty_step_btc": qty_step,
        "max_order_notional_usdt": max_order_notional,
        "risk_fraction": risk_fraction,
        "dynamic_window_seconds": dynamic_window_seconds,
        "fee_spread_multiplier": fee_spread_multiplier,
        "avg_min_half_spread_from_fees": sum(
            item["min_half_spread_from_fees"] for item in equity_curve
        )
        / max(1, len(equity_curve)),
        "quote_horizon": quote_horizon,
        "max_backtest_seconds": max_backtest_seconds,
        "model_variant": "continuous_as_unit_horizon",
        "pnl_breakdown": pnl_breakdown,
        "execution_stats": execution_summary,
    }
    return summary, fill_log, equity_curve


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a practical Avellaneda-Stoikov backtest on a collected L2 session.")
    parser.add_argument("--session-dir", type=str, required=True, help="Collected session directory.")
    parser.add_argument("--gamma", type=float, default=-1.0, help="Risk aversion parameter. Use negative value for auto.")
    parser.add_argument("--k", type=float, default=-1.0, help="Order arrival decay parameter. Use negative value for auto.")
    parser.add_argument("--order-size", type=float, default=0.003, help="Single fill size in BTC.")
    parser.add_argument("--inventory-limit", type=float, default=0.03, help="Maximum absolute inventory.")
    parser.add_argument("--tick-size", type=float, default=0.0, help="Price tick size. Use 0 to infer from data.")
    parser.add_argument("--initial-cash", type=float, default=1000.0, help="Initial cash in USDT.")
    parser.add_argument("--maker-fee-rate", type=float, default=0.0002, help="Maker fee rate.")
    parser.add_argument("--min-order-size", type=float, default=0.001, help="Minimum order size in BTC.")
    parser.add_argument("--qty-step", type=float, default=0.001, help="Order quantity step in BTC.")
    parser.add_argument("--max-order-notional", type=float, default=300.0, help="Maximum order notional in USDT.")
    parser.add_argument("--risk-fraction", type=float, default=0.02, help="Fraction of equity used to infer auto gamma.")
    parser.add_argument("--dynamic-window-seconds", type=float, default=10.0, help="Rolling window for dynamic sigma/intensity/k estimation.")
    parser.add_argument("--order-latency-ms", type=int, default=150, help="Delay before a new quote becomes active.")
    parser.add_argument("--cancel-latency-ms", type=int, default=100, help="Delay before a cancel/replace removes the old quote.")
    parser.add_argument("--max-backtest-seconds", type=float, default=0.0, help="Only use the first N seconds of the session. Use 0 for full session.")
    parser.add_argument(
        "--fee-spread-multiplier",
        type=float,
        default=1.0,
        help="Multiplier for the minimum half-spread needed to cover a maker-fee round trip.",
    )
    parser.add_argument("--output-json", type=str, default="", help="Optional output summary JSON path.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    session_dir = Path(args.session_dir)
    events = reconstruct_book_events(session_dir)
    trades = load_trades(session_dir)
    tick_size = args.tick_size if args.tick_size > 0 else infer_tick_size(events)
    gamma = args.gamma if args.gamma > 0 else None
    k = args.k if args.k > 0 else None

    summary, fill_log, equity_curve = simulate_as_strategy(
        events=events,
        trades=trades,
        gamma=gamma,
        k=k,
        order_size=args.order_size,
        inventory_limit=args.inventory_limit,
        tick_size=tick_size,
        initial_cash=args.initial_cash,
        maker_fee_rate=args.maker_fee_rate,
        min_order_size=args.min_order_size,
        qty_step=args.qty_step,
        max_order_notional=args.max_order_notional,
        risk_fraction=args.risk_fraction,
        dynamic_window_seconds=args.dynamic_window_seconds,
        fee_spread_multiplier=args.fee_spread_multiplier,
        order_latency_ms=args.order_latency_ms,
        cancel_latency_ms=args.cancel_latency_ms,
        max_backtest_seconds=args.max_backtest_seconds,
    )

    print("=" * 80)
    print("A-S Backtest Summary")
    print("=" * 80)
    for key, value in summary.items():
        if key in {"pnl_breakdown", "execution_stats"}:
            continue
        print(f"{key}: {value}")
    print("-" * 80)
    print("PnL breakdown:")
    for key, value in summary["pnl_breakdown"].items():
        print(f"{key}: {value}")
    print("-" * 80)
    print("Execution stats:")
    for key, value in summary["execution_stats"].items():
        print(f"{key}: {value}")
    print("-" * 80)
    print("first_fills:")
    for fill in fill_log[:10]:
        print(fill)

    if args.output_json:
        payload = {
            "summary": summary,
            "first_fills": fill_log[:100],
            "equity_curve": equity_curve,
        }
        output_path = Path(args.output_json)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
