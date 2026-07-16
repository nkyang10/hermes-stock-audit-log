#!/usr/bin/env python3
"""
Stock Audit Log — record every trade decision, study, and portfolio snapshot
as readable HTML, served via GitHub Pages.

Usage:
  # Log a decision/study/snapshot
  python3 audit_log.py log --type decision --ticker NVDA \\
      --title "HOLD NVDA — semi sector dip recovery" \\
      --reasoning "NVDA recovered from -3% intraday lows..." \\
      --price 212.50 --tags semi,recovery,morgan-stanley

  # Log a portfolio snapshot
  python3 audit_log.py log --type snapshot --title "EOD 2026-07-16" \\
      --portfolio portfolio.json --pnl "+$4,877"

  # Log a study/analysis
  python3 audit_log.py log --type study --title "Semi sector rotation analysis" \\
      --reasoning study.md --tags sector-rotation,memory

  # Build HTML site
  python3 audit_log.py build

  # Push to GitHub
  python3 audit_log.py push "Add portfolio snapshot 2026-07-16"

  # One-shot: log + build + push
  python3 audit_log.py commit --type decision --ticker NVDA \\
      --title "..." --reasoning "..."

SAFETY: This tool is designed for SIM-TRADING data ONLY.
Real IBKR portfolio data must NEVER be logged here.
"""

import argparse, json, os, re, sqlite3, shutil, subprocess, sys, textwrap
from datetime import datetime, timezone, timedelta
from pathlib import Path
from html import escape

HERE = Path(__file__).parent.resolve()
DB = HERE / "audit.db"
DOCS = HERE / "docs"
ASSETS = DOCS / "assets"

TZ_HK = timezone(timedelta(hours=8))

# ── schema ──────────────────────────────────────────────

SCHEMA = """
CREATE TABLE IF NOT EXISTS entries (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_type  TEXT NOT NULL CHECK(entry_type IN ('decision','snapshot','study','analysis')),
    title       TEXT NOT NULL,
    ticker      TEXT DEFAULT '',
    reasoning   TEXT DEFAULT '',
    price       REAL,
    pnl         TEXT DEFAULT '',
    portfolio   TEXT DEFAULT '{}',
    tags        TEXT DEFAULT '',
    created_at  TEXT NOT NULL DEFAULT (datetime('now','+8 hours')),
    source      TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_created ON entries(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_type ON entries(entry_type);
CREATE INDEX IF NOT EXISTS idx_ticker ON entries(ticker);
"""

def get_db():
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn

# ── log ─────────────────────────────────────────────────

def cmd_log(args):
    if args.portfolio and args.portfolio != '{}':
        try:
            with open(args.portfolio) as f:
                portfolio_data = json.load(f)
            # SAFETY: detect real portfolio by large values
            portfolio_raw = json.dumps(portfolio_data, indent=2)
        except Exception as e:
            print(f"⚠ Cannot read portfolio file: {e}")
            portfolio_raw = '{}'
    else:
        portfolio_raw = args.portfolio

    reasoning = args.reasoning
    if reasoning and reasoning.strip():
        # Check if reasoning is a file path or inline text
        # Use existence check that won't fail on long strings
        try:
            maybe_path = reasoning.strip()
            if len(maybe_path) < 512:
                p = Path(maybe_path)
                if p.exists():
                    reasoning = p.read_text().strip()
        except (OSError, ValueError):
            pass  # too long for a path, treat as inline text

    conn = get_db()
    conn.execute(
        """INSERT INTO entries (entry_type, title, ticker, reasoning, price, pnl, portfolio, tags, source)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (args.type, args.title, args.ticker or '',
         reasoning, args.price, args.pnl or '',
         portfolio_raw, args.tags or '', args.source or '')
    )
    conn.commit()
    entry_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    print(f"✓ Logged entry #{entry_id}: {args.type} — {args.title}")
    return entry_id

# ── build ───────────────────────────────────────────────

def render_markdown(text):
    """Very basic markdown→HTML for reasoning fields."""
    if not text:
        return ""
    text = escape(text)
    # code blocks
    text = re.sub(r'```(\w*)\n(.*?)```', r'<pre><code>\2</code></pre>', text, flags=re.DOTALL)
    # inline code
    text = re.sub(r'`([^`]+)`', r'<code>\1</code>', text)
    # bold
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    # italic
    text = re.sub(r'\*(.+?)\*', r'<em>\1</em>', text)
    # bullet lines
    lines = []
    for line in text.split('\n'):
        if line.strip().startswith('- ') or line.strip().startswith('* '):
            lines.append(f'<li>{line.strip()[2:]}</li>')
        elif line.strip().startswith('  - ') or line.strip().startswith('  * '):
            lines.append(f'<li class="sub">{line.strip()[3:]}</li>')
        elif re.match(r'^\d+\.\s', line.strip()):
            lines.append(f'<li class="num">{line.strip()}</li>')
        elif line.strip() == '':
            lines.append('<br>')
        else:
            lines.append(f'<p>{line}</p>')
    return '\n'.join(lines)

def fmt_num(n):
    """Format number with commas."""
    if n is None: return '—'
    return f'{n:,.2f}'

def fmt_dt(iso_str):
    try:
        dt = datetime.fromisoformat(iso_str)
        return dt.strftime('%Y-%m-%d %H:%M HKT')
    except:
        return iso_str

TICKER_COLORS = {
    'NVDA': '#76b900', 'AAPL': '#555555', 'MSFT': '#00a4ef',
    'META': '#0668e1', 'GOOGL': '#4285f4', 'AMZN': '#ff9900',
    'AMD': '#ed1c24', 'INTC': '#0071c5', 'TSLA': '#e82127',
    'IBKR': '#ff6600', 'SNDK': '#ea1d2c', 'WDC': '#0077b6',
    'STX': '#5dade2', 'AMKR': '#d4af37',
}

def generate_index(entries):
    """Generate index.html — reverse chronological timeline."""
    count = len(entries)
    now = datetime.now(TZ_HK).strftime('%Y-%m-%d %H:%M')
    # summary stats
    decisions = sum(1 for e in entries if e['entry_type'] == 'decision')
    snapshots = sum(1 for e in entries if e['entry_type'] == 'snapshot')
    studies = sum(1 for e in entries if e['entry_type'] == 'study')
    tickers = sorted(set(e['ticker'] for e in entries if e['ticker']))

    rows = []
    for e in entries:
        tag_html = ''
        if e['tags']:
            for t in e['tags'].split(','):
                t = t.strip()
                tag_html += f'<span class="tag">{escape(t)}</span>'
        type_badge = f'<span class="type-badge type-{e["entry_type"]}">{e["entry_type"]}</span>'
        ticker_badge = ''
        if e['ticker']:
            tc = TICKER_COLORS.get(e['ticker'].upper(), '#666')
            ticker_badge = f'<span class="tkr" style="--tkr-c:{tc}">{escape(e["ticker"])}</span>'
        pnl_badge = ''
        if e['pnl']:
            cls = 'pnl-pos' if e['pnl'].startswith('+') else 'pnl-neg' if e['pnl'].startswith('-') else ''
            pnl_badge = f'<span class="pnl {cls}">{escape(e["pnl"])}</span>'

        rows.append(f'''\
    <a href="entry-{e['id']}.html" class="entry-card">
      <div class="entry-meta">
        <span class="entry-time">{fmt_dt(e['created_at'])}</span>
        <div class="entry-badges">{type_badge}{ticker_badge}{pnl_badge}</div>
      </div>
      <div class="entry-title">{escape(e['title'])}</div>
      <div class="entry-tags">{tag_html}</div>
    </a>''')

    cards = '\n'.join(rows)
    ticker_list = ', '.join(f'<span class="tkr-mini" style="--tkr-c:{TICKER_COLORS.get(t,"#666")}">{t}</span>' for t in tickers)

    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Stock Audit Log</title>
<link rel="stylesheet" href="assets/style.css">
</head>
<body>
<header>
  <div class="hd-inner">
    <h1>📊 Stock Audit Log</h1>
    <div class="hd-sub">Sim-Trading Decision Journal · {count} entries</div>
    <div class="hd-stats">
      <span class="stat">{decisions} decisions</span>
      <span class="stat">{snapshots} snapshots</span>
      <span class="stat">{studies} studies</span>
      <span class="stat">{len(tickers)} tickers</span>
    </div>
    {f'<div class="hd-tickers">{ticker_list}</div>' if ticker_list else ''}
    <div class="hd-last">Updated {now}</div>
  </div>
</header>
<main>
  {cards}
</main>
<footer>
  <p>Generated by audit_log.py · <a href="https://github.com/nkyang10/hermes-stock-audit-log">View on GitHub</a></p>
</footer>
</body>
</html>'''
    (DOCS / 'index.html').write_text(html)
    return len(rows)

def generate_detail(e):
    """Generate entry-NNNNN.html for a single entry."""
    portfolio_html = ''
    pf = json.loads(e['portfolio']) if isinstance(e['portfolio'], str) else e.get('portfolio', {})
    if pf and pf != '{}':
        rows = []
        total = 0
        for sym, pos in pf.items():
            mv = pos.get('market_value', pos.get('mv_usd', 0))
            total += mv
            sym_clean = sym.replace('NASDAQ:', '')
            tc = TICKER_COLORS.get(sym_clean, '#666')
            chg = pos.get('chg_pct', pos.get('change_pct', ''))
            chg_cls = ''
            if isinstance(chg, (int, float)) and chg != 0:
                chg_cls = 'pnl-pos' if chg > 0 else 'pnl-neg'
            pnl = pos.get('pnl', pos.get('unrealized_pnl', ''))
            pnl_cls = ''
            if isinstance(pnl, (int, float)):
                pnl_cls = 'pnl-pos' if pnl > 0 else 'pnl-neg'
            # SAFETY: if any stock position is > 500 shares, flag as possible real data
            shares = pos.get('shares', 0)
            if isinstance(shares, (int, float)) and shares > 500:
                sym_clean += ' ⚠'
            rows.append(f'''\
          <tr>
            <td><span class="tkr-mini" style="--tkr-c:{tc}">{escape(sym_clean)}</span></td>
            <td class="r">{pos.get("shares", "—")}</td>
            <td class="r">${fmt_num(pos.get("avg_cost", pos.get("entry", 0)))}</td>
            <td class="r">${fmt_num(pos.get("current_price", pos.get("current", 0)))}</td>
            <td class="r {chg_cls}">{chg}%</td>
            <td class="r {pnl_cls}">${fmt_num(pnl)}</td>
            <td class="r">${fmt_num(mv)}</td>
            <td class="r">{pos.get("wt", pos.get("concentration_pct", ""))}%</td>
          </tr>''')
        portfolio_html = f'''\
      <div class="pf-section">
        <h3>Portfolio</h3>
        <div class="pf-total">Total: <strong>${fmt_num(total)}</strong></div>
        <table class="pf-table">
          <thead><tr><th>Ticker</th><th>Shares</th><th>Avg Cost</th><th>Price</th><th>Chg%</th><th>P&L</th><th>Value</th><th>Wt%</th></tr></thead>
          <tbody>{''.join(rows)}</tbody>
        </table>
      </div>'''

    ticker_badge = ''
    if e['ticker']:
        tc = TICKER_COLORS.get(e['ticker'].upper(), '#666')
        ticker_badge = f'<span class="tkr" style="--tkr-c:{tc}">{escape(e["ticker"])}</span>'
    tag_html = ''
    if e['tags']:
        for t in e['tags'].split(','):
            t = t.strip()
            tag_html += f'<span class="tag">{escape(t)}</span>'
    pnl_badge = ''
    if e['pnl']:
        cls = 'pnl-pos' if e['pnl'].startswith('+') else 'pnl-neg' if e['pnl'].startswith('-') else ''
        pnl_badge = f'<span class="big-pnl {cls}">{escape(e["pnl"])}</span>'

    reasoning_html = render_markdown(e['reasoning'])

    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>#{e['id']} — {escape(e['title'])} | Stock Audit Log</title>
<link rel="stylesheet" href="assets/style.css">
</head>
<body>
<header class="detail-hd">
  <div class="hd-inner">
    <a href="index.html" class="back-link">← Back to timeline</a>
    <div class="detail-meta">
      <div class="detail-time">{fmt_dt(e['created_at'])}</div>
      <div class="entry-badges">
        <span class="type-badge type-{e['entry_type']}">{e['entry_type']}</span>
        {ticker_badge}
        {pnl_badge}
      </div>
    </div>
    <h1>{escape(e['title'])}</h1>
    <div class="entry-tags">{tag_html}</div>
  </div>
</header>
<main>
  <div class="reasoning">
    {reasoning_html}
  </div>
  {portfolio_html}
</main>
<footer>
  <p><a href="index.html">← Back to timeline</a> · Entry #{e['id']} · Generated by audit_log.py</p>
</footer>
</body>
</html>'''
    (DOCS / f"entry-{e['id']}.html").write_text(html)

def cmd_build(args):
    DOCS.mkdir(parents=True, exist_ok=True)
    ASSETS.mkdir(parents=True, exist_ok=True)
    (DOCS / '.nojekyll').write_text('')  # GitHub Pages: serve _underscore files

    # write CSS
    write_css()

    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM entries ORDER BY created_at DESC"
    ).fetchall()
    conn.close()

    entries = [dict(r) for r in rows]
    n = generate_index(entries)
    for e in entries:
        generate_detail(e)

    print(f"✓ Built {n} entries → {DOCS}/")
    print(f"  index.html + {n} detail pages")

def write_css():
    css = '''/* ── Stock Audit Log Theme ─────────────────────── */
:root {
  --bg: #0d1117;
  --bg-card: #161b22;
  --bg-hover: #1c2333;
  --border: #30363d;
  --text: #e6edf3;
  --text-muted: #8b949e;
  --accent: #58a6ff;
  --green: #3fb950;
  --red: #f85149;
  --yellow: #d29922;
  --purple: #bc8cff;
}
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  background: var(--bg);
  color: var(--text);
  line-height: 1.6;
  padding: 0;
}
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }

/* header */
header {
  border-bottom: 1px solid var(--border);
  background: linear-gradient(180deg, #161b22 0%, #0d1117 100%);
  padding: 32px 20px 24px;
}
.hd-inner { max-width: 800px; margin: 0 auto; }
header h1 { font-size: 1.8em; margin-bottom: 4px; }
.hd-sub { color: var(--text-muted); font-size: 0.9em; margin-bottom: 6px; }
.hd-stats { display: flex; gap: 16px; flex-wrap: wrap; margin: 8px 0; }
.stat { background: var(--bg-card); padding: 2px 10px; border-radius: 12px; font-size: 0.85em; border: 1px solid var(--border); }
.hd-tickers { margin: 6px 0; display: flex; gap: 4px; flex-wrap: wrap; }
.hd-last { color: var(--text-muted); font-size: 0.8em; margin-top: 4px; }

/* entry cards */
main { max-width: 800px; margin: 0 auto; padding: 20px; }
.entry-card {
  display: block;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 16px 20px;
  margin-bottom: 10px;
  transition: background 0.15s, border-color 0.15s;
  color: var(--text);
}
.entry-card:hover {
  background: var(--bg-hover);
  border-color: var(--accent);
  text-decoration: none;
}
.entry-meta {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 6px;
  flex-wrap: wrap;
  gap: 4px;
}
.entry-time { color: var(--text-muted); font-size: 0.8em; }
.entry-badges { display: flex; gap: 4px; align-items: center; flex-wrap: wrap; }
.entry-title { font-size: 1.05em; font-weight: 600; margin-bottom: 4px; }
.entry-tags { display: flex; gap: 4px; flex-wrap: wrap; }

/* badges */
.type-badge {
  display: inline-block;
  padding: 1px 8px;
  border-radius: 10px;
  font-size: 0.72em;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
.type-decision { background: #1a3a2a; color: var(--green); border: 1px solid #2d6a3f; }
.type-snapshot { background: #1a2a3a; color: var(--accent); border: 1px solid #1f5399; }
.type-study    { background: #2a1a3a; color: var(--purple); border: 1px solid #4a2066; }
.type-analysis { background: #3a2a1a; color: var(--yellow); border: 1px solid #5a3a1a; }

.tkr {
  display: inline-block;
  padding: 1px 8px;
  border-radius: 10px;
  font-size: 0.8em;
  font-weight: 700;
  background: color-mix(in srgb, var(--tkr-c) 15%, transparent);
  color: var(--tkr-c);
  border: 1px solid color-mix(in srgb, var(--tkr-c) 40%, transparent);
}
.tkr-mini {
  display: inline-block;
  font-weight: 700;
  color: var(--tkr-c);
}
.pnl { font-size: 0.82em; font-weight: 600; padding: 1px 6px; border-radius: 6px; }
.pnl-pos { color: var(--green); }
.pnl-neg { color: var(--red); }

.tag {
  display: inline-block;
  padding: 1px 7px;
  border-radius: 8px;
  font-size: 0.72em;
  font-weight: 500;
  background: var(--bg);
  border: 1px solid var(--border);
  color: var(--text-muted);
}

/* detail page */
.detail-hd { padding-bottom: 20px; }
.detail-hd h1 { font-size: 1.5em; margin-top: 8px; }
.detail-meta { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 6px; }
.detail-time { color: var(--text-muted); font-size: 0.85em; }
.back-link { display: inline-block; margin-bottom: 8px; font-size: 0.9em; }
.big-pnl { font-size: 1.1em; font-weight: 700; }

.reasoning {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 20px;
  margin-bottom: 20px;
}
.reasoning p { margin-bottom: 10px; }
.reasoning li { margin-bottom: 4px; margin-left: 20px; }
.reasoning li.sub { list-style-type: circle; margin-left: 36px; color: var(--text-muted); }
.reasoning li.num { list-style-type: decimal; margin-left: 20px; }
.reasoning pre {
  background: #0d1117;
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 12px;
  overflow-x: auto;
  font-size: 0.85em;
  margin: 10px 0;
}
.reasoning code {
  background: #0d1117;
  padding: 1px 5px;
  border-radius: 4px;
  font-size: 0.85em;
}
.reasoning br { display: none; }
.reasoning strong { color: #f0f6fc; }

/* portfolio table */
.pf-section {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 20px;
  margin-bottom: 20px;
}
.pf-section h3 { margin-bottom: 8px; font-size: 1em; }
.pf-total { text-align: right; margin-bottom: 10px; font-size: 1em; color: var(--text-muted); }
.pf-table { width: 100%; border-collapse: collapse; font-size: 0.85em; }
.pf-table th { text-align: left; padding: 6px 8px; border-bottom: 1px solid var(--border); color: var(--text-muted); font-weight: 500; }
.pf-table td { padding: 6px 8px; border-bottom: 1px solid var(--border); }
.pf-table th.r, td.r { text-align: right; }
.pf-table tr:last-child td { border-bottom: none; }

/* footer */
footer {
  max-width: 800px;
  margin: 0 auto;
  padding: 20px;
  text-align: center;
  color: var(--text-muted);
  font-size: 0.8em;
  border-top: 1px solid var(--border);
}
footer a { color: var(--text-muted); }

/* responsive */
@media (max-width: 600px) {
  header { padding: 20px 12px 16px; }
  main { padding: 12px; }
  .entry-card { padding: 12px 14px; }
  .pf-table { font-size: 0.75em; }
  .pf-table th, .pf-table td { padding: 4px 6px; }
}
'''
    (ASSETS / 'style.css').write_text(css)

# ── push ────────────────────────────────────────────────

def cmd_push(args):
    msg = args.message or f"Audit log update {datetime.now(TZ_HK).strftime('%Y-%m-%d %H:%M')}"
    # Safety check: never push real portfolio data
    for f in DOCS.rglob('*.html'):
        content = f.read_text()
        if '⚠' in content:
            print(f"⚠ WARNING: {f.name} contains ⚠ markers (possible real portfolio data)")
            if not args.force:
                print("  Use --force to push anyway, or review the data first.")
                return

    subprocess.run(['git', '-C', str(HERE), 'add', 'docs/'], check=True)
    result = subprocess.run(
        ['git', '-C', str(HERE), 'diff', '--cached', '--quiet'],
        capture_output=True
    )
    if result.returncode == 0:
        print("✓ Nothing new to push")
        return
    subprocess.run(['git', '-C', str(HERE), 'commit', '-m', msg], check=True)
    subprocess.run(['git', '-C', str(HERE), 'push', 'origin', 'main'], check=True)
    print(f"✓ Pushed to GitHub: {msg}")

# ── commit (one-shot) ──────────────────────────────────

def cmd_commit(args):
    eid = cmd_log(args)
    cmd_build(args)
    cmd_push(args)
    print(f"\n✓ Entry #{eid} committed and pushed")

# ── main ────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description='Stock Audit Log — record & publish trade decisions')
    sub = p.add_subparsers(dest='cmd')

    # log
    plog = sub.add_parser('log', help='Log a new entry')
    plog.add_argument('--type', '-t', required=True, choices=['decision','snapshot','study','analysis'])
    plog.add_argument('--title', required=True)
    plog.add_argument('--ticker', default='')
    plog.add_argument('--reasoning', default='')
    plog.add_argument('--price', type=float, default=None)
    plog.add_argument('--pnl', default='')
    plog.add_argument('--portfolio', default='{}')
    plog.add_argument('--tags', default='')
    plog.add_argument('--source', default='')

    # build
    pbuild = sub.add_parser('build', help='Generate HTML site from database')

    # push
    ppush = sub.add_parser('push', help='Commit docs/ and push to GitHub')
    ppush.add_argument('message', nargs='?', default='')
    ppush.add_argument('--force', action='store_true', help='Push even if ⚠ markers detected')

    # commit (one-shot)
    pcommit = sub.add_parser('commit', help='Log + build + push in one step')
    pcommit.add_argument('--type', '-t', required=True, choices=['decision','snapshot','study','analysis'])
    pcommit.add_argument('--title', required=True)
    pcommit.add_argument('--ticker', default='')
    pcommit.add_argument('--reasoning', default='')
    pcommit.add_argument('--price', type=float, default=None)
    pcommit.add_argument('--pnl', default='')
    pcommit.add_argument('--portfolio', default='{}')
    pcommit.add_argument('--tags', default='')
    pcommit.add_argument('--source', default='')
    pcommit.add_argument('--force', action='store_true', help='Push even if ⚠ markers detected')

    args = p.parse_args()
    if args.cmd == 'log':
        cmd_log(args)
    elif args.cmd == 'build':
        cmd_build(args)
    elif args.cmd == 'push':
        cmd_push(args)
    elif args.cmd == 'commit':
        cmd_commit(args)
    else:
        p.print_help()

if __name__ == '__main__':
    main()
