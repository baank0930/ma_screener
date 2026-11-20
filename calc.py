"""calc.py — データ取得と足生成・MA乖離率の計算ロジック（Streamlit 非依存）

  tf = "1H" / "4H" / "1D"
    1H : 1時間足をそのまま使用
    4H : 1時間足を各取引日の寄り付きから 4 本ずつ集約（セッション起点基準）
    1D : 日足をそのまま使用
  MA は「当日進行中（未確定）の最新足の現在値も含む」直近 N 本の終値平均。
"""

from __future__ import annotations

import io
import contextlib
import logging
import re
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import yfinance as yf

logging.getLogger("yfinance").setLevel(logging.CRITICAL)  # ERROR ログの洪水を止める

JST = "Asia/Tokyo"

TF_INFO = {
    "1H": {"label": "1時間足", "src_period": "730d", "src_interval": "1h", "hours": 1},
    "4H": {"label": "4時間足", "src_period": "730d", "src_interval": "1h", "hours": 4},
    "1D": {"label": "日足",     "src_period": "5y",   "src_interval": "1d", "hours": 24},
}


# ---------------------------------------------------------------------------
# 入力
# ---------------------------------------------------------------------------
def parse_tickers(raw: str) -> list[str]:
    """カンマ・読点・空白・改行区切りで受け取り、銘柄コードらしいものだけ通す。"""
    raw = (raw or "").replace("、", ",").replace("，", ",")
    raw = re.sub(r"[\s\n\r]+", ",", raw)
    out: list[str] = []
    for s in raw.split(","):
        s = s.strip().upper()
        if not s:
            continue
        if "/" in s or s.endswith(".JSON") or not re.fullmatch(r"[A-Z0-9\^\.\-\=]{1,15}", s):
            continue
        if s not in out:
            out.append(s)
    return out


# ---------------------------------------------------------------------------
# 足の生成
# ---------------------------------------------------------------------------
def aggregate(df: pd.DataFrame, n: int) -> pd.DataFrame:
    """各取引日の最初の足を起点に n 本ずつまとめて n 倍足を作る。"""
    df = df.dropna(subset=["Close"])
    if df.empty:
        return df
    seq = pd.Series(range(len(df)), index=df.index)
    day = pd.Series(df.index.date, index=df.index).astype(str)
    grp = day + "#" + (seq.groupby(day.values).cumcount() // n).astype(str)
    g = df.groupby(grp, sort=False)
    out = pd.DataFrame({
        "Open":   g["Open"].first(),
        "High":   g["High"].max(),
        "Low":    g["Low"].min(),
        "Close":  g["Close"].last(),
        "Volume": g["Volume"].sum(),
        "bars":   g["Close"].count(),
        "start":  g.apply(lambda x: x.index[0]),
    })
    out.index = pd.to_datetime(out["start"])
    return out.sort_index()


def _short_name(tk: yf.Ticker, fallback: str) -> str:
    for getter in ("get_info", "info"):
        try:
            info = getattr(tk, getter)
            info = info() if callable(info) else info
            for k in ("shortName", "longName", "displayName"):
                if info.get(k):
                    return str(info[k])
        except Exception:
            continue
    return fallback


# ---------------------------------------------------------------------------
# 1 銘柄分
# ---------------------------------------------------------------------------
def fetch_one(symbol: str, tf: str = "4H", ma_len: int = 60) -> dict:
    info = TF_INFO.get(tf, TF_INFO["4H"])
    rec = dict(code=symbol, name=symbol, price=None, ma=None, dev=None, diff=None,
               pos="-", bars=0, partial=False, last="-", note="", tf=tf)
    try:
        with contextlib.redirect_stderr(io.StringIO()):
            tk = yf.Ticker(symbol)
            df = tk.history(period=info["src_period"], interval=info["src_interval"],
                            auto_adjust=False)
    except Exception as e:
        rec["note"] = f"取得失敗（{type(e).__name__}）"
        return rec

    if df is None or df.empty:
        rec["note"] = "データなし（銘柄コードをご確認ください）"
        return rec

    df = df[["Open", "High", "Low", "Close", "Volume"]].copy()
    bars_tf = aggregate(df, info["hours"]) if tf == "4H" else df
    bars_tf = bars_tf.dropna(subset=["Close"])
    if bars_tf.empty:
        rec["note"] = "足を作成できませんでした"
        return rec

    if "bars" not in bars_tf:
        bars_tf = bars_tf.copy()
        bars_tf["bars"] = 1

    bars_tf["MA"] = bars_tf["Close"].rolling(ma_len).mean()
    last = bars_tf.iloc[-1]
    rec["price"] = float(last["Close"])
    rec["bars"] = int(len(bars_tf))
    rec["partial"] = bool(int(last["bars"]) < info["hours"]) if tf == "4H" else False
    try:
        rec["last"] = bars_tf.index[-1].tz_convert(JST).strftime(
            "%m/%d %H:%M" if tf != "1D" else "%Y/%m/%d")
    except Exception:
        rec["last"] = str(bars_tf.index[-1])[:16]

    ma = last["MA"]
    if pd.notna(ma) and float(ma) != 0:
        rec["ma"] = float(ma)
        rec["dev"] = (rec["price"] - rec["ma"]) / rec["ma"] * 100.0
        rec["diff"] = rec["price"] - rec["ma"]
        rec["pos"] = "上" if rec["dev"] > 0 else ("下" if rec["dev"] < 0 else "＝")
    else:
        rec["note"] = f"MA{ma_len}算出に不足（{len(bars_tf)}本／必要{ma_len}本）"

    rec["name"] = _short_name(tk, symbol)
    return rec


def fetch_many(symbols: list[str], tf: str = "4H", ma_len: int = 60,
               max_workers: int = 8) -> list[dict]:
    if not symbols:
        return []
    with ThreadPoolExecutor(max_workers=min(max_workers, len(symbols))) as ex:
        return list(ex.map(lambda s: fetch_one(s, tf, ma_len), symbols))


# ---------------------------------------------------------------------------
# 並べ替え（買う候補）
# ---------------------------------------------------------------------------
def split_groups(recs: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    """① 現在値 ≧ MA（乖離率の降順）／② 現在値 < MA（降順）／③ 算出不可"""
    ok = [r for r in recs if r["dev"] is not None]
    buy = sorted([r for r in ok if r["price"] >= r["ma"]], key=lambda r: -r["dev"])
    below = sorted([r for r in ok if r["price"] < r["ma"]], key=lambda r: -r["dev"])
    ng = [r for r in recs if r["dev"] is None]
    return buy, below, ng


# ---------------------------------------------------------------------------
# ダウンロード用 HTML（PC＝表 / iPhone＝カード表示に自動で切り替え）
# ---------------------------------------------------------------------------
def _badge_style(dev):
    if dev is None:
        return "#8a94a6", "#f1f3f7"
    mag = min(abs(dev), 15.0) / 15.0
    if dev > 0:
        return "#0b7a3b", f"rgba(22,163,74,{0.10 + 0.45 * mag:.2f})"
    return "#b42318", f"rgba(220,38,38,{0.10 + 0.45 * mag:.2f})"


def _f2(v):
    return "-" if v is None else f"{v:,.2f}"


def _fp(v):
    return "-" if v is None else f"{v:+.2f}%"


CSS = """
:root{color-scheme:light}
body{margin:0;padding:14px;background:#f4f6fa;color:#111827;
  font-family:-apple-system,BlinkMacSystemFont,'Hiragino Sans','Noto Sans JP',Meiryo,sans-serif;
  -webkit-text-size-adjust:100%}
.card{background:#fff;border:1px solid #e3e8ef;border-radius:16px;padding:14px 12px;
  box-shadow:0 2px 10px rgba(16,24,40,.06);max-width:1180px;margin:0 auto}
h1{font-size:17px;margin:0 0 2px}
.ts{font-size:12px;color:#6b7280;margin-bottom:10px}
.chips{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:6px}
.chip{font-size:12px;padding:5px 10px;border-radius:999px;font-weight:700;background:#f1f3f7;color:#4b5563}
.chip.g{background:#e8f5ee;color:#0b7a3b}
.chip.r{background:#fdeceb;color:#b42318}
h2{font-size:14px;margin:18px 0 6px}
h2.g{color:#0b7a3b}
h2.r{color:#b42318}
.sub{font-size:11px;color:#9aa3b2;font-weight:400;margin-left:6px}
table{border-collapse:collapse;width:100%;font-size:12.5px;font-variant-numeric:tabular-nums}
th{font-size:11px;font-weight:600;color:#5b6577;background:#f7f9fc;border-bottom:2px solid #e3e8ef;
  padding:8px 6px;white-space:nowrap;text-align:right}
th:nth-child(2),th:nth-child(5){text-align:left}
th:nth-child(1),th:nth-child(3),th:nth-child(9){text-align:center}
td{border-bottom:1px solid #eef1f6;padding:9px 6px;white-space:nowrap}
td.v,td.num,td.dev{text-align:right}
td.pos,td.last{text-align:center}
td.code{font-family:ui-monospace,Menlo,monospace;font-weight:700}
td.name{max-width:190px;overflow:hidden;text-overflow:ellipsis;color:#4b5563}
td.last{color:#4b5563;font-size:11.5px}
.up{color:#0b7a3b;font-weight:700}
.dn{color:#b42318;font-weight:700}
.badge{display:inline-block;min-width:66px;padding:3px 6px;border-radius:6px;font-weight:700}
.trk{display:inline-block;width:38px;height:4px;margin-left:6px;vertical-align:middle;
  background:#eef1f6;border-radius:2px;overflow:hidden}
.trk i{display:block;height:100%}
.st{color:#f59e0b;font-weight:700}
.empty{text-align:center;color:#9aa3b2;padding:14px}
.ng{color:#b42318;font-size:12px;font-weight:400}
ul.ng{margin:0 0 0 18px;padding:0;line-height:1.8}
.foot{margin-top:14px;font-size:11px;color:#8a94a6;line-height:1.8}
.wrap{overflow-x:auto;-webkit-overflow-scrolling:touch}

/* ---- iPhone（幅560px以下）は1銘柄＝1カードに組み替え（横スクロールなし） ---- */
@media (max-width:560px){
  body{padding:10px}
  .card{padding:12px 10px;border-radius:14px}
  h1{font-size:16px}
  .wrap{overflow:visible}
  table,tbody{display:block;width:100%}
  thead{display:none}
  tr.r{display:grid;align-items:center;
    grid-template-columns:auto auto 1fr auto;
    grid-template-areas:
      "code pos . dev"
      "name name name name"
      "px ma bars last";
    column-gap:7px;row-gap:5px;
    border:1px solid #e3e8ef;border-radius:12px;padding:10px 11px;margin-bottom:8px;background:#fff;
    box-shadow:0 1px 4px rgba(16,24,40,.04)}
  tr.r td{border:none;padding:0;white-space:nowrap;text-align:left;font-size:12px}
  td.num{display:none}
  td.code{grid-area:code;font-size:14.5px}
  td.pos{grid-area:pos;font-size:11px;font-weight:800}
  td.dev{grid-area:dev;justify-self:end;text-align:right}
  td.dev .badge{font-size:14px;min-width:0;padding:3px 9px;border-radius:8px}
  td.name{grid-area:name;color:#6b7280;font-size:11px;
    overflow:hidden;text-overflow:ellipsis;min-width:0}
  td.px{grid-area:px}
  td.ma{grid-area:ma}
  td.bars{grid-area:bars}
  td.last{grid-area:last;justify-self:end;text-align:right;font-size:10.5px;color:#8a94a6}
  tr.r td.px{font-weight:700;color:#111827}
  tr.r td.ma,tr.r td.bars{font-weight:600;color:#4b5563}
  tr.r td.px::before,tr.r td.ma::before,tr.r td.bars::before{
    content:attr(data-l);font-size:9.5px;font-weight:400;color:#9aa3b2;margin-right:4px}
  .trk{display:none}
  .foot{font-size:10.5px}
}
"""


def build_html(recs: list[dict], tf: str = "4H", ma_len: int = 60) -> str:
    import html as _html

    label = TF_INFO.get(tf, {}).get("label", tf)
    buy, below, ng = split_groups(recs)
    ts = pd.Timestamp.now(tz=JST).strftime("%Y-%m-%d %H:%M")

    def row(i, r):
        fg, bg = _badge_style(r["dev"])
        w = 0 if r["dev"] is None else min(abs(r["dev"]) / 15.0 * 100, 100)
        star = "<sup class='st'>*</sup>" if r["partial"] else ""
        pos = "上" if r["pos"] == "上" else ("下" if r["pos"] == "下" else "-")
        pcls = "up" if r["pos"] == "上" else "dn"
        return (f"<tr class='r'><td class='num'>{i}</td>"
                f"<td class='code'>{_html.escape(r['code'])}</td>"
                f"<td class='pos {pcls}'>{pos}</td>"
                f"<td class='dev'><span class='badge' style='color:{fg};background:{bg}'>{_fp(r['dev'])}</span>"
                f"<span class='trk'><i style='width:{w:.0f}%;background:{fg}'></i></span></td>"
                f"<td class='name'>{_html.escape(r['name'])}</td>"
                f"<td class='v px' data-l='現在値'>{_f2(r['price'])}</td>"
                f"<td class='v ma' data-l='MA{ma_len}'>{_f2(r['ma'])}</td>"
                f"<td class='v bars' data-l='本数'>{r['bars']}{star}</td>"
                f"<td class='last'>{_html.escape(r['last'])}</td></tr>")

    def table(group):
        body = "".join(row(i, r) for i, r in enumerate(group, 1)) or \
               "<tr><td colspan='9' class='empty'>該当なし</td></tr>"
        return ("<table><thead><tr><th>#</th><th>コード</th><th>上/下</th><th>乖離率</th>"
                f"<th>銘柄名</th><th>現在値</th><th>MA{ma_len}</th>"
                "<th>本数</th><th>最終足</th></tr></thead><tbody>" + body + "</tbody></table>")

    ng_html = ""
    if ng:
        items = "".join(f"<li><b>{_html.escape(r['code'])}</b> … {_html.escape(r['note'])}</li>" for r in ng)
        ng_html = f"<h3 class='ng'>算出不可</h3><ul class='ng'>{items}</ul>"

    return f"""<!doctype html><html lang="ja"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{label} MA{ma_len} 乖離率一覧</title><style>{CSS}</style>
<div class="card">
  <h1>{label} MA{ma_len} 乖離率一覧</h1>
  <div class="ts">{ts} JST</div>
  <div class="chips">
    <span class="chip g">買い候補（MA{ma_len}以上） {len(buy)}</span>
    <span class="chip r">MA{ma_len}割れ {len(below)}</span>
    <span class="chip">算出不可 {len(ng)}</span>
    <span class="chip">対象 {len(recs)} 銘柄</span>
  </div>
  <h2 class="g">① 買い候補：現在値 ≧ MA{ma_len}<span class="sub">乖離率の降順</span></h2>
  <div class="wrap">{table(buy)}</div>
  <h2 class="r">② 参考：現在値 &lt; MA{ma_len}<span class="sub">乖離率の降順</span></h2>
  <div class="wrap">{table(below)}</div>
  {ng_html}
  <div class="foot">
    ・{label}：1時間足を各取引日の寄り付きから4本ずつ集約（4H選択時）。<br>
    ・MA{ma_len}は当日進行中（未確定）の最新足の現在値も含む直近{ma_len}本の終値平均。
      <span class="st">*</span> は未確定足を含む本数。<br>
    ・乖離率＝(現在値−MA{ma_len})／MA{ma_len}×100。データ提供: Yahoo Finance（yfinance）。
  </div>
</div></html>"""


def to_csv_bytes(recs: list[dict], tf: str, ma_len: int) -> bytes:
    df = pd.DataFrame([{
        "code": r["code"], "shortName": r["name"],
        "price": None if r["price"] is None else round(r["price"], 2),
        f"MA{ma_len}_{tf}": None if r["ma"] is None else round(r["ma"], 2),
        "deviation_pct": None if r["dev"] is None else round(r["dev"], 2),
        "position": r["pos"], "bars": r["bars"],
        "partial": r["partial"], "last_bar_jst": r["last"], "note": r["note"],
    } for r in recs])
    return df.to_csv(index=False).encode("utf-8-sig")
