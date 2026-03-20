import argparse
import asyncio
import contextlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
import websockets


FUTURES_WS_BASE = "wss://fstream.binance.com/stream?streams="
FUTURES_REST_BASE = "https://fapi.binance.com/fapi/v1/depth"
DEFAULT_DEPTH_LIMIT = 1000
DEFAULT_OUTPUT_ROOT = "data/as_l2"
DEFAULT_FLUSH_EVERY = 200
DEFAULT_FLUSH_INTERVAL = 1.0


class BufferedNdjsonWriter:
    def __init__(self, path: Path, flush_every: int, flush_interval: float) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.file_obj = path.open("a", encoding="utf-8", buffering=1024 * 1024)
        self.flush_every = max(1, flush_every)
        self.flush_interval = max(0.0, flush_interval)
        self.buffer: list[str] = []
        self.last_flush = time.monotonic()

    def write_record(self, record: dict) -> None:
        self.buffer.append(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
        now = time.monotonic()
        if len(self.buffer) >= self.flush_every or (
            self.flush_interval > 0 and now - self.last_flush >= self.flush_interval
        ):
            self.flush()

    def flush(self) -> None:
        if not self.buffer:
            return
        self.file_obj.write("".join(self.buffer))
        self.file_obj.flush()
        self.buffer.clear()
        self.last_flush = time.monotonic()

    def close(self) -> None:
        self.flush()
        self.file_obj.close()


def utc_now_text() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def local_now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def build_session_name(symbol: str) -> str:
    return f"{symbol.lower()}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def append_jsonl(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file_obj:
        file_obj.write(json.dumps(payload, ensure_ascii=False) + "\n")


def fetch_snapshot(session: requests.Session, symbol: str, limit: int) -> dict:
    response = session.get(
        FUTURES_REST_BASE,
        params={"symbol": symbol.upper(), "limit": limit},
        timeout=10,
    )
    response.raise_for_status()
    return response.json()


def build_ws_url(symbol: str, include_trades: bool) -> str:
    streams = [f"{symbol.lower()}@depth@100ms"]
    if include_trades:
        streams.append(f"{symbol.lower()}@aggTrade")
    return FUTURES_WS_BASE + "/".join(streams)


async def collect_l2_session(
    symbol: str,
    depth_limit: int,
    include_trades: bool,
    max_events: int,
    max_seconds: float,
    flush_every: int,
    flush_interval: float,
    quiet: bool,
    print_every: int,
    output_root: Path,
    session_name: str,
) -> None:
    symbol = symbol.upper()
    session_dir = output_root / symbol.lower() / session_name
    snapshot_path = session_dir / "snapshot.ndjson"
    depth_path = session_dir / "depth.ndjson"
    trades_path = session_dir / "aggtrade.ndjson"
    meta_path = session_dir / "meta.json"
    manifest_path = output_root / "sessions.jsonl"

    ws_url = build_ws_url(symbol, include_trades=include_trades)
    meta = {
        "session_name": session_name,
        "symbol": symbol,
        "market": "binance_futures",
        "started_at_utc": utc_now_text(),
        "snapshot_path": str(snapshot_path),
        "depth_path": str(depth_path),
        "trades_path": str(trades_path) if include_trades else "",
        "ws_url": ws_url,
        "rest_url": FUTURES_REST_BASE,
        "depth_limit": depth_limit,
        "max_events": max_events,
        "max_seconds": max_seconds,
        "include_trades": include_trades,
    }
    write_json(meta_path, meta)
    append_jsonl(manifest_path, meta)

    session = requests.Session()
    session.trust_env = False
    snapshot_file = BufferedNdjsonWriter(snapshot_path, flush_every=1, flush_interval=0)
    depth_file = BufferedNdjsonWriter(depth_path, flush_every=flush_every, flush_interval=flush_interval)
    trades_file = BufferedNdjsonWriter(trades_path, flush_every=flush_every, flush_interval=flush_interval) if include_trades else None

    try:
        if not quiet:
            print("=" * 80)
            print("A-S Model L2 Recorder")
            print("=" * 80)
            print(f"session:       {session_name}")
            print(f"symbol:        {symbol}")
            print(f"session dir:   {session_dir}")
            print(f"snapshot file: {snapshot_path}")
            print(f"depth file:    {depth_path}")
            if include_trades:
                print(f"trades file:   {trades_path}")
            print("Connecting websocket first so depth updates are buffered before snapshot.")
            print("-" * 80)

        event_count = 0
        trade_count = 0
        start_loop_time = asyncio.get_running_loop().time()
        async with websockets.connect(ws_url, ping_interval=20, ping_timeout=20, proxy=None) as websocket:
            queue: asyncio.Queue[dict | None] = asyncio.Queue()

            async def reader() -> None:
                try:
                    async for raw_message in websocket:
                        message = json.loads(raw_message)
                        await queue.put(
                            {
                                "local_time": local_now_text(),
                                "source": "websocket",
                                "stream": message.get("stream", ""),
                                "payload": message.get("data", {}),
                            }
                        )
                finally:
                    await queue.put(None)

            reader_task = asyncio.create_task(reader())

            try:
                snapshot = await asyncio.to_thread(fetch_snapshot, session, symbol, depth_limit)
                snapshot_file.write_record(
                    {
                        "local_time": local_now_text(),
                        "source": "rest",
                        "stream": "depth_snapshot",
                        "payload": snapshot,
                    },
                )
                if not quiet:
                    print(f"snapshot lastUpdateId: {snapshot.get('lastUpdateId')}")
                    print("-" * 80)

                while True:
                    record = await queue.get()
                    if record is None:
                        break

                    stream = record["stream"]
                    payload = record["payload"]

                    if "@depth@" in stream:
                        depth_file.write_record(record)
                        event_count += 1
                        if not quiet and (print_every <= 1 or event_count % print_every == 0):
                            print(
                                f"depth {event_count}: U={payload.get('U')} u={payload.get('u')} pu={payload.get('pu')} "
                                f"bids={len(payload.get('b', []))} asks={len(payload.get('a', []))}"
                            )
                    elif stream.endswith("@aggTrade") and trades_file is not None:
                        trades_file.write_record(record)
                        trade_count += 1
                        if not quiet and print_every > 0 and trade_count % print_every == 0:
                            print(f"trades captured: {trade_count}")

                    if max_seconds > 0 and asyncio.get_running_loop().time() - start_loop_time >= max_seconds:
                        if not quiet:
                            print(f"Reached time limit: {max_seconds} seconds.")
                        break

                    if max_events > 0 and event_count >= max_events:
                        if not quiet:
                            print(f"Reached event limit: {max_events} depth events.")
                        break
            finally:
                reader_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await reader_task
    finally:
        session.close()
        snapshot_file.close()
        depth_file.close()
        if trades_file is not None:
            trades_file.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect aligned Binance Futures L2 data for A-S model backtests.")
    parser.add_argument("--symbol", type=str, default="BTCUSDT", help="Trading symbol, for example BTCUSDT.")
    parser.add_argument("--depth-limit", type=int, default=DEFAULT_DEPTH_LIMIT, help="REST snapshot depth limit.")
    parser.add_argument("--max-events", type=int, default=0, help="Depth event limit. Use 0 for no event limit.")
    parser.add_argument("--max-seconds", type=float, default=0, help="Time limit in seconds. Use 0 for no time limit.")
    parser.add_argument("--include-trades", action="store_true", help="Also store aggTrade events in the same session.")
    parser.add_argument("--flush-every", type=int, default=DEFAULT_FLUSH_EVERY, help="Flush to disk every N records.")
    parser.add_argument(
        "--flush-interval",
        type=float,
        default=DEFAULT_FLUSH_INTERVAL,
        help="Flush to disk at least once every N seconds.",
    )
    parser.add_argument("--quiet", action="store_true", help="Reduce console output for higher throughput.")
    parser.add_argument("--print-every", type=int, default=100, help="Print progress every N depth records.")
    parser.add_argument("--output-root", type=str, default=DEFAULT_OUTPUT_ROOT, help="Root directory for saved sessions.")
    parser.add_argument("--session-name", type=str, default="", help="Optional explicit session directory name.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    session_name = args.session_name or build_session_name(args.symbol)
    asyncio.run(
        collect_l2_session(
            symbol=args.symbol,
            depth_limit=args.depth_limit,
            include_trades=args.include_trades,
            max_events=args.max_events,
            max_seconds=args.max_seconds,
            flush_every=args.flush_every,
            flush_interval=args.flush_interval,
            quiet=args.quiet,
            print_every=args.print_every,
            output_root=Path(args.output_root),
            session_name=session_name,
        )
    )


if __name__ == "__main__":
    main()
