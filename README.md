# 📊 Stock Audit Log

> **Sim-Trading Decision Journal** — every trade decision, portfolio snapshot, and study is logged as a readable HTML page, served via GitHub Pages.

[![GitHub Pages](https://img.shields.io/badge/View-Live-blue?style=flat-square)](https://nkyang10.github.io/hermes-stock-audit-log/)

## How It Works

Any script (premarket report, portfolio analysis, trading sim, manual decision) calls `audit_log.py` to log an entry, then builds a static HTML site and pushes to GitHub.

```
                     ┌──────────────┐
  Hermes script ────▶│ audit_log.py │───▶ SQLite (local)
                     │  log ...     │
                     └──────┬───────┘
                            │ build
                            ▼
                     ┌──────────────┐
                     │   docs/      │───▶ Beautiful HTML site
                     │  *.html      │     (index + detail pages)
                     └──────┬───────┘
                            │ push
                            ▼
                     ┌──────────────┐
                     │   GitHub     │───▶ https://nkyang10.github.io/
                     │   Pages      │     hermes-stock-audit-log/
                     └──────────────┘
```

## Quick Start

```bash
# Log a trade decision
python3 audit_log.py log --type decision --ticker NVDA \
    --title "HOLD NVDA — semi sector dip recovery" \
    --reasoning "NVDA recovered from -3% intraday lows..." \
    --price 212.50 --tags semi,recovery,morgan-stanley \
    --source sim-trader

# Log a portfolio snapshot (with JSON portfolio file)
python3 audit_log.py log --type snapshot \
    --title "EOD Portfolio 2026-07-16" \
    --portfolio portfolio.json --pnl "+$4,877"

# Log a study / analysis
python3 audit_log.py log --type study \
    --title "Semi Sector Rotation Analysis" \
    --reasoning study.md --tags sector-rotation,memory

# Build the HTML site
python3 audit_log.py build

# Push to GitHub
python3 audit_log.py push "Add EOD snapshot 2026-07-16"

# Or all-in-one
python3 audit_log.py commit --type decision --ticker AAPL \
    --title "BUY AAPL — pullback entry" \
    --reasoning "AAPL dipped to $326 support..." \
    --price 326.50 --pnl "+$0" --source sim-trader
```

## Entry Types

| Type | Meaning |
|------|---------|
| `decision` | A trade decision (BUY / SELL / HOLD) |
| `snapshot` | Portfolio snapshot (EOD, period-end) |
| `study` | Research / analysis study |
| `analysis` | Technical / fundamental analysis |

## Arguments

| Arg | Required | Description |
|-----|----------|-------------|
| `--type` | ✓ | `decision`, `snapshot`, `study`, or `analysis` |
| `--title` | ✓ | Short description of the entry |
| `--ticker` | - | Stock ticker (e.g. `NVDA`, `AAPL`) |
| `--reasoning` | - | Reasoning text or **path to a .md file** |
| `--price` | - | Price at time of decision |
| `--pnl` | - | P&L summary (e.g. `+$1,234`) |
| `--portfolio` | - | Path to JSON portfolio file |
| `--tags` | - | Comma-separated tags (e.g. `semi,earnings,dip`) |
| `--source` | - | Source script name (e.g. `sim-trader`, `premarket-report`) |

## HTML Site Features

- **Dark theme** — easy on the eyes, GitHub-style
- **Reverse-chronological timeline** — newest decisions first
- **Per-ticker colors** — each stock has its own badge colour
- **Markdown rendering** — `**bold**`, `*italic*`, `` `code` ``, ``` ```code``` ```, `- bullet` lists
- **Portfolio tables** — positions, P&L, concentration % at a glance
- **Responsive** — looks great on phone too
- **No JavaScript** — pure HTML + CSS, loads instantly

## Safety

This tool is designed for **sim-trading data only**. Real portfolio data must never be logged here. The script includes automatic detection of unusually large position sizes and will flag them with ⚠ markers during build.

## Directory Structure

```
hermes-stock-audit-log/
├── audit_log.py      # Main CLI tool (log / build / push / commit)
├── audit.db          # SQLite database (local only, gitignored)
├── docs/             # Generated HTML site (committed to GitHub)
│   ├── index.html
│   ├── entry-1.html
│   ├── entry-2.html
│   └── assets/
│       └── style.css
└── README.md
```

## Example: Cron Integration

Add to a sim-trading cron job to auto-log every decision batch:

```bash
# After sim-trader runs decisions, log them to audit trail
python3 ~/hermes-stock-audit-log/audit_log.py log \
    --type snapshot \
    --title "Post-decision portfolio" \
    --portfolio ~/.hermes/sim-trader/state/portfolio.json \
    --source sim-trader

python3 ~/hermes-stock-audit-log/audit_log.py build
python3 ~/hermes-stock-audit-log/audit_log.py push "Auto-update after sim decision"
```
