# 📈 MA乖離スクリーナー（Streamlit / iPhone 最優先）

4時間足（1H・1Dに切替可）の **MA60 乖離率**を一覧表示するスクリーナー。
GitHub に置いて **Streamlit Community Cloud** で公開すれば、iPhone の Safari からいつでも使えます。

- **4H 基本**：1時間足を各取引日の寄り付きから4本ずつ集約して4時間足を生成（TradingView 等と同じセッション起点基準）
- **1H / 1D も分岐**：セグメントボタンで切替。MA本数も変更可
- **並びは「買う候補」**：① 現在値 ≧ MA（乖離率の降順）→ ② 参考：MA割れ（降順）→ ③ 算出不可
- **最新データ**：当日進行中（未確定）の足の現在値も MA に算入（`*` で明示）
- **iPhone 最優先 UI**：カード型レイアウト・44px のタップ領域・親指で届く縦積み
- **shortName 表示**：足取得と同じ通信で銘柄名も取得（取れない場合は自動フォールバック）
- **エクスポート**：HTML（単体で開けるレスポンシブ表）と CSV をダウンロード（`shortName` 列入り）
- **ウォッチリストを URL に保持**（`?t=7203.T,AAPL`）→ ホーム画面に追加しておけば毎回同じ銘柄で開く

---

## ファイル構成

```
ma_screener/
├── app.py                 # Streamlit 本体（UI・iPhone 向け）
├── calc.py                # データ取得 / 4H・1H・1D 足生成 / MA・乖離率 / HTML出力
├── requirements.txt
├── .streamlit/config.toml # テーマ・設定（headless 等）
├── .gitignore
└── README.md
```

## ローカルで動かす

```bash
pip install -r requirements.txt
streamlit run app.py
```

## GitHub に上げる

```bash
cd ma_screener
git init
git add .
git commit -m "MA screener: streamlit app"
git branch -M main
git remote add origin https://github.com/<あなたのユーザー名>/ma_screener.git
git push -u origin main
```

（GitHub の Web UI からでも可：**New repository** → **Add file → Upload files** でこのフォルダ内のファイルをドラッグ＆ドロップ）

## Streamlit Community Cloud で公開（無料）

1. <https://share.streamlit.io> に GitHub アカウントでログイン
2. **Create app** → **Deploy a public app from GitHub**
3. Repository：`<ユーザー名>/ma_screener` ／ Branch：`main` ／ **Main file path：`app.py`**
4. **Deploy**（初回は 1〜2 分）→ `https://<app名>.streamlit.app` が発行されます
5. 以降は `git push` するだけで自動再デプロイ

> 依存は `requirements.txt` から自動インストールされます。秘密情報は不要（APIキーなし）。
> リージョンや Python バージョンは既定で問題ありません。

## iPhone での使い方

1. Safari で公開 URL を開く
2. **共有ボタン → 「ホーム画面に追加」** でアプリのように起動（例：`...streamlit.app/?t=7203.T,6758.T,AAPL,NVDA`）
3. 銘柄コード欄はカンマ・改行・空白区切りで複数入力（`、` も可）
4. 「足」で **4H / 1H / 1D** を切替 → 自動で再計算
5. 「⚙️ 設定」内で **MA期間**変更と「最新データで再取得」（キャッシュ 5 分）

## 銘柄名（shortName）の取得

`calc.py` の `_short_name()` が **追加リクエストなしで確実に取れる順** にフォールバックします。

1. **足取得と同じ `history()` のレスポンス `meta`** に入っている `shortName` → `longName` → `displayName`
   （＝通信1回で名前まで揃う。レート制限の影響を受けにくく、最も安定）
2. `quoteSummary`（`Ticker.get_info()` / `Ticker.info`）
3. Yahoo 検索 API（指数・特殊銘柄向け）
4. それでも取れなければ銘柄コードを表示

取得した名前はメモリ（`NAME_CACHE`）に保持し、`fetch_many()` は並列取得なので銘柄数が増えても待ち時間はほぼ変わりません。
`get_names(symbols)` で名前だけを先に引くこともできます（一覧の即時表示用）。

## カスタマイズ

- **MA期間**：`⚙️ 設定` の数値入力、または `app.py` の `value=60`
- **既定の銘柄**：`app.py` の `DEFAULT_TICKERS`
- **足を増やす**（例：2H・週足）：`calc.py` の `TF_INFO` に追記（`1H` 系は 1時間足を N 本集約、`1D` 系は日足をそのまま）
- **色**：`.streamlit/config.toml` の `primaryColor` と、`app.py` 内 `badge_colors()` のしきい値（既定 ±15% で最大）

## 仕様メモ

| 足 | 元データ | 本数 | 備考 |
|---|---|---|---|
| 4H（基本） | 1時間足 730日 | 4本/セッション | 寄り付き起点。東証は 9:00–13:00 / 13:00–15:00 の2本 |
| 1H | 1時間足 730日 | 1本 | 直近 730 日（約 5,000 本） |
| 1D | 日足 5年 | 1本 | 約 1,200 本 |

- MA = 直近 N 本の終値平均（**未確定の最新足の現在値も含む**）
- 乖離率 =（現在値 − MA）／MA × 100［%］
- データ提供：Yahoo Finance（yfinance）。**投資判断は自己責任で**。Yahoo 側のレート制限で一時的に取得失敗する場合は「最新データで再取得」をお試しください。
