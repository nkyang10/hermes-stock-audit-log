# 📊 股票審計記錄 — Stock Audit Log

> **完整嘅 Sim-Trading 決策日誌系統** — 記錄每個 trade decision、portfolio snapshot、研究分析，自動生成靚仔 HTML 網站推上 GitHub Pages。

---

## What — 呢個系統係乜

一個 **CLI + static site generator**，記錄模擬股票交易嘅決策同分析。每個 entry（決策、快照、研究）入 SQLite DB，然後 build 成有 tab 嘅 dark-theme HTML 網站，auto-deploy 去 GitHub Pages。

### 核心能力

| 功能 | 詳情 |
|------|------|
| **記 decisions** | BUY / SELL / TRIM / ADD / HOLD，連 reasoning, price, P&L |
| **記 snapshots** | Portfolio 快照（所有持倉 + 現金 + 盈虧），跟時間線對比 |
| **記 research** | 每 tick 嘅研究分析，記錄 sources, confidence, verdict |
| **Build 網站** | 3 個 tab：時間線（JS 月份/日期 filter）、持倉（日期選擇器）、研究 |
| **GitHub Pages** | `audit_log.py push` → auto commit + push，live 即更新 |
| **Audit trial** | 完整嘅決策 sequence，適合回溯點解某個 trade 發生 |

### 網站結構

```
docs/
├── index.html         ← 時間線（買賣記錄，月/日 JS filter）
├── holdings.html      ← 持倉（揀日期睇 snapshot）
├── studies.html       ← 研究
├── assets/style.css   ← Dark theme CSS
├── 2026-07-20/
│   ├── index.html     ← 該日時間線
│   ├── entry-300.html ← 每個 entry 嘅 detail page
│   ├── entry-301.html
│   └── ...
└── .nojekyll
```

**Live site:** https://nkyang10.github.io/hermes-stock-audit-log/

---

## Who — 邊啲 component 用緊佢

| Consumer | Cron Job | 用途 | Log Type |
|----------|----------|------|----------|
| **stock-trading-sim** | `165c8859d964` | 每 tick 做 trading decision 後 | `snapshot`（每次 decision batch 後自動 log） |
| **stock-trading-sim-research** | `584ed05cbc4e` | 每 tick 做研究後 | `study`（每 tick pick 1 stock 深度研究） |
| **stock-trading-sim-part2** | `5f83859edfbb` | 凌晨 trading session | `snapshot`（同 part1 一樣 pattern） |
| **stock-trading-sim-research-part2** | `b553e577ad13` | 凌晨研究 session | `study` |
| **手動決策** | — | 用戶手動 log 研究/分析 | `study` / `analysis` / `decision` |

### 心跳排程（HKT）

```
21:33 → research   (stock-trading-sim-research)
22:18 → trading    (stock-trading-sim)         ← log snapshot
23:33 → research
00:18 → trading                                ← log snapshot
01:33 → research
02:18 → trading                                ← log snapshot
```

Every trading tick auto-runs `audit_log.py log` + `build` + `push`。

---

## When — 幾時用 / 點解要用

### 自動觸發（cron job 內）

每個 sim-trader cron job 嘅最後一步：

```python
# 喺 cron prompt 入面（每次 trading decision batch 之後）：
subprocess.run([
    "python3", "~/hermes-exchange/hermes-stock-audit-log/audit_log.py",
    "commit", "--type", "snapshot",
    "--title", f"EOD Portfolio {date}",
    "--portfolio", "state/portfolio.json",
    "--pnl", f"+${realized_pnl}",
    "--source", "sim-trader"
])
```

或者 research job 完成後：

```
python3 audit_log.py commit --type study \
    --ticker NVDA \
    --title "NVDA Research — Jul 20 session" \
    --reasoning research/20260720_221800/NASDAQ_NVDA.json \
    --tags research,sim-trader \
    --source sim-trader
```

### 手動使用

```
# Log 一個 trade decision
python3 audit_log.py log --type decision --ticker NVDA \
    --title "TRIM NVDA — 10 @ $206.69" \
    --reasoning "NVDA recovered from dip..." \
    --price 206.69 --pnl "+$342" \
    --source manual

# Log 一個研究分析
python3 audit_log.py log --type study \
    --title "Semi Sector Rotation Analysis" \
    --reasoning analysis.md \
    --tags sector-rotation,memory

# Build + push（必要時）
python3 audit_log.py build
python3 audit_log.py push "Update after manual analysis"
```

### 幾個好重要嘅 timing 考慮

- **每次 trading tick 都要 log** — 唔可以漏，否則 audit trail 斷咗
- **Build + push 一定要跟 log 一齊行** — 唔係就冇人睇到個 entry
- **Reasoning file 要留低** — `--reasoning` 可以收 file path，auto read 成個 file（唔好 truncate）
- **研究 entries 要記 source tier + confidence** — 方便日後回溯

---

## How — 點樣用（詳細指令參考）

### 📝 log — 寫 entry

```
python3 audit_log.py log \
    --type <decision|snapshot|study|analysis> \
    --title "<action> <ticker> — <detail>" \
    --ticker <SYM> \
    --reasoning "<text or /path/to/file.md>" \
    --price <N.NN> \
    --pnl "<+$N,NNN>" \
    --portfolio <pf.json> \
    --tags <tag1,tag2> \
    --source <sim-trader|manual|...> \
    --datetime "YYYY-MM-DD HH:MM:SS"
```

**Argument 重點：**

| Arg | 點用 |
|-----|------|
| `--type` | `decision` = 買賣操作 · `snapshot` = 持倉快照 · `study` = 研究 · `analysis` = 分析 |
| `--title` | Title format 見下面 §Title Format |
| `--reasoning` | 可以直接傳 text，或者傳 **file path**（auto read 全個 file，唔 truncate） |
| `--portfolio` | **snapshot 專用** — 傳 portfolio JSON file path，系統會 parse 出 holdings table |
| `--tags` | comma-separated，用嚟分類（e.g. `semi,earnings,dip`） |
| `--source` | 邊個 script 生成嘅（方便 audit） |

### 🔨 build — 生成網站

```
python3 audit_log.py build
```

讀 audit.db → generate `docs/` 成個 static site（index, holdings, studies + 每個 entry 嘅 detail page + 每日 folder）。

### 🚀 push — 上 GitHub Pages

```
python3 audit_log.py push "Update message"
python3 audit_log.py push --force   # 跳過 ⚠ 檢查
```

會做：`git add docs/` → `git commit` → `git push origin main`  
安全機制：自動 detect ⚠ marker（真實 portfolio 數據），要有 `--force` 先推。

### ⚡ commit — 一鍵三連

```
python3 audit_log.py commit --type decision --ticker NVDA \
    --title "BUY NVDA — 10 @ $205" \
    --reasoning "Dip buy into support" \
    --price 205.00
```

等於 `log` + `build` + `push` 一次過。

---

## Title Format Convention（好重要）

每個 entry title 跟嚴格格式，方便人眼 scan 同 parsing：

| Type | Format | Example |
|------|--------|---------|
| **BUY** | `BUY <TKR> — <N> @ $<price> ($<total>)` | `BUY AAPL — 60 @ $298.01 ($17,882)` |
| **SELL** | `SELL <TKR> — <N> @ $<price> ($<total>) [prev buy: N @ $X]` | `SELL NVDA — 250 @ $206.45 ($51,612) [prev buy: 500 @ $205.19]` |
| **TRIM** | `TRIM <TKR> — <N> @ $<price> ($<total>) [prev avg: $X \| prev pos: N]` | `TRIM NVDA — 10 @ $206.69 ($2,067) [prev avg: $205.19 \| prev pos: 240]` |
| **ADD** | `ADD <TKR> — +<N> @ $<price> ($<total>) [prev avg: $X \| prev pos: N]` | `ADD META — +2 @ $669.00 ($1,338) [prev avg: $618.38 \| prev pos: 26]` |
| **HOLD** | `HOLD <TKR> — HOLD — <brief reason>` | `HOLD AAPL — HOLD — +0.14%, only green in portfolio` |
| **Snapshot** | `<date> Portfolio` | `2026-07-20 Portfolio Snapshot` |
| **Study** | `<TKR> Research — <context>` | `NVDA Research — Jul 20 session` |

### Tags 約定

| Tag | 用喺 |
|-----|------|
| `research` | Study entries from research cron |
| `sim-trader` | Auto-logged by sim-trader cron |
| `semi`, `ai`, `consumer` | Sector tags |
| `earnings`, `dip`, `recovery` | Event tags |
| `manual` | 手動 entry |

---

## Which — 邊個 component 做乜

### 1️⃣ `audit_log.py` — 核心 CLI（1242行）

```
├── main()                   ← argparse CLI entry
├── cmd_log()                ← 寫 entry 入 SQLite
├── cmd_build()              ← Generate static site
├── cmd_push()               ← Git commit + push
├── cmd_commit()             ← log + build + push one-shot
├── build_site()             ← 生成所有 HTML pages
│   ├── index.html           ← 時間線（JS month/day filter）
│   ├── holdings.html        ← 持倉（JS date selector）
│   ├── studies.html         ← 研究（JS date filter）
│   └── per-date/entry-N.html ← Detail pages
├── generate_detail()        ← 每個 entry 嘅 detail page
├── render_md()              ← Markdown → HTML（bold, code, bullet）
└── write_css()              ← 生成 style.css
```

### 2️⃣ SQLite DB (`audit.db`)

```
entries table:
  id          INTEGER PRIMARY KEY
  entry_type  TEXT (decision|snapshot|study|analysis)
  title       TEXT
  ticker      TEXT
  reasoning   TEXT (raw 或 file path auto-read)
  price       REAL
  pnl         TEXT (e.g. "+$1,234")
  portfolio   TEXT (JSON blob for snapshots)
  tags        TEXT (comma-separated)
  created_at  TEXT (HKT timestamp)
  source      TEXT (sim-trader, manual, etc.)
```

Indexes: `created_at DESC`, `entry_type`, `ticker`

### 3️⃣ Web Pages（`docs/`）

| Page | 功能 | JS? | 日期篩選 |
|------|------|-----|---------|
| `index.html` | 時間線（買賣記錄 + HOLD） | ✅ 月+日 button | 揀月份→顯示日子→filter |
| `holdings.html` | 持倉表 | ✅ date selector | 揀日期睇嗰日嘅 snapshot |
| `studies.html` | 研究列表 | ✅ date selector | 揀日期 filter |
| `entry-N.html` | Detail page | ❌ 純 static | 冇，但 auto link 返時間線 |
| `YYYY-MM-DD/index.html` | 該日時間線 | ✅ auto-filter to that date | 預設已 filter |

### 4️⃣ CSS (`docs/assets/style.css`)

GitHub-style dark theme（349行），支援 responsive mobile layout。

### 5️⃣ GitHub Pages

- **Repo:** `nkyang10/hermes-stock-audit-log`
- **Live:** https://nkyang10.github.io/hermes-stock-audit-log/
- **Branch:** `main`（serve `docs/` folder）
- **Push pattern:** 每個 cron tick auto `git add docs/ && git commit && git push`

---

## Architecture — 成個 flow

```
                    ┌─────────────────────┐
                    │   sim-trader cron    │
                    │  (every 2h HKT)      │
                    │  tradingview_prices  │
                    │      → prices/       │
                    │      → research/     │
                    │      → decisions/    │
                    │      → state/        │
                    └────────┬────────────┘
                             │
                  ┌──────────▼──────────┐
                  │   audit_log.py log  │
                  │   --type snapshot   │
                  │   --portfolio *.json│
                  └──────────┬──────────┘
                             │
                  ┌──────────▼──────────┐
                  │   audit_log.py build │
                  │   → SQLite → docs/  │
                  └──────────┬──────────┘
                             │
                  ┌──────────▼──────────┐
                  │   audit_log.py push  │
                  │   → git push →      │
                  │   GitHub Pages      │
                  └─────────────────────┘
                              │
                              ▼
              https://nkyang10.github.io/
              hermes-stock-audit-log/
```

---

## Pitfalls & Notes（累積知識）

### Reasoning File Auto-Read

`--reasoning` 收 file path 時會 auto read 成個 file。**永遠唔好 truncate reasoning** — 完整 reasoning 先有用。

### Portfolio JSON Format

Snapshot portfolio JSON expected structure:

```json
{
  "holdings": {
    "NASDAQ:NVDA": {
      "shares": 121,
      "avg_cost": 205.19,
      "current_price": 202.81,
      "market_value": 24540.01,
      "unrealized_pnl": -287.98,
      "concentration_pct": 23.42
    }
  },
  "cash": 3965.13,
  "total_value": 104800.73,
  "initial_cash": 100000.0
}
```

Field 名有多種兼容（`avg_cost`/`entry`、`current_price`/`current`、`unrealized_pnl`/`pnl` 等）。

### ⚠️ Safety Guard

`audit_log.py push` 會 scan `docs/` 有冇 `⚠` Unicode character。如果有，block 推上 GitHub — 因為 ⚠ 係真實 portfolio data marker（shares > 500 auto-flagged）。

### Build 只 log decision 類型

時間線頁只顯示 `entry_type = 'decision'` 嘅 entries（唔顯示 snapshot/study/analysis，呢啲喺各自 tab）。

### Date Folder Structure

每個 date 嘅 entry detail page 放喺 `docs/{YYYY-MM-DD}/entry-{id}.html`，同時 `docs/` root 都有 flat entry pages（backward compat）。

---

## 開發心得（畀未來開發者）

1. **Reasoning 一定要留完整** — 用 file path read 好過 inline text
2. **Snapshot portfolio 係 JSON** — 直接食 sim-trader 嘅 `state/portfolio.json`
3. **JS filter 係 client-side** — 所有 entries 一齊 load，JS 只 toggle `display`
4. **Title format 統一** — `action TKR — detail [prev tags]`
5. **每次 tick 都要 build + push** — 斷咗鏈就 auditable 唔到
6. **新 ticker color 要加落 `TKR_C` dict** — 先有 badge color
