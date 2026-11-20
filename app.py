"""app.py — MA乖離スクリーナー（Streamlit / iPhone最優先 UI）

  GitHub にこのフォルダを push → Streamlit Community Cloud で app.py を指定するだけで公開できます。
  ローカル:  streamlit run app.py
"""

from __future__ import annotations

import html as _html

import pandas as pd
import streamlit as st

from calc import TF_INFO, JST, build_html, fetch_many, parse_tickers, split_groups, to_csv_bytes

st.set_page_config(
    page_title="MA乖離スクリーナー",
    page_icon="📈",
    layout="centered",              # iPhone では画面幅いっぱいに使う
    initial_sidebar_state="collapsed",
)

DEFAULT_TICKERS = "7203.T, 6758.T, 9984.T, AAPL, NVDA, MSFT"

# ---------------------------------------------------------------------------
# スマホ向けスタイル
# ---------------------------------------------------------------------------
st.markdown("""
<style>
  header[data-testid="stHeader"]{height:2.1rem;background:transparent}
  [data-testid="stToolbar"]{right:.3rem;top:.1rem}
  [data-testid="stDecoration"]{display:none}
  .block-container{padding:2.6rem 0.85rem 3rem;max-width:760px}
  h1,h2,h3{letter-spacing:-.01em}
  .hero{display:flex;align-items:baseline;justify-content:space-between;gap:8px;margin:-.2rem 0 .1rem}
  .hero .t{font-size:19px;font-weight:800;letter-spacing:-.02em}
  .hero .s{font-size:11px;color:#8a94a6;white-space:nowrap}
  .chips{display:flex;gap:6px;flex-wrap:wrap;margin:.35rem 0 .1rem}
  .chip{font-size:12px;padding:5px 10px;border-radius:999px;font-weight:700;background:#f1f3f7;color:#4b5563}
  .chip.g{background:#e8f5ee;color:#0b7a3b}
  .chip.r{background:#fdeceb;color:#b42318}
  .sec{display:flex;align-items:baseline;gap:8px;margin:16px 0 8px}
  .sec .h{font-size:14px;font-weight:800}
  .sec .g{color:#0b7a3b}.sec .r{color:#b42318}
  .sec .n{font-size:11px;color:#9aa3b2}
  .card{background:#fff;border:1px solid #e3e8ef;border-radius:14px;padding:11px 12px;margin-bottom:8px;
        box-shadow:0 1px 6px rgba(16,24,40,.05)}
  .card.dim{opacity:.92}
  .c-top{display:flex;align-items:center;justify-content:space-between;gap:8px}
  .c-l{display:flex;align-items:baseline;gap:7px;min-width:0}
  .c-rk{font-size:11px;color:#c3c9d4;font-weight:700;min-width:14px}
  .c-code{font-family:ui-monospace,Menlo,monospace;font-size:15px;font-weight:800;color:#111827;
          white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .c-pos{font-size:11px;font-weight:800}
  .c-pos.up{color:#0b7a3b}.c-pos.dn{color:#b42318}
  .c-badge{font-size:15px;font-weight:800;font-variant-numeric:tabular-nums;padding:3px 9px;border-radius:8px;white-space:nowrap}
  .c-name{font-size:11.5px;color:#6b7280;margin:2px 0 8px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .c-vals{display:flex;gap:14px;font-variant-numeric:tabular-nums;flex-wrap:wrap}
  .c-vals .k{font-size:10px;color:#9aa3b2;display:block;letter-spacing:.04em}
  .c-vals .v{font-size:14px;font-weight:700;color:#111827}
  .c-vals .v.m{color:#4b5563;font-weight:600}
  .trk{height:5px;background:#eef1f6;border-radius:3px;overflow:hidden;margin:9px 0 7px}
  .trk i{display:block;height:100%}
  .c-foot{display:flex;justify-content:space-between;gap:8px;font-size:10.5px;color:#8a94a6;font-variant-numeric:tabular-nums}
  .note{font-size:11px;color:#8a94a6;line-height:1.8;margin-top:10px}
  div[data-testid="stHorizontalBlock"]{gap:.4rem}
  .stButton>button,.stDownloadButton>button{width:100%;border-radius:11px;font-weight:700;min-height:44px}
  textarea{font-size:15px !important}
</style>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# 取得（キャッシュ）
# ---------------------------------------------------------------------------
@st.cache_data(ttl=300, show_spinner=False)
def load(symbols: tuple[str, ...], tf: str, ma_len: int) -> list[dict]:
    return fetch_many(list(symbols), tf, ma_len)


def fmt(v, spec=",.2f"):
    return "-" if v is None else format(v, spec)


def badge_colors(dev):
    if dev is None:
        return "#8a94a6", "#f1f3f7"
    mag = min(abs(dev), 15.0) / 15.0
    return (("#0b7a3b", f"rgba(22,163,74,{0.10 + 0.45 * mag:.2f})") if dev > 0
            else ("#b42318", f"rgba(220,38,38,{0.10 + 0.45 * mag:.2f})"))


def card_html(rank, r, ma_len, tf):
    fg, bg = badge_colors(r["dev"])
    w = 0 if r["dev"] is None else min(abs(r["dev"]) / 15.0 * 100, 100)
    star = "*" if r["partial"] else ""
    pos_txt = "▲ 上" if r["pos"] == "上" else ("▼ 下" if r["pos"] == "下" else "—")
    pos_cls = "up" if r["pos"] == "上" else "dn"
    dim = "" if r["pos"] == "上" else " dim"
    return f"""<div class="card{dim}">
  <div class="c-top">
    <div class="c-l"><span class="c-rk">{rank}</span><span class="c-code">{_html.escape(r['code'])}</span>
      <span class="c-pos {pos_cls}">{pos_txt}</span></div>
    <span class="c-badge" style="color:{fg};background:{bg}">{fmt(r['dev'], '+.2f') + '%'}</span>
  </div>
  <div class="c-name">{_html.escape(r['name'])}</div>
  <div class="c-vals">
    <div><span class="k">現在値</span><span class="v">{fmt(r['price'])}</span></div>
    <div><span class="k">MA{ma_len}({tf})</span><span class="v m">{fmt(r['ma'])}</span></div>
    <div><span class="k">乖離幅</span><span class="v m">{fmt(r['diff'], '+,.2f')}</span></div>
  </div>
  <div class="trk"><i style="width:{w:.0f}%;background:{fg}"></i></div>
  <div class="c-foot"><span>{tf} 本数 {r['bars']}{star}</span><span>最終足 {_html.escape(r['last'])} JST</span></div>
</div>"""


# ---------------------------------------------------------------------------
# 操作パネル（iPhone で押しやすい縦積み）
# ---------------------------------------------------------------------------
st.markdown('<div class="hero"><div class="t">📈 MA乖離スクリーナー</div>'
            f'<div class="s">{pd.Timestamp.now(tz=JST).strftime("%m/%d %H:%M")} JST</div></div>',
            unsafe_allow_html=True)

# URL パラメータでウォッチリストを保持（iPhone のホーム画面ブックマークでも復元）
if "tickers_input" not in st.session_state:
    try:
        st.session_state["tickers_input"] = st.query_params.get("t", DEFAULT_TICKERS)
    except Exception:
        st.session_state["tickers_input"] = DEFAULT_TICKERS

raw = st.text_area("銘柄コード（カンマ・改行・空白区切り）", height=86,
                   placeholder="7203.T, 6758.T, AAPL, NVDA …", key="tickers_input")

seg = getattr(st, "segmented_control", None)
if seg:
    tf = seg("足", list(TF_INFO.keys()), default="4H", key="tf") or "4H"
else:  # 旧 Streamlit 用フォールバック
    tf = st.radio("足", list(TF_INFO.keys()), index=0, horizontal=True, key="tf")

with st.expander("⚙️ 設定（MA期間・再取得）", expanded=False):
    ma_len = st.number_input("MA期間（本）", min_value=5, max_value=400, value=60, step=5)
    if st.button("🔄 最新データで再取得"):
        load.clear()
        st.rerun()
    st.caption("データは5分間キャッシュされます。足を切り替えると自動で再計算します。")

symbols = parse_tickers(raw)
try:
    st.query_params["t"] = ",".join(symbols)
except Exception:
    pass

if not symbols:
    st.info("銘柄コードを1つ以上入力してください（例: 7203.T, AAPL）")
    st.stop()

with st.spinner(f"{len(symbols)}銘柄を取得中…（{TF_INFO[tf]['label']} / MA{ma_len}）"):
    recs = load(tuple(symbols), tf, ma_len)

buy, below, ng = split_groups(recs)
label = TF_INFO[tf]["label"]

st.markdown(
    '<div class="chips">'
    f'<span class="chip g">買い候補 {len(buy)}</span>'
    f'<span class="chip r">MA{ma_len}割れ {len(below)}</span>'
    f'<span class="chip">算出不可 {len(ng)}</span>'
    f'<span class="chip">対象 {len(recs)}</span>'
    '</div>', unsafe_allow_html=True)

# ① 買い候補
st.markdown(f'<div class="sec"><span class="h g">① 買い候補：現在値 ≧ MA{ma_len}</span>'
            f'<span class="n">{len(buy)}銘柄・乖離率の降順</span></div>', unsafe_allow_html=True)
if buy:
    st.markdown("".join(card_html(i, r, ma_len, tf) for i, r in enumerate(buy, 1)), unsafe_allow_html=True)
else:
    st.caption("該当なし（全銘柄が MA を下回っています）")

# ② MA割れ（参考）
with st.expander(f"② 参考：MA{ma_len}割れ（{len(below)}銘柄・降順）", expanded=False):
    if below:
        st.markdown("".join(card_html(i, r, ma_len, tf) for i, r in enumerate(below, 1)), unsafe_allow_html=True)
    else:
        st.caption("該当なし")

# ③ 算出不可
if ng:
    with st.expander(f"⚠️ 算出不可（{len(ng)}銘柄）", expanded=False):
        for r in ng:
            st.markdown(f"- **{_html.escape(r['code'])}** … {_html.escape(r['note'])}")

# ダウンロード
st.markdown('<div class="sec"><span class="h">📥 エクスポート</span></div>', unsafe_allow_html=True)
stamp = pd.Timestamp.now(tz=JST).strftime("%Y%m%d_%H%M")
c1, c2 = st.columns(2)
with c1:
    st.download_button("📄 HTML", data=build_html(recs, tf, ma_len).encode("utf-8"),
                       file_name=f"ma{ma_len}_{tf}_{stamp}.html", mime="text/html",
                       use_container_width=True)
with c2:
    st.download_button("📊 CSV", data=to_csv_bytes(recs, tf, ma_len),
                       file_name=f"ma{ma_len}_{tf}_{stamp}.csv", mime="text/csv",
                       use_container_width=True)

src_note = ("1時間足を各取引日の寄り付きから4本ずつ集約" if tf == "4H"
            else "配信される素の1時間足" if tf == "1H" else "配信される素の日足")
st.markdown(
    f'<div class="note">・{tf}（{label}）: {src_note}。<br>'
    f'・MA{ma_len} は当日進行中（未確定）の最新足の現在値も含む直近{ma_len}本の終値平均。'
    f'<b>*</b> は未確定足を含む本数。<br>'
    f'・乖離率＝(現在値−MA{ma_len})／MA{ma_len}×100。データ提供: Yahoo Finance（yfinance）。投資判断は自己責任で。</div>',
    unsafe_allow_html=True)
