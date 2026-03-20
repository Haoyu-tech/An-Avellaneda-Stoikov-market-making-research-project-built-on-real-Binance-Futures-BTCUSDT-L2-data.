import argparse
import json
from datetime import datetime
from pathlib import Path


HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Binance L2 Heatmap Replay</title>
  <style>
    :root {
      --bg: #f5efe5;
      --panel: #fffaf2;
      --ink: #1d1d1b;
      --muted: #736b62;
      --bid: #1b7f5b;
      --ask: #c4492d;
      --grid: #e7ddcf;
      --accent: #0d5c63;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: Georgia, "Times New Roman", serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top left, #fff8ee 0, transparent 30%),
        linear-gradient(180deg, #f7f1e8 0%, #efe4d2 100%);
    }
    .wrap {
      max-width: 1200px;
      margin: 0 auto;
      padding: 28px 20px 40px;
    }
    h1 {
      margin: 0 0 8px;
      font-size: 34px;
      letter-spacing: 0.02em;
    }
    .sub {
      color: var(--muted);
      margin-bottom: 20px;
      font-size: 15px;
    }
    .topbar, .panel {
      background: rgba(255, 250, 242, 0.88);
      border: 1px solid rgba(29, 29, 27, 0.08);
      border-radius: 18px;
      box-shadow: 0 14px 40px rgba(61, 44, 17, 0.08);
      backdrop-filter: blur(10px);
    }
    .topbar {
      padding: 16px 18px;
      margin-bottom: 18px;
    }
    .controls {
      display: grid;
      grid-template-columns: 1fr auto auto;
      gap: 14px;
      align-items: center;
    }
    input[type="range"] { width: 100%; accent-color: var(--accent); }
    button {
      border: 0;
      border-radius: 999px;
      padding: 10px 16px;
      background: var(--accent);
      color: white;
      font-weight: 600;
      cursor: pointer;
    }
    .stats {
      display: grid;
      grid-template-columns: repeat(5, minmax(0, 1fr));
      gap: 12px;
      margin-top: 14px;
    }
    .stat {
      padding: 12px 14px;
      background: rgba(255,255,255,0.55);
      border-radius: 14px;
      border: 1px solid rgba(29,29,27,0.06);
    }
    .label { font-size: 12px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.08em; }
    .value { font-size: 22px; margin-top: 6px; font-variant-numeric: tabular-nums; }
    .grid {
      display: grid;
      grid-template-columns: 1.25fr 0.9fr;
      gap: 18px;
    }
    .panel { padding: 18px; }
    .heatmap {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 14px;
    }
    .ladder-title {
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      margin-bottom: 10px;
      font-size: 15px;
    }
    .ladder {
      display: grid;
      gap: 8px;
    }
    .row {
      position: relative;
      display: grid;
      grid-template-columns: 98px 90px 1fr;
      gap: 10px;
      align-items: center;
      min-height: 28px;
      font-variant-numeric: tabular-nums;
    }
    .row .bar {
      height: 100%;
      border-radius: 999px;
      opacity: 0.92;
      transition: width 160ms ease;
    }
    .bid .bar { background: linear-gradient(90deg, #8fd6bb, var(--bid)); }
    .ask .bar { background: linear-gradient(90deg, #f0ae9f, var(--ask)); }
    .row .barWrap {
      height: 22px;
      background: rgba(0,0,0,0.04);
      border-radius: 999px;
      overflow: hidden;
    }
    .changes {
      margin-top: 18px;
      display: grid;
      gap: 8px;
      max-height: 580px;
      overflow: auto;
      padding-right: 4px;
    }
    .change {
      border-left: 4px solid var(--grid);
      padding: 10px 12px;
      background: rgba(255,255,255,0.6);
      border-radius: 10px;
      font-variant-numeric: tabular-nums;
    }
    .change.bid { border-left-color: var(--bid); }
    .change.ask { border-left-color: var(--ask); }
    .hint { color: var(--muted); font-size: 13px; }
    @media (max-width: 920px) {
      .grid { grid-template-columns: 1fr; }
      .stats { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .controls { grid-template-columns: 1fr; }
      .heatmap { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <div class="wrap">
    <h1>Binance L2 Heatmap Replay</h1>
    <div class="sub">Snapshot + diff-depth reconstruction rendered as a local standalone page.</div>

    <div class="topbar">
      <div class="controls">
        <input id="slider" type="range" min="0" max="0" value="0">
        <button id="playBtn">Play</button>
        <div id="stepLabel" class="hint"></div>
      </div>
      <div class="stats">
        <div class="stat"><div class="label">Event Time</div><div class="value" id="eventTime">-</div></div>
        <div class="stat"><div class="label">Best Bid</div><div class="value" id="bestBid">-</div></div>
        <div class="stat"><div class="label">Best Ask</div><div class="value" id="bestAsk">-</div></div>
        <div class="stat"><div class="label">Mid</div><div class="value" id="mid">-</div></div>
        <div class="stat"><div class="label">Spread</div><div class="value" id="spread">-</div></div>
      </div>
    </div>

    <div class="grid">
      <div class="panel">
        <div class="heatmap">
          <div>
            <div class="ladder-title"><strong>Bids</strong><span class="hint">near best bid</span></div>
            <div id="bidLadder" class="ladder"></div>
          </div>
          <div>
            <div class="ladder-title"><strong>Asks</strong><span class="hint">near best ask</span></div>
            <div id="askLadder" class="ladder"></div>
          </div>
        </div>
      </div>

      <div class="panel">
        <div class="ladder-title"><strong>Changed Levels</strong><span id="changeCount" class="hint"></span></div>
        <div id="changes" class="changes"></div>
      </div>
    </div>
  </div>

  <script>
    const FRAMES = __FRAMES_JSON__;
    const slider = document.getElementById('slider');
    const playBtn = document.getElementById('playBtn');
    const stepLabel = document.getElementById('stepLabel');
    const eventTime = document.getElementById('eventTime');
    const bestBid = document.getElementById('bestBid');
    const bestAsk = document.getElementById('bestAsk');
    const mid = document.getElementById('mid');
    const spread = document.getElementById('spread');
    const bidLadder = document.getElementById('bidLadder');
    const askLadder = document.getElementById('askLadder');
    const changes = document.getElementById('changes');
    const changeCount = document.getElementById('changeCount');
    slider.max = Math.max(0, FRAMES.length - 1);

    let playing = false;
    let timer = null;

    function fmt(value, digits = 4) {
      if (value === null || value === undefined) return '-';
      return Number(value).toFixed(digits);
    }

    function ladderRow(side, level, maxQty) {
      const row = document.createElement('div');
      row.className = `row ${side}`;
      const width = maxQty > 0 ? Math.max(2, Math.round((level.qty / maxQty) * 100)) : 0;
      row.innerHTML = `
        <div>${fmt(level.price, 2)}</div>
        <div>${fmt(level.qty, 4)}</div>
        <div class="barWrap"><div class="bar" style="width:${width}%"></div></div>
      `;
      return row;
    }

    function renderLadder(node, side, levels, maxQty) {
      node.innerHTML = '';
      levels.forEach(level => node.appendChild(ladderRow(side, level, maxQty)));
    }

    function renderChanges(items) {
      changes.innerHTML = '';
      changeCount.textContent = `${items.length} updates`;
      if (!items.length) {
        changes.innerHTML = '<div class="hint">No changed levels in this diff message.</div>';
        return;
      }
      items.forEach(item => {
        const div = document.createElement('div');
        div.className = `change ${item.side}`;
        div.innerHTML = `
          <strong>${item.side.toUpperCase()} ${fmt(item.price, 2)}</strong><br>
          ${item.action} ${fmt(item.old_qty)} -> ${fmt(item.new_qty)}<br>
          delta ${item.delta >= 0 ? '+' : ''}${fmt(item.delta)}
        `;
        changes.appendChild(div);
      });
    }

    function renderFrame(index) {
      const frame = FRAMES[index];
      if (!frame) return;
      slider.value = index;
      stepLabel.textContent = `Step ${frame.step} / ${FRAMES.length}`;
      eventTime.textContent = frame.event_time;
      bestBid.textContent = fmt(frame.best_bid, 2);
      bestAsk.textContent = fmt(frame.best_ask, 2);
      mid.textContent = fmt(frame.mid, 2);
      spread.textContent = fmt(frame.spread, 4);
      const maxQty = Math.max(...frame.bids.map(x => x.qty), ...frame.asks.map(x => x.qty), 0);
      renderLadder(bidLadder, 'bid', frame.bids, maxQty);
      renderLadder(askLadder, 'ask', frame.asks, maxQty);
      renderChanges(frame.changes);
    }

    function startPlayback() {
      if (playing) return;
      playing = true;
      playBtn.textContent = 'Pause';
      timer = setInterval(() => {
        let next = Number(slider.value) + 1;
        if (next >= FRAMES.length) next = 0;
        renderFrame(next);
      }, 700);
    }

    function stopPlayback() {
      playing = false;
      playBtn.textContent = 'Play';
      if (timer) clearInterval(timer);
      timer = null;
    }

    playBtn.addEventListener('click', () => {
      if (playing) stopPlayback();
      else startPlayback();
    });
    slider.addEventListener('input', event => {
      stopPlayback();
      renderFrame(Number(event.target.value));
    });

    renderFrame(0);
  </script>
</body>
</html>
"""


def load_ndjson(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open("r", encoding="utf-8") as file_obj:
        for line in file_obj:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def build_book(levels: list[list[str]]) -> dict[float, float]:
    book: dict[float, float] = {}
    for price_str, qty_str in levels:
        qty = float(qty_str)
        if qty > 0:
            book[float(price_str)] = qty
    return book


def apply_updates(book: dict[float, float], updates: list[list[str]]) -> None:
    for price_str, qty_str in updates:
        price = float(price_str)
        qty = float(qty_str)
        if qty == 0:
            book.pop(price, None)
        else:
            book[price] = qty


def capture_changes(book: dict[float, float], updates: list[list[str]], side: str) -> list[dict]:
    changes: list[dict] = []
    for price_str, qty_str in updates:
        price = float(price_str)
        new_qty = float(qty_str)
        old_qty = book.get(price, 0.0)
        if old_qty == new_qty:
            continue
        changes.append(
            {
                "side": side,
                "price": price,
                "old_qty": old_qty,
                "new_qty": new_qty,
                "delta": new_qty - old_qty,
                "action": "remove" if new_qty == 0 else ("add" if old_qty == 0 else "update"),
            }
        )
    return changes


def best_levels(bids: dict[float, float], asks: dict[float, float], depth: int) -> tuple[list[dict], list[dict]]:
    top_bids = [{"price": p, "qty": q} for p, q in sorted(bids.items(), key=lambda x: x[0], reverse=True)[:depth]]
    top_asks = [{"price": p, "qty": q} for p, q in sorted(asks.items(), key=lambda x: x[0])[:depth]]
    return top_bids, top_asks


def ms_to_str(ms: int | None) -> str:
    if not ms:
        return "N/A"
    return datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def build_frames(snapshot_path: Path, diff_path: Path, levels: int, steps: int) -> list[dict]:
    snapshot_records = load_ndjson(snapshot_path)
    if not snapshot_records:
        raise ValueError(f"No snapshot records found in {snapshot_path}")

    snapshot = snapshot_records[-1]["payload"]
    bids = build_book(snapshot["bids"])
    asks = build_book(snapshot["asks"])
    last_update_id = snapshot["lastUpdateId"]

    frames: list[dict] = []
    step = 0
    for record in load_ndjson(diff_path):
        payload = record.get("payload", {})
        end_id = payload.get("u")
        if end_id is None or end_id < last_update_id:
            continue

        bid_changes = capture_changes(bids, payload.get("b", []), "bid")
        ask_changes = capture_changes(asks, payload.get("a", []), "ask")
        apply_updates(bids, payload.get("b", []))
        apply_updates(asks, payload.get("a", []))
        last_update_id = end_id
        step += 1

        top_bids, top_asks = best_levels(bids, asks, levels)
        best_bid = top_bids[0]["price"] if top_bids else None
        best_ask = top_asks[0]["price"] if top_asks else None
        mid = (best_bid + best_ask) / 2.0 if best_bid is not None and best_ask is not None else None
        spread = (best_ask - best_bid) if best_bid is not None and best_ask is not None else None
        near_best = []
        if best_bid is not None and best_ask is not None:
            lo = best_bid - 20
            hi = best_ask + 20
            near_best = [c for c in bid_changes + ask_changes if lo <= c["price"] <= hi]

        frames.append(
            {
                "step": step,
                "event_time": ms_to_str(payload.get("E")),
                "best_bid": best_bid,
                "best_ask": best_ask,
                "mid": mid,
                "spread": spread,
                "bids": top_bids,
                "asks": top_asks,
                "changes": near_best[:24],
            }
        )
        if steps > 0 and step >= steps:
            break

    return frames


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export Binance L2 replay as a local HTML heatmap page.")
    parser.add_argument("--snapshot", type=str, default="data/l2_snapshot.ndjson")
    parser.add_argument("--diff", type=str, default="data/l2_diff_depth.ndjson")
    parser.add_argument("--out", type=str, default="data/l2_heatmap.html")
    parser.add_argument("--steps", type=int, default=120, help="How many diff records to include.")
    parser.add_argument("--levels", type=int, default=12, help="How many top levels to render per side.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    snapshot_path = Path(args.snapshot)
    diff_path = Path(args.diff)
    out_path = Path(args.out)

    frames = build_frames(snapshot_path, diff_path, levels=args.levels, steps=args.steps)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    html = HTML_TEMPLATE.replace("__FRAMES_JSON__", json.dumps(frames, ensure_ascii=False))
    out_path.write_text(html, encoding="utf-8")

    print(f"frames exported: {len(frames)}")
    print(f"html written to: {out_path}")


if __name__ == "__main__":
    main()
raise SystemExit(
    "Deprecated script: visualization export is no longer part of the active A-S backtest workflow."
)
