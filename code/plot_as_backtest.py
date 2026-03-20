import argparse
import json
from pathlib import Path


def load_ndjson(path: Path) -> list[dict]:
    records: list[dict] = []
    with path.open("r", encoding="utf-8") as file_obj:
        for line in file_obj:
            line = line.strip()
            if line:
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


def resolve_session_dir(summary_path: Path) -> Path:
    candidate = summary_path.parent
    required = ("snapshot.ndjson", "depth.ndjson", "aggtrade.ndjson")
    if all((candidate / name).exists() for name in required):
        return candidate
    parent = candidate.parent
    if all((parent / name).exists() for name in required):
        return parent
    return candidate


def build_orderbook_frames(session_dir: Path, curve_times: list[int], levels: int = 8) -> list[dict]:
    if not curve_times:
        return []

    snapshot_records = load_ndjson(session_dir / "snapshot.ndjson")
    depth_records = load_ndjson(session_dir / "depth.ndjson")
    if not snapshot_records or not depth_records:
        return []

    snapshot = snapshot_records[-1]["payload"]
    bids = build_book(snapshot["bids"])
    asks = build_book(snapshot["asks"])
    last_update_id = int(snapshot["lastUpdateId"])

    aligned_updates: list[dict] = []
    started = False
    for record in depth_records:
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
        aligned_updates.append(
            {
                "time_ms": int(event_time),
                "bids": [[price, bids[price]] for price in sorted(bids, reverse=True)[:levels]],
                "asks": [[price, asks[price]] for price in sorted(asks)[:levels]],
            }
        )

    if not aligned_updates:
        return []

    frames: list[dict] = []
    update_idx = 0
    current = aligned_updates[0]
    for time_ms in curve_times:
        while update_idx + 1 < len(aligned_updates) and aligned_updates[update_idx + 1]["time_ms"] <= time_ms:
            update_idx += 1
            current = aligned_updates[update_idx]
        frames.append(
            {
                "time_ms": time_ms,
                "bids": current["bids"],
                "asks": current["asks"],
            }
        )
    return frames


HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>A-S Animated Backtest</title>
  <style>
    :root {{
      --bg: #f4f0e8;
      --panel: #fffaf2;
      --ink: #1f1c18;
      --muted: #6a6258;
      --line1: #1d6b57;
      --line2: #c2542d;
      --line3: #225f9c;
      --line4: #8b3c88;
      --grid: #ddd0bc;
    }}
    body {{
      margin: 0;
      font-family: Georgia, "Times New Roman", serif;
      background:
        radial-gradient(circle at top left, #efe3ce 0, transparent 32%),
        linear-gradient(180deg, #f7f1e6 0%, #efe6d7 100%);
      color: var(--ink);
    }}
    .wrap {{
      max-width: 1200px;
      margin: 24px auto;
      padding: 0 16px 32px;
    }}
    .hero, .panel {{
      background: rgba(255, 250, 242, 0.96);
      border: 1px solid #d8c9b3;
      border-radius: 18px;
      box-shadow: 0 14px 40px rgba(78, 57, 26, 0.08);
    }}
    .hero {{
      padding: 20px 22px;
    }}
    .panel {{
      margin-top: 18px;
      padding: 14px;
    }}
    h1 {{
      margin: 0 0 8px;
      font-size: 34px;
      line-height: 1.05;
      letter-spacing: -0.03em;
    }}
    .sub {{
      color: var(--muted);
      font-size: 15px;
    }}
    .stats {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
      gap: 12px;
      margin-top: 18px;
    }}
    .stat {{
      background: #fff;
      border: 1px solid #eadfce;
      border-radius: 14px;
      padding: 12px 14px;
    }}
    .label {{
      color: var(--muted);
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
    }}
    .value {{
      margin-top: 6px;
      font-size: 24px;
      font-weight: 700;
    }}
    .title {{
      font-size: 16px;
      margin: 4px 6px 12px;
    }}
    .legend {{
      display: flex;
      gap: 18px;
      color: var(--muted);
      font-size: 13px;
      margin: 0 6px 10px;
      flex-wrap: wrap;
    }}
    .dot {{
      display: inline-block;
      width: 10px;
      height: 10px;
      border-radius: 999px;
      margin-right: 7px;
      vertical-align: middle;
    }}
    .controls {{
      display: flex;
      gap: 12px;
      align-items: center;
      flex-wrap: wrap;
      margin-top: 16px;
    }}
    button {{
      border: 1px solid #d8c9b3;
      background: #fff;
      color: var(--ink);
      border-radius: 999px;
      padding: 10px 16px;
      cursor: pointer;
      font: inherit;
    }}
    input[type="range"] {{
      flex: 1 1 320px;
      accent-color: #1d6b57;
    }}
    .play-meta {{
      color: var(--muted);
      font-size: 14px;
    }}
    .stage {{
      position: relative;
    }}
    .floating-state {{
      position: absolute;
      top: 18px;
      right: 18px;
      width: 240px;
      background: rgba(255, 250, 242, 0.92);
      border: 1px solid #d8c9b3;
      border-radius: 14px;
      padding: 12px 14px;
      box-shadow: 0 14px 40px rgba(78, 57, 26, 0.08);
      backdrop-filter: blur(6px);
    }}
    .floating-state .state-row {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      font-size: 13px;
      color: var(--muted);
      margin-top: 8px;
    }}
    .floating-state .state-row strong {{
      color: var(--ink);
      font-weight: 700;
    }}
    .grid {{
      display: grid;
      grid-template-columns: 1.5fr 1fr;
      gap: 18px;
    }}
    .full-width {{
      margin-top: 18px;
    }}
    .mini-grid {{
      display: grid;
      grid-template-columns: 1fr 1fr 1fr;
      gap: 18px;
      margin-top: 18px;
    }}
    .stats-grid {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 18px;
      margin-top: 18px;
    }}
    .stats-list {{
      display: grid;
      grid-template-columns: 1fr;
      gap: 8px;
      margin-top: 4px;
    }}
    .stats-row {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      padding: 10px 12px;
      border: 1px solid #eadfce;
      border-radius: 12px;
      background: #fff;
      color: var(--muted);
      font-size: 13px;
    }}
    .stats-row strong {{
      color: var(--ink);
      font-weight: 700;
      text-align: right;
    }}
    svg {{
      width: 100%;
      height: auto;
      display: block;
      background: #fffdf9;
      border-radius: 16px;
    }}
    .fills {{
      margin-top: 12px;
      font-size: 14px;
      color: var(--muted);
    }}
    .book-meta {{
      margin-top: 10px;
      color: var(--muted);
      font-size: 13px;
    }}
    .timeline-strip {{
      margin-top: 14px;
      display: flex;
      justify-content: space-between;
      gap: 12px;
      color: var(--muted);
      font-size: 13px;
      border-top: 1px solid #eadfce;
      padding-top: 10px;
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <section class="hero">
      <h1>Continuous A-S Animated Replay</h1>
      <div class="sub">{subtitle}</div>
      <div class="stats">
        <div class="stat"><div class="label">Final Equity</div><div class="value">{final_equity}</div></div>
        <div class="stat"><div class="label">Net PnL</div><div class="value">{net_pnl}</div></div>
        <div class="stat"><div class="label">Fills</div><div class="value">{fills}</div></div>
        <div class="stat"><div class="label">Gamma / K</div><div class="value">{gamma_k}</div></div>
      </div>
      <div class="controls">
        <button id="playBtn" type="button">Pause</button>
        <input id="frameSlider" type="range" min="0" max="{frame_max}" value="0">
        <div class="play-meta">
          frame <span id="frameLabel">0</span> / {frame_max} |
          time <span id="timeLabel">-</span> |
          speed <span id="speedLabel">1x</span>
        </div>
      </div>
      <div class="timeline-strip">
        <span>start {start_time}</span>
        <span>duration {duration_text}</span>
        <span>end {end_time}</span>
      </div>
    </section>

    <div class="grid">
      <section class="panel">
        <div class="title">Order Book Quotes And Fills</div>
        <div class="legend">
          <span><span class="dot" style="background: #444"></span>Best Bid</span>
          <span><span class="dot" style="background: #777"></span>Best Ask</span>
          <span><span class="dot" style="background: var(--line3)"></span>Bid Active</span>
          <span><span class="dot" style="background: var(--line4)"></span>Ask Active</span>
          <span><span class="dot" style="background: #5f88c9"></span>Bid Target</span>
          <span><span class="dot" style="background: #b06cad"></span>Ask Target</span>
          <span><span class="dot" style="background: #111"></span>Trade Price</span>
        </div>
        <div class="stage">
          <svg id="quoteSvg" viewBox="0 0 1020 460" role="img" aria-label="Animated order book quotes"></svg>
          <div class="floating-state">
            <div class="label">Current Account State</div>
            <div class="state-row"><span>Cash</span><strong id="cashLabel">-</strong></div>
            <div class="state-row"><span>Position</span><strong id="positionLabel">-</strong></div>
            <div class="state-row"><span>Equity</span><strong id="equityLabel">-</strong></div>
            <div class="state-row"><span>Mid</span><strong id="midLabel">-</strong></div>
          </div>
        </div>
        <div class="fills" id="fillText">{fills_text}</div>
      </section>

      <section class="panel">
        <div class="title">Current Order Book</div>
        <svg id="bookSvg" viewBox="0 0 720 460" role="img" aria-label="Animated order book depth"></svg>
        <div class="book-meta" id="bookMeta">top-of-book depth updates with playback</div>
      </section>
    </div>

    <section class="panel full-width">
      <div class="title">Account State Delta</div>
      <svg id="equitySvg" viewBox="0 0 1020 460" role="img" aria-label="Animated account state"></svg>
    </section>

    <div class="stats-grid">
      <section class="panel">
        <div class="title">PnL Breakdown</div>
        <div class="stats-list">
          <div class="stats-row"><span>Realized Gross</span><strong>{realized_gross}</strong></div>
          <div class="stats-row"><span>Inventory PnL</span><strong>{inventory_pnl}</strong></div>
          <div class="stats-row"><span>Gross Before Fees</span><strong>{gross_before_fees}</strong></div>
          <div class="stats-row"><span>Fees Paid</span><strong>{fees_paid}</strong></div>
          <div class="stats-row"><span>Net After Fees</span><strong>{net_after_fees}</strong></div>
        </div>
      </section>

      <section class="panel">
        <div class="title">Execution Stats</div>
        <div class="stats-list">
          <div class="stats-row"><span>Order / Cancel Latency</span><strong>{latency_pair}</strong></div>
          <div class="stats-row"><span>Quote Refresh / No Change</span><strong>{refresh_pair}</strong></div>
          <div class="stats-row"><span>Submit / Replace / Cancel</span><strong>{request_triplet}</strong></div>
          <div class="stats-row"><span>Activated Qty / Fill Qty</span><strong>{qty_pair}</strong></div>
          <div class="stats-row"><span>Fill Rate / Unfilled End</span><strong>{fill_rate_end}</strong></div>
        </div>
      </section>
    </div>

    <div class="mini-grid">
      <section class="panel">
        <div class="title">Dynamic Sigma</div>
        <svg id="sigmaSvg" viewBox="0 0 640 280" role="img" aria-label="Animated sigma"></svg>
      </section>
      <section class="panel">
        <div class="title">Dynamic K</div>
        <svg id="kSvg" viewBox="0 0 640 280" role="img" aria-label="Animated k"></svg>
      </section>
      <section class="panel">
        <div class="title">Inventory</div>
        <svg id="inventorySvg" viewBox="0 0 640 280" role="img" aria-label="Animated inventory"></svg>
      </section>
    </div>
  </div>

  <script>
    const payload = {payload_json};

    const quoteSvg = document.getElementById("quoteSvg");
    const bookSvg = document.getElementById("bookSvg");
    const equitySvg = document.getElementById("equitySvg");
    const sigmaSvg = document.getElementById("sigmaSvg");
    const kSvg = document.getElementById("kSvg");
    const inventorySvg = document.getElementById("inventorySvg");
    const playBtn = document.getElementById("playBtn");
    const frameSlider = document.getElementById("frameSlider");
    const frameLabel = document.getElementById("frameLabel");
    const timeLabel = document.getElementById("timeLabel");
    const speedLabel = document.getElementById("speedLabel");
    const fillText = document.getElementById("fillText");
    const bookMeta = document.getElementById("bookMeta");
    const cashLabel = document.getElementById("cashLabel");
    const positionLabel = document.getElementById("positionLabel");
    const equityLabel = document.getElementById("equityLabel");
    const midLabel = document.getElementById("midLabel");

    const curve = payload.equity_curve;
    const orderbookFrames = payload.orderbook_frames || [];
    const fills = payload.first_fills;
    const fillByTime = new Map(fills.map((fill) => [fill.time_ms, fill]));
    const frameCount = curve.length;
    let frame = 0;
    let playing = true;
    let speed = 1;
    let pauseOnFill = true;

    const priceSeries = {{
      mid: curve.map((row) => row.mid),
      bestBid: curve.map((row) => row.best_bid),
      bestAsk: curve.map((row) => row.best_ask),
      bidQuote: curve.map((row) => row.bid_quote ?? row.mid),
      askQuote: curve.map((row) => row.ask_quote ?? row.mid),
      bidTargetQuote: curve.map((row) => row.bid_target_quote ?? row.mid),
      askTargetQuote: curve.map((row) => row.ask_target_quote ?? row.mid),
    }};
    const equitySeries = {{
      cash: curve.map((row) => row.cash_usdt),
      equity: curve.map((row) => row.equity_usdt),
      inventoryValue: curve.map((row) => row.position_btc * row.mid),
    }};
    const accountDeltaSeries = {{
      cashDelta: curve.map((row) => row.cash_usdt - curve[0].cash_usdt),
      equityDelta: curve.map((row) => row.equity_usdt - curve[0].equity_usdt),
      inventoryValueDelta: curve.map((row) => row.position_btc * row.mid),
    }};
    const inventorySeries = curve.map((row) => row.position_btc);
    const sigmaSeries = curve.map((row) => row.sigma);
    const kSeries = curve.map((row) => row.k);

    function formatClock(timeMs) {{
      return new Date(timeMs).toLocaleTimeString([], {{
        hour12: false,
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      }});
    }}

    function formatAxisTime(timeMs) {{
      return new Date(timeMs).toLocaleTimeString([], {{
        hour12: false,
        minute: "2-digit",
        second: "2-digit",
      }});
    }}

    function scaleFactory(values, width, height, pad) {{
      const min = Math.min(...values);
      const max = Math.max(...values);
      const span = (max - min) || 1;
      return {{
        x: (index, total) => pad + ((width - pad * 2) * index / Math.max(1, total - 1)),
        y: (value) => height - pad - ((value - min) / span) * (height - pad * 2),
        min,
        max,
      }};
    }}

    function buildGrid(width, height, pad) {{
      let html = `<rect x="0" y="0" width="${{width}}" height="${{height}}" rx="16" fill="#fffdf9"/>`;
      for (let i = 0; i < 5; i += 1) {{
        const y = pad + i * (height - pad * 2) / 4;
        html += `<line x1="${{pad}}" y1="${{y}}" x2="${{width - pad}}" y2="${{y}}" stroke="var(--grid)" stroke-width="1"/>`;
      }}
      return html;
    }}

    function buildTimeAxis(width, height, pad, stopFrame) {{
      if (!curve.length) return "";
      const axisY = height - pad + 16;
      let html = `<line x1="${{pad}}" y1="${{height - pad}}" x2="${{width - pad}}" y2="${{height - pad}}" stroke="#cdbfa9" stroke-width="1.2"/>`;
      const tickCount = 5;
      for (let i = 0; i < tickCount; i += 1) {{
        const ratio = tickCount === 1 ? 0 : i / (tickCount - 1);
        const idx = Math.round(ratio * Math.max(0, curve.length - 1));
        const x = pad + ratio * (width - pad * 2);
        const tickTime = curve[idx].time_ms;
        html += `<line x1="${{x}}" y1="${{height - pad}}" x2="${{x}}" y2="${{height - pad + 6}}" stroke="#9b8f7c" stroke-width="1.2"/>`;
        html += `<text x="${{x}}" y="${{axisY + 14}}" text-anchor="middle" fill="var(--muted)" font-size="12">${{formatAxisTime(tickTime)}}</text>`;
      }}
      const focusX = pad + ((width - pad * 2) * stopFrame / Math.max(1, curve.length - 1));
      const elapsedSeconds = (curve[stopFrame].time_ms - curve[0].time_ms) / 1000;
      html += `<text x="${{focusX}}" y="${{axisY - 4}}" text-anchor="middle" fill="#111" font-size="12" font-weight="700">t=+${{elapsedSeconds.toFixed(1)}}s</text>`;
      return html;
    }}

    function linePath(values, scaler, width, height, pad, stopFrame) {{
      if (!values.length) return "";
      let path = "";
      const last = Math.min(stopFrame, values.length - 1);
      for (let i = 0; i <= last; i += 1) {{
        const x = scaler.x(i, values.length);
        const y = scaler.y(values[i]);
        path += `${{i === 0 ? "M" : "L"}} ${{x.toFixed(2)}} ${{y.toFixed(2)}} `;
      }}
      return path.trim();
    }}

    function renderLineChart(svg, series, colors, width, height, pad, stopFrame) {{
      const allValues = Object.values(series).flat();
      const scaler = scaleFactory(allValues, width, height, pad);
      let html = buildGrid(width, height, pad);
      Object.entries(series).forEach(([key, values]) => {{
        html += `<path d="${{linePath(values, scaler, width, height, pad, stopFrame)}}" fill="none" stroke="${{colors[key]}}" stroke-width="3"/>`;
      }});
      const focusX = scaler.x(stopFrame, curve.length);
      html += `<line x1="${{focusX}}" y1="${{pad}}" x2="${{focusX}}" y2="${{height - pad}}" stroke="#111" stroke-dasharray="6 6" stroke-width="1.5"/>`;
      html += buildTimeAxis(width, height, pad, stopFrame);
      svg.innerHTML = html;
    }}

    function renderAccountChart(stopFrame) {{
      const width = 1020, height = 460, pad = 42;
      const series = accountDeltaSeries;
      const colors = {{
        cashDelta: "var(--line1)",
        equityDelta: "var(--line2)",
        inventoryValueDelta: "var(--line4)",
      }};
      const allValues = Object.values(series).flat();
      const scaler = scaleFactory(allValues, width, height, pad);
      let html = buildGrid(width, height, pad);
      Object.entries(series).forEach(([key, values]) => {{
        html += `<path d="${{linePath(values, scaler, width, height, pad, stopFrame)}}" fill="none" stroke="${{colors[key]}}" stroke-width="3"/>`;
      }});
      const focusX = scaler.x(stopFrame, curve.length);
      html += `<line x1="${{focusX}}" y1="${{pad}}" x2="${{focusX}}" y2="${{height - pad}}" stroke="#111" stroke-dasharray="6 6" stroke-width="1.5"/>`;
      const zeroY = scaler.y(0);
      html += `<line x1="${{pad}}" y1="${{zeroY}}" x2="${{width - pad}}" y2="${{zeroY}}" stroke="#8f8473" stroke-dasharray="4 4" stroke-width="1.2"/>`;
      html += `<text x="${{pad + 8}}" y="${{zeroY - 8}}" fill="var(--muted)" font-size="12">0 delta</text>`;
      const row = curve[stopFrame];
      const cashDelta = row.cash_usdt - curve[0].cash_usdt;
      const equityDelta = row.equity_usdt - curve[0].equity_usdt;
      const inventoryDelta = row.position_btc * row.mid;
      html += `<text x="${{width - pad}}" y="${{pad - 10}}" text-anchor="end" fill="var(--muted)" font-size="13">cash ${{cashDelta.toFixed(4)}} | equity ${{equityDelta.toFixed(4)}} | inv ${{inventoryDelta.toFixed(4)}}</text>`;
      if (Math.max(...allValues) === Math.min(...allValues)) {{
        html += `<text x="${{width / 2}}" y="${{height / 2}}" text-anchor="middle" fill="#6a6258" font-size="22" font-weight="700">No account change in this run</text>`;
        html += `<text x="${{width / 2}}" y="${{height / 2 + 26}}" text-anchor="middle" fill="#6a6258" font-size="14">fills = ${{payload.summary.fills}}, so cash and equity stay flat</text>`;
      }}
      html += buildTimeAxis(width, height, pad, stopFrame);
      equitySvg.innerHTML = html;
    }}

    function renderQuoteChart(stopFrame) {{
      const width = 1020, height = 460, pad = 42;
      const scaler = scaleFactory(
        [
          ...priceSeries.mid,
          ...priceSeries.bestBid,
          ...priceSeries.bestAsk,
          ...priceSeries.bidQuote,
          ...priceSeries.askQuote,
          ...priceSeries.bidTargetQuote,
          ...priceSeries.askTargetQuote,
        ],
        width,
        height,
        pad
      );
      let html = buildGrid(width, height, pad);
      const colors = {{
        mid: "var(--line1)",
        bestBid: "#444",
        bestAsk: "#777",
        bidQuote: "var(--line3)",
        askQuote: "var(--line4)",
        bidTargetQuote: "#5f88c9",
        askTargetQuote: "#b06cad",
      }};
      Object.entries(priceSeries).forEach(([key, values]) => {{
        const dash = key.endsWith("TargetQuote") ? "10 7" : "";
        const widthPx = key.endsWith("TargetQuote") ? 2 : 2.5;
        const dashAttr = dash ? `stroke-dasharray="${{dash}}"` : "";
        html += `<path d="${{linePath(values, scaler, width, height, pad, stopFrame)}}" fill="none" stroke="${{colors[key]}}" stroke-width="${{widthPx}}" ${{dashAttr}}/>`;
      }});
      const row = curve[stopFrame];
      const focusX = scaler.x(stopFrame, curve.length);
      html += `<line x1="${{focusX}}" y1="${{pad}}" x2="${{focusX}}" y2="${{height - pad}}" stroke="#111" stroke-dasharray="6 6" stroke-width="1.5"/>`;
      const points = [
        [row.best_bid, "#444", 5],
        [row.best_ask, "#777", 5],
        [row.bid_quote ?? row.mid, "var(--line3)", 6],
        [row.ask_quote ?? row.mid, "var(--line4)", 6],
        [row.bid_target_quote ?? row.mid, "#5f88c9", 4],
        [row.ask_target_quote ?? row.mid, "#b06cad", 4],
      ];
      points.forEach(([value, color, radius]) => {{
        html += `<circle cx="${{focusX}}" cy="${{scaler.y(value)}}" r="${{radius}}" fill="${{color}}"/>`;
      }});
      const fill = fillByTime.get(row.time_ms);
      if (fill) {{
        const fillColor = fill.side === "buy" ? "#1d6b57" : "#c2542d";
        html += `<circle cx="${{focusX}}" cy="${{scaler.y(fill.fill_price)}}" r="8" fill="${{fillColor}}"/>`;
        html += `<circle cx="${{focusX}}" cy="${{scaler.y(fill.trade_price)}}" r="6" fill="#111"/>`;
        html += `<line x1="${{focusX}}" y1="${{scaler.y(fill.fill_price)}}" x2="${{focusX}}" y2="${{scaler.y(fill.trade_price)}}" stroke="#111" stroke-dasharray="4 4" stroke-width="1.5"/>`;
        html += `<text x="${{focusX + 10}}" y="${{scaler.y(fill.fill_price) - 12}}" fill="${{fillColor}}" font-size="14" font-weight="700">${{fill.side.toUpperCase()}}</text>`;
        fillText.textContent = `fill @ ${{fill.fill_price.toFixed(1)}} | trade @ ${{fill.trade_price.toFixed(1)}} | side=${{fill.side}} | qty=${{fill.fill_qty}}`;
      }} else {{
        fillText.textContent = "current frame has no fill";
      }}
      html += buildTimeAxis(width, height, pad, stopFrame);
      quoteSvg.innerHTML = html;
    }}

    function renderOrderBookChart(stopFrame) {{
      const width = 720, height = 460, pad = 32;
      const frameBook = orderbookFrames[stopFrame];
      if (!frameBook) {{
        bookSvg.innerHTML = buildGrid(width, height, pad);
        bookMeta.textContent = "order book data unavailable";
        return;
      }}

      const bids = frameBook.bids || [];
      const asks = frameBook.asks || [];
      const allQty = [...bids, ...asks].map((item) => item[1]);
      const maxQty = Math.max(...allQty, 1);
      const centerX = width / 2;
      const rowHeight = 22;
      const topY = 52;

      let html = `<rect x="0" y="0" width="${{width}}" height="${{height}}" rx="16" fill="#fffdf9"/>`;
      html += `<line x1="${{centerX}}" y1="26" x2="${{centerX}}" y2="${{height - 26}}" stroke="#d7cab7" stroke-width="1.5"/>`;
      html += `<text x="${{centerX - 110}}" y="30" text-anchor="middle" fill="var(--muted)" font-size="13">Bids</text>`;
      html += `<text x="${{centerX + 110}}" y="30" text-anchor="middle" fill="var(--muted)" font-size="13">Asks</text>`;

      bids.forEach((item, idx) => {{
        const [price, qty] = item;
        const y = topY + idx * (rowHeight + 10);
        const barWidth = (qty / maxQty) * (width * 0.34);
        html += `<rect x="${{centerX - barWidth - 18}}" y="${{y}}" width="${{barWidth}}" height="${{rowHeight}}" rx="8" fill="rgba(29,107,87,0.82)"/>`;
        html += `<text x="${{centerX - 24}}" y="${{y + 15}}" text-anchor="end" fill="#1f1c18" font-size="12">${{price.toFixed(1)}}</text>`;
        html += `<text x="${{centerX - barWidth - 26}}" y="${{y + 15}}" text-anchor="end" fill="var(--muted)" font-size="12">${{qty.toFixed(3)}}</text>`;
      }});

      asks.forEach((item, idx) => {{
        const [price, qty] = item;
        const y = topY + idx * (rowHeight + 10);
        const barWidth = (qty / maxQty) * (width * 0.34);
        html += `<rect x="${{centerX + 18}}" y="${{y}}" width="${{barWidth}}" height="${{rowHeight}}" rx="8" fill="rgba(194,84,45,0.82)"/>`;
        html += `<text x="${{centerX + 24}}" y="${{y + 15}}" text-anchor="start" fill="#1f1c18" font-size="12">${{price.toFixed(1)}}</text>`;
        html += `<text x="${{centerX + barWidth + 30}}" y="${{y + 15}}" text-anchor="start" fill="var(--muted)" font-size="12">${{qty.toFixed(3)}}</text>`;
      }});

      const bestBid = bids.length ? bids[0][0] : null;
      const bestAsk = asks.length ? asks[0][0] : null;
      const spread = bestBid !== null && bestAsk !== null ? (bestAsk - bestBid).toFixed(1) : "-";
      html += `<text x="${{centerX}}" y="${{height - 24}}" text-anchor="middle" fill="#111" font-size="13" font-weight="700">spread ${{spread}}</text>`;
      bookSvg.innerHTML = html;
      bookMeta.textContent = `book time ${{formatClock(frameBook.time_ms)}} | top ${{Math.max(bids.length, asks.length)}} levels`;
    }}

    function renderFrame(stopFrame) {{
      renderQuoteChart(stopFrame);
      renderOrderBookChart(stopFrame);
      renderAccountChart(stopFrame);
      renderLineChart(
        sigmaSvg,
        {{ sigma: sigmaSeries }},
        {{ sigma: "var(--line3)" }},
        640,
        280,
        32,
        stopFrame
      );
      renderLineChart(
        kSvg,
        {{ k: kSeries }},
        {{ k: "var(--line4)" }},
        640,
        280,
        32,
        stopFrame
      );
      renderLineChart(
        inventorySvg,
        {{ inventory: inventorySeries }},
        {{ inventory: "var(--line3)" }},
        640,
        280,
        32,
        stopFrame
      );

      const row = curve[stopFrame];
      frameSlider.value = String(stopFrame);
      frameLabel.textContent = String(stopFrame);
      timeLabel.textContent = formatClock(row.time_ms);
      cashLabel.textContent = `${{row.cash_usdt.toFixed(4)}} USDT`;
      positionLabel.textContent = `${{row.position_btc.toFixed(4)}} BTC`;
      equityLabel.textContent = `${{row.equity_usdt.toFixed(4)}} USDT`;
      midLabel.textContent = `${{row.mid.toFixed(2)}}`;
    }}

    function tick() {{
      if (playing) {{
        frame = Math.min(frame + speed, frameCount - 1);
        renderFrame(frame);
        if (pauseOnFill && fillByTime.has(curve[frame].time_ms)) {{
          playing = false;
          playBtn.textContent = "Play";
        }}
        if (frame >= frameCount - 1) {{
          playing = false;
          playBtn.textContent = "Play";
        }}
      }}
      requestAnimationFrame(tick);
    }}

    playBtn.addEventListener("click", () => {{
      playing = !playing;
      playBtn.textContent = playing ? "Pause" : "Play";
    }});

    frameSlider.addEventListener("input", (event) => {{
      frame = Number(event.target.value);
      renderFrame(frame);
    }});

    window.addEventListener("keydown", (event) => {{
      if (event.code === "Space") {{
        event.preventDefault();
        playing = !playing;
        playBtn.textContent = playing ? "Pause" : "Play";
      }}
      if (event.key === "ArrowRight") {{
        frame = Math.min(frame + 25, frameCount - 1);
        renderFrame(frame);
      }}
      if (event.key === "ArrowLeft") {{
        frame = Math.max(frame - 25, 0);
        renderFrame(frame);
      }}
      if (event.key === "1") {{
        speed = 1;
        speedLabel.textContent = "1x";
      }}
      if (event.key === "2") {{
        speed = 4;
        speedLabel.textContent = "4x";
      }}
      if (event.key === "3") {{
        speed = 12;
        speedLabel.textContent = "12x";
      }}
    }});

    renderFrame(0);
    requestAnimationFrame(tick);
  </script>
</body>
</html>
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Render an animated HTML replay from an A-S backtest summary JSON.")
    parser.add_argument("--summary-json", type=str, required=True, help="Path to as_summary JSON.")
    parser.add_argument("--output-html", type=str, default="", help="Optional output HTML path.")
    args = parser.parse_args()

    summary_path = Path(args.summary_json)
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    session_dir = resolve_session_dir(summary_path)
    summary = payload["summary"]
    equity_curve = payload.get("equity_curve", [])
    fills = payload.get("first_fills", [])
    pnl_breakdown = summary.get("pnl_breakdown", {})
    execution_stats = summary.get("execution_stats", {})
    orderbook_frames = build_orderbook_frames(session_dir, [row["time_ms"] for row in equity_curve], levels=8)
    start_time = "-"
    end_time = "-"
    duration_text = "0.0s"
    if equity_curve:
        start_ms = equity_curve[0]["time_ms"]
        end_ms = equity_curve[-1]["time_ms"]
        start_time = str(start_ms)
        end_time = str(end_ms)
        try:
            from datetime import datetime

            start_time = datetime.fromtimestamp(start_ms / 1000).strftime("%H:%M:%S")
            end_time = datetime.fromtimestamp(end_ms / 1000).strftime("%H:%M:%S")
        except Exception:
            pass
        duration_text = f"{(end_ms - start_ms) / 1000:.1f}s"

    subtitle = f"{session_dir.name} | events={summary['events']} | trades={summary['trades_seen']} | variant={summary.get('model_variant', 'as')}"
    fills_text = "No fills in this sample." if not fills else "Animated fill text updates as playback moves."

    html = HTML_TEMPLATE.format(
        subtitle=subtitle,
        final_equity=f"{summary['final_equity_usdt']:.4f} USDT",
        net_pnl=f"{summary['net_pnl_usdt']:.6f} USDT",
        fills=summary["fills"],
        gamma_k=f"{summary['gamma']:.4f} / {summary['k']:.4f}",
        frame_max=max(0, len(equity_curve) - 1),
        fills_text=fills_text,
        start_time=start_time,
        end_time=end_time,
        duration_text=duration_text,
        realized_gross=f"{pnl_breakdown.get('realized_gross_pnl_usdt', 0.0):.6f} USDT",
        inventory_pnl=f"{pnl_breakdown.get('unrealized_inventory_pnl_usdt', 0.0):.6f} USDT",
        gross_before_fees=f"{pnl_breakdown.get('gross_pnl_before_fees_usdt', 0.0):.6f} USDT",
        fees_paid=f"{pnl_breakdown.get('fees_paid_usdt', 0.0):.6f} USDT",
        net_after_fees=f"{pnl_breakdown.get('net_pnl_after_fees_usdt', summary.get('net_pnl_usdt', 0.0)):.6f} USDT",
        latency_pair=f"{int(execution_stats.get('order_latency_ms', 0))} / {int(execution_stats.get('cancel_latency_ms', 0))} ms",
        refresh_pair=f"{int(execution_stats.get('quote_refresh_events', 0))} / {int(execution_stats.get('quote_no_change_events', 0))}",
        request_triplet=f"{int(execution_stats.get('submit_requests', 0))} / {int(execution_stats.get('replace_requests', 0))} / {int(execution_stats.get('cancel_requests', 0))}",
        qty_pair=f"{execution_stats.get('activated_qty', 0.0):.3f} / {execution_stats.get('fill_qty', 0.0):.3f}",
        fill_rate_end=f"{execution_stats.get('fill_rate_vs_activated_qty', 0.0):.1%} / {execution_stats.get('unfilled_active_qty_end', 0.0):.3f}",
        payload_json=json.dumps(
            {
                **payload,
                "orderbook_frames": orderbook_frames,
            },
            ensure_ascii=False,
        ),
    )

    output_path = Path(args.output_html) if args.output_html else summary_path.with_suffix(".html")
    output_path.write_text(html, encoding="utf-8")
    print(f"plot saved: {output_path}")


if __name__ == "__main__":
    main()
