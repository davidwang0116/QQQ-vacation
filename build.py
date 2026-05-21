"""
build.py — 下载最新 QQQ 数据，生成可拖动的交互式回测页面。

用法:
    pip install yfinance pandas
    python build.py

产物:
    index.html  (单文件，数据已嵌入，可直接 GitHub Pages 部署)
"""

import json
import os
import sys
from datetime import datetime

try:
    import pandas as pd
    import yfinance as yf
except ImportError:
    print("缺少依赖，请先运行: pip install yfinance pandas", file=sys.stderr)
    sys.exit(1)


def fetch_qqq() -> pd.DataFrame:
    """从 Yahoo Finance 下载 QQQ 全部历史日线 (1999-03 起)。"""
    print("→ 正在从 Yahoo Finance 下载 QQQ 数据 ...")
    df = yf.download(
        "QQQ",
        start="1999-03-10",
        end=None,                 # 自动取到今天
        auto_adjust=False,        # 同时拿到 Close 和 Adj Close
        progress=False,
        threads=False,
    )
    if df.empty:
        raise RuntimeError("Yahoo Finance 返回空数据。检查网络。")

    # yfinance 新版可能返回 MultiIndex columns，展平一下
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df = df.reset_index()
    # 兼容字段名: 优先用 Adj Close，没有就用 Close
    price_col = "Adj Close" if "Adj Close" in df.columns else "Close"
    df = df.rename(columns={price_col: "Price", "Date": "Date"})
    df = df[["Date", "Price"]].dropna()
    df["Date"] = pd.to_datetime(df["Date"])
    df = df.sort_values("Date").reset_index(drop=True)
    print(f"  下载完成: {len(df)} 行, {df['Date'].iloc[0].date()} → {df['Date'].iloc[-1].date()}")
    return df


def prepare_data(df: pd.DataFrame) -> dict:
    """计算 MA200 并准备前端用的数据包。"""
    df["MA200"] = df["Price"].rolling(200).mean()
    df = df.dropna(subset=["MA200"]).reset_index(drop=True)
    df["ret"] = df["Price"].pct_change().fillna(0)
    df["ratio"] = df["Price"] / df["MA200"]

    # 完整数据 (用于精确回测): ret + ratio
    full = {
        "dates": df["Date"].dt.strftime("%Y-%m-%d").tolist(),
        "rets":  [round(x, 6) for x in df["ret"].tolist()],
        "ratios":[round(x, 5) for x in df["ratio"].tolist()],
    }

    # 降采样数据 (用于绘图): ~600 个点
    n = len(df)
    step = max(1, n // 600)
    idx = list(range(0, n, step))
    if idx[-1] != n - 1:
        idx.append(n - 1)

    sampled = {
        "dates":  [df["Date"].iloc[i].strftime("%Y-%m-%d") for i in idx],
        "price":  [round(float(df["Price"].iloc[i]), 2)  for i in idx],
        "ma200":  [round(float(df["MA200"].iloc[i]), 2)  for i in idx],
        "ratio":  [round(float(df["ratio"].iloc[i]), 4)  for i in idx],
    }

    return {
        "full": full,
        "sampled": sampled,
        "totalDays": len(df),
        "years": round(len(df) / 252, 3),
        "startDate": full["dates"][0],
        "endDate":   full["dates"][-1],
        "generatedAt": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
    }


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>QQQ · 趋势放假分界线</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
    background: #0f1419; color: #e6e9ef; padding: 24px; min-height: 100vh;
  }
  .container { max-width: 1100px; margin: 0 auto; }
  h1 { font-size: 24px; font-weight: 600; margin-bottom: 6px; color: #f8fafc; }
  .subtitle { font-size: 13px; color: #64748b; margin-bottom: 6px; }
  .meta { font-size: 11px; color: #475569; margin-bottom: 28px; }
  .panel {
    background: #1a212d; border-radius: 10px; padding: 24px 28px;
    margin-bottom: 18px; border: 1px solid #232b3a;
  }
  .slider-row { display: flex; align-items: center; gap: 20px; margin-bottom: 18px; flex-wrap: wrap; }
  .slider-label { font-size: 14px; color: #94a3b8; min-width: 90px; }
  .k-value {
    font-size: 36px; font-weight: 700; color: #60a5fa;
    font-variant-numeric: tabular-nums; min-width: 120px;
    font-family: "SF Mono", Menlo, monospace;
  }
  input[type=range] {
    flex: 1; min-width: 260px; height: 6px; -webkit-appearance: none;
    background: linear-gradient(to right, #7c3aed 0%, #ef4444 50%, #f59e0b 75%, #22c55e 100%);
    border-radius: 3px; outline: none;
  }
  input[type=range]::-webkit-slider-thumb {
    -webkit-appearance: none; width: 22px; height: 22px; border-radius: 50%;
    background: #fff; cursor: pointer; box-shadow: 0 2px 8px rgba(0,0,0,0.4);
    border: 2px solid #60a5fa;
  }
  input[type=range]::-moz-range-thumb {
    width: 22px; height: 22px; border-radius: 50%; background: #fff;
    cursor: pointer; border: 2px solid #60a5fa;
  }
  .stats-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; margin-top: 8px; }
  @media (max-width: 720px) { .stats-grid { grid-template-columns: repeat(2, 1fr); } }
  .stat { background: #131927; border-radius: 8px; padding: 14px 16px; border-left: 3px solid #60a5fa; }
  .stat-label { font-size: 11px; color: #64748b; text-transform: uppercase; letter-spacing: 0.8px; margin-bottom: 6px; }
  .stat-value { font-size: 22px; font-weight: 700; color: #f1f5f9; font-variant-numeric: tabular-nums; font-family: "SF Mono", Menlo, monospace; }
  .stat-sub { font-size: 11px; color: #64748b; margin-top: 3px; }
  .stat.pos { border-left-color: #22c55e; }
  .stat.neg { border-left-color: #ef4444; }
  .stat.pos .stat-value { color: #4ade80; }
  .stat.neg .stat-value { color: #f87171; }
  .chart-title { font-size: 13px; color: #94a3b8; margin-bottom: 12px; font-weight: 500; }
  svg { display: block; width: 100%; height: auto; }
  .axis-label { fill: #64748b; font-size: 10px; font-family: "SF Mono", Menlo, monospace; }
  .gridline { stroke: #232b3a; stroke-width: 1; }
  .footnote { font-size: 11px; color: #475569; line-height: 1.7; margin-top: 14px; }
  .baseline-row {
    display: flex; gap: 24px; font-size: 12px; color: #94a3b8;
    padding: 10px 14px; background: #131927; border-radius: 6px; margin-top: 14px;
  }
  .baseline-row b { color: #cbd5e1; font-family: "SF Mono", Menlo, monospace; }
  .tagline {
    font-size: 13px; color: #94a3b8; font-style: italic;
    margin-top: 10px; padding-left: 14px; border-left: 3px solid #4ade80;
  }
  a { color: #60a5fa; text-decoration: none; }
  a:hover { text-decoration: underline; }
</style>
</head>
<body>
<div class="container">
  <h1>QQQ · 趋势投资者的"放假分界线"</h1>
  <div class="subtitle" id="subtitle">加载中…</div>
  <div class="meta" id="meta"></div>

  <div class="panel">
    <div class="slider-row">
      <div class="slider-label">阈值系数 k</div>
      <input type="range" id="slider" min="0.70" max="1.05" step="0.005" value="0.83">
      <div class="k-value" id="kval">0.830</div>
    </div>
    <div style="font-size: 12px; color: #64748b; margin-top: -8px;">
      当 QQQ 收盘价 &lt; MA200 × k 时空仓（去放假），&ge; 时全仓持有。信号 shift(1) 避免未来函数。
    </div>

    <div class="stats-grid" id="stats"></div>

    <div class="baseline-row">
      <span>基准 · 长持 QQQ: <b id="bh-total"></b> · 年化 <b id="bh-cagr"></b></span>
    </div>

    <div class="tagline" id="verdict"></div>
  </div>

  <div class="panel">
    <div class="chart-title">QQQ 价格 vs MA200 × k 阈值（红色阴影 = 应该放假的区间）</div>
    <svg id="priceChart" viewBox="0 0 1040 320"></svg>
  </div>

  <div class="panel">
    <div class="chart-title">净值曲线对比（对数坐标）</div>
    <svg id="equityChart" viewBox="0 0 1040 320"></svg>
  </div>

  <div class="footnote">
    使用 Adj Close 计算；信号 shift(1) 避免未来函数；不含交易成本、税费、滑点。<br>
    数据源：Yahoo Finance。仅供研究，不构成投资建议。
  </div>
</div>

<script>
const DATA = __DATA__;

const fullRets = DATA.full.rets;
const fullRatios = DATA.full.ratios;
const N = fullRets.length;
const years = DATA.years;

const bhEquity = new Array(N);
{ let e = 1; for (let i = 0; i < N; i++) { e *= (1 + fullRets[i]); bhEquity[i] = e; } }
const bhFinal = bhEquity[N-1];
const bhCagr = Math.pow(bhFinal, 1/years) - 1;

document.getElementById('subtitle').textContent =
  DATA.startDate + ' → ' + DATA.endDate + '  ·  ' + DATA.totalDays + ' 个交易日 · ~' + DATA.years + ' 年';
document.getElementById('meta').textContent = '数据生成于 ' + DATA.generatedAt;
document.getElementById('bh-total').textContent = ((bhFinal - 1) * 100).toFixed(1) + '%';
document.getElementById('bh-cagr').textContent = (bhCagr * 100).toFixed(2) + '%';

function backtest(k) {
  let belowDays = 0;
  for (let i = 0; i < N; i++) if (fullRatios[i] < k) belowDays++;
  const stratEquity = new Array(N);
  let e = 1; stratEquity[0] = 1;
  for (let i = 1; i < N; i++) {
    const sig = fullRatios[i-1] >= k ? 1 : 0;
    e *= (1 + fullRets[i] * sig);
    stratEquity[i] = e;
  }
  return { belowDays, stratEquity, stratFinal: stratEquity[N-1], stratCagr: Math.pow(stratEquity[N-1], 1/years) - 1 };
}

const sampled = DATA.sampled;
const M = sampled.dates.length;
const sampledIdx = [];
{ let j = 0;
  for (let i = 0; i < M; i++) {
    while (j < N && DATA.full.dates[j] !== sampled.dates[i]) j++;
    sampledIdx.push(j);
  }
}

const W = 1040, H = 320;
const PAD = { l: 60, r: 20, t: 14, b: 28 };
const plotW = W - PAD.l - PAD.r;
const plotH = H - PAD.t - PAD.b;
function xPos(i) { return PAD.l + (i / (M - 1)) * plotW; }

const minP = Math.min(...sampled.price, ...sampled.ma200) * 0.9;
const maxP = Math.max(...sampled.price, ...sampled.ma200) * 1.1;
const logMin = Math.log(minP), logMax = Math.log(maxP);
function yPrice(v) { return PAD.t + plotH - ((Math.log(v) - logMin) / (logMax - logMin)) * plotH; }

function drawPriceChart(k) {
  const svg = document.getElementById('priceChart');
  let html = '';
  const niceTicks = [];
  let t = Math.pow(10, Math.floor(Math.log10(minP)));
  while (t <= maxP) { for (const m of [1,2,5]) { const v = t*m; if (v>=minP && v<=maxP) niceTicks.push(v); } t *= 10; }
  for (const v of niceTicks) {
    const y = yPrice(v);
    html += `<line class="gridline" x1="${PAD.l}" y1="${y}" x2="${W-PAD.r}" y2="${y}"/>`;
    html += `<text class="axis-label" x="${PAD.l-6}" y="${y+3}" text-anchor="end">${v}</text>`;
  }
  const years_seen = new Set();
  for (let i = 0; i < M; i++) {
    const y = sampled.dates[i].slice(0,4);
    if (!years_seen.has(y) && parseInt(y) % 4 === 0) {
      years_seen.add(y);
      html += `<text class="axis-label" x="${xPos(i)}" y="${H-10}" text-anchor="middle">${y}</text>`;
    }
  }
  let segStart = -1;
  for (let i = 0; i < M; i++) {
    const below = sampled.ratio[i] < k;
    if (below && segStart < 0) segStart = i;
    if ((!below || i === M-1) && segStart >= 0) {
      const endI = below ? i : i - 1;
      const x1 = xPos(segStart), x2 = xPos(endI);
      html += `<rect x="${x1}" y="${PAD.t}" width="${Math.max(x2-x1,1)}" height="${plotH}" fill="#ef4444" fill-opacity="0.18"/>`;
      segStart = -1;
    }
  }
  let pathK = '';
  for (let i = 0; i < M; i++) pathK += (i===0?'M':'L') + xPos(i) + ',' + yPrice(sampled.ma200[i] * k);
  html += `<path d="${pathK}" stroke="#ef4444" stroke-width="1.2" fill="none" stroke-dasharray="4 3"/>`;
  let pathMA = '';
  for (let i = 0; i < M; i++) pathMA += (i===0?'M':'L') + xPos(i) + ',' + yPrice(sampled.ma200[i]);
  html += `<path d="${pathMA}" stroke="#f59e0b" stroke-width="1" fill="none" stroke-dasharray="2 2" opacity="0.8"/>`;
  let pathPrice = '';
  for (let i = 0; i < M; i++) pathPrice += (i===0?'M':'L') + xPos(i) + ',' + yPrice(sampled.price[i]);
  html += `<path d="${pathPrice}" stroke="#60a5fa" stroke-width="1.5" fill="none"/>`;
  html += `<g transform="translate(${PAD.l+10},${PAD.t+10})" font-family="SF Mono,Menlo,monospace" font-size="11">
    <rect x="0" y="0" width="200" height="60" fill="#0f1419" fill-opacity="0.85" rx="4"/>
    <line x1="8" y1="14" x2="24" y2="14" stroke="#60a5fa" stroke-width="2"/><text x="30" y="18" fill="#cbd5e1">QQQ</text>
    <line x1="8" y1="30" x2="24" y2="30" stroke="#f59e0b" stroke-width="1.5" stroke-dasharray="2 2"/><text x="30" y="34" fill="#cbd5e1">MA200</text>
    <line x1="8" y1="46" x2="24" y2="46" stroke="#ef4444" stroke-width="1.5" stroke-dasharray="4 3"/><text x="30" y="50" fill="#cbd5e1">MA200 × ${k.toFixed(3)}</text>
  </g>`;
  svg.innerHTML = html;
}

function drawEquityChart(stratEquity) {
  const svg = document.getElementById('equityChart');
  const bhSamp = sampledIdx.map(i => bhEquity[i]);
  const stSamp = sampledIdx.map(i => stratEquity[i]);
  const minE = Math.min(...bhSamp, ...stSamp) * 0.9;
  const maxE = Math.max(...bhSamp, ...stSamp) * 1.1;
  const logMinE = Math.log(minE), logMaxE = Math.log(maxE);
  function yEq(v) { return PAD.t + plotH - ((Math.log(v) - logMinE) / (logMaxE - logMinE)) * plotH; }
  let html = '';
  const eqTicks = [];
  let t = Math.pow(10, Math.floor(Math.log10(minE)));
  while (t <= maxE) { for (const m of [1,2,5]) { const v = t*m; if (v>=minE && v<=maxE) eqTicks.push(v); } t *= 10; }
  for (const v of eqTicks) {
    const y = yEq(v);
    html += `<line class="gridline" x1="${PAD.l}" y1="${y}" x2="${W-PAD.r}" y2="${y}"/>`;
    html += `<text class="axis-label" x="${PAD.l-6}" y="${y+3}" text-anchor="end">${v < 1 ? v.toFixed(2) : v}x</text>`;
  }
  const years_seen = new Set();
  for (let i = 0; i < M; i++) {
    const y = sampled.dates[i].slice(0,4);
    if (!years_seen.has(y) && parseInt(y) % 4 === 0) {
      years_seen.add(y);
      html += `<text class="axis-label" x="${xPos(i)}" y="${H-10}" text-anchor="middle">${y}</text>`;
    }
  }
  if (1 >= minE && 1 <= maxE) {
    const y1 = yEq(1);
    html += `<line x1="${PAD.l}" y1="${y1}" x2="${W-PAD.r}" y2="${y1}" stroke="#475569" stroke-width="1" stroke-dasharray="3 3"/>`;
  }
  let p1 = '';
  for (let i = 0; i < M; i++) p1 += (i===0?'M':'L') + xPos(i) + ',' + yEq(bhSamp[i]);
  html += `<path d="${p1}" stroke="#94a3b8" stroke-width="1.6" fill="none"/>`;
  let p2 = '';
  for (let i = 0; i < M; i++) p2 += (i===0?'M':'L') + xPos(i) + ',' + yEq(stSamp[i]);
  html += `<path d="${p2}" stroke="#4ade80" stroke-width="1.8" fill="none"/>`;
  html += `<g transform="translate(${PAD.l+10},${PAD.t+10})" font-family="SF Mono,Menlo,monospace" font-size="11">
    <rect x="0" y="0" width="240" height="46" fill="#0f1419" fill-opacity="0.85" rx="4"/>
    <line x1="8" y1="14" x2="24" y2="14" stroke="#94a3b8" stroke-width="2"/>
    <text x="30" y="18" fill="#cbd5e1">长持 QQQ (${bhFinal.toFixed(2)}x)</text>
    <line x1="8" y1="32" x2="24" y2="32" stroke="#4ade80" stroke-width="2"/>
    <text x="30" y="36" fill="#cbd5e1">放假策略 (${stSamp[M-1].toFixed(2)}x)</text>
  </g>`;
  svg.innerHTML = html;
}

function verdictText(k, diffCagr, pct) {
  if (diffCagr > 1.0) return `🏖️  k=${k.toFixed(3)} 是有效的放假分界线 —— 全年只放 ${pct.toFixed(0)}% 的假，但跑赢长持 +${diffCagr.toFixed(2)}% 年化。`;
  if (diffCagr > 0)   return `📈  k=${k.toFixed(3)} 略有超额收益 (+${diffCagr.toFixed(2)}%)，但优势微弱，可能不值得操作成本。`;
  if (diffCagr > -1)  return `⚖️  k=${k.toFixed(3)} 与长持基本打平 (${diffCagr.toFixed(2)}%)，放假反而错过了反弹。`;
  return `💸  k=${k.toFixed(3)} 跑输长持 ${diffCagr.toFixed(2)}% —— 假放太多了，把上涨也错过了。`;
}

function update(k) {
  document.getElementById('kval').textContent = k.toFixed(3);
  const r = backtest(k);
  const stratTotal = (r.stratFinal - 1) * 100;
  const stratCagr = r.stratCagr * 100;
  const diffCagr = stratCagr - bhCagr * 100;
  const days = r.belowDays;
  const pct = (days / N) * 100;

  document.getElementById('stats').innerHTML = `
    <div class="stat">
      <div class="stat-label">放假天数</div>
      <div class="stat-value">${days}</div>
      <div class="stat-sub">${pct.toFixed(2)}% · 约 ${(days/252).toFixed(1)} 年</div>
    </div>
    <div class="stat ${stratTotal > (bhFinal-1)*100 ? 'pos' : 'neg'}">
      <div class="stat-label">策略总收益</div>
      <div class="stat-value">${stratTotal.toFixed(1)}%</div>
      <div class="stat-sub">终值 ${r.stratFinal.toFixed(2)}x</div>
    </div>
    <div class="stat ${stratCagr > bhCagr*100 ? 'pos' : 'neg'}">
      <div class="stat-label">策略年化</div>
      <div class="stat-value">${stratCagr.toFixed(2)}%</div>
      <div class="stat-sub">vs 长持 ${(bhCagr*100).toFixed(2)}%</div>
    </div>
    <div class="stat ${diffCagr > 0 ? 'pos' : 'neg'}">
      <div class="stat-label">年化超额</div>
      <div class="stat-value">${diffCagr >= 0 ? '+' : ''}${diffCagr.toFixed(2)}%</div>
      <div class="stat-sub">${diffCagr >= 0 ? '跑赢' : '跑输'}长持</div>
    </div>
  `;
  document.getElementById('verdict').textContent = verdictText(k, diffCagr, pct);

  drawPriceChart(k);
  drawEquityChart(r.stratEquity);
}

const slider = document.getElementById('slider');
slider.addEventListener('input', e => update(parseFloat(e.target.value)));
update(parseFloat(slider.value));
</script>
</body>
</html>
"""


def main():
    df = fetch_qqq()
    payload = prepare_data(df)
    html = HTML_TEMPLATE.replace("__DATA__", json.dumps(payload, separators=(",", ":")))

    out_path = os.path.join(os.path.dirname(__file__) or ".", "index.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    size_kb = os.path.getsize(out_path) / 1024
    print(f"→ 已生成 {out_path}  ({size_kb:.1f} KB)")
    print(f"  数据截至 {payload['endDate']}  ·  {payload['totalDays']} 个交易日  ·  ~{payload['years']} 年")
    print("→ 直接打开 index.html 或推送到 GitHub Pages 即可。")


if __name__ == "__main__":
    main()
