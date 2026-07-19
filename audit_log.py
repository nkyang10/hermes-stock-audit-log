#!/usr/bin/env python3
"""
Stock Audit Log — record every trade decision, study, and portfolio snapshot
as readable HTML, served via GitHub Pages.

Usage:
  python3 audit_log.py log --type decision --ticker NVDA --title "..." --reasoning "..."
  python3 audit_log.py build
  python3 audit_log.py push "message"
  python3 audit_log.py commit --type snapshot --title "EOD" --portfolio pf.json
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

# ── log ──

def cmd_log(args):
    portfolio_raw = args.portfolio
    if args.portfolio and args.portfolio != '{}':
        try:
            with open(args.portfolio) as f:
                json.load(f)  # validate
            portfolio_raw = args.portfolio
        except Exception as e:
            print(f"⚠ Cannot read portfolio file: {e}")
            portfolio_raw = '{}'

    reasoning = args.reasoning
    if reasoning and reasoning.strip():
        try:
            maybe_path = reasoning.strip()
            if len(maybe_path) < 512:
                p = Path(maybe_path)
                if p.exists():
                    reasoning = p.read_text().strip()
        except (OSError, ValueError):
            pass

    # If portfolio is a file path, read it
    if portfolio_raw and portfolio_raw != '{}':
        try:
            p = Path(portfolio_raw)
            if p.exists():
                portfolio_raw = p.read_text()
        except:
            pass

    conn = get_db()
    conn.execute(
        """INSERT INTO entries (entry_type, title, ticker, reasoning, price, pnl, portfolio, tags, source, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (args.type, args.title, args.ticker or '',
         reasoning, args.price, args.pnl or '',
         portfolio_raw, args.tags or '', args.source or '',
         args.datetime or datetime.now(TZ_HK).strftime('%Y-%m-%d %H:%M:%S'))
    )
    conn.commit()
    entry_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    print(f"✓ Logged entry #{entry_id}: {args.type} — {args.title}")
    return entry_id

# ── rendering helpers ──

def render_md(text):
    if not text:
        return ""
    text = escape(text)
    text = re.sub(r'```(\w*)\n(.*?)```', r'<pre><code>\2</code></pre>', text, flags=re.DOTALL)
    text = re.sub(r'`([^`]+)`', r'<code>\1</code>', text)
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    text = re.sub(r'\*(.+?)\*', r'<em>\1</em>', text)
    lines = []
    for line in text.split('\n'):
        s = line.strip()
        if s.startswith('- ') or s.startswith('* '):
            lines.append(f'<li>{s[2:]}</li>')
        elif s.startswith('  - ') or s.startswith('  * '):
            lines.append(f'<li class="sub">{s[3:]}</li>')
        elif re.match(r'^\d+\.\s', s):
            lines.append(f'<li class="num">{s}</li>')
        elif s == '':
            lines.append('<br>')
        else:
            lines.append(f'<p>{line}</p>')
    return '\n'.join(lines)

def fmt_num(n):
    if n is None: return '—'
    return f'{n:,.2f}'

def fmt_dt(iso_str):
    try:
        dt = datetime.fromisoformat(iso_str)
        return dt.strftime('%Y-%m-%d %H:%M HKT')
    except:
        return iso_str

TKR_C = {
    'NVDA': '#76b900', 'AAPL': '#555555', 'MSFT': '#00a4ef',
    'META': '#0668e1', 'GOOGL': '#4285f4', 'AMZN': '#ff9900',
    'AMD': '#ed1c24', 'INTC': '#0071c5', 'TSLA': '#e82127',
    'IBKR': '#ff6600', 'SNDK': '#ea1d2c', 'WDC': '#0077b6',
    'STX': '#5dade2', 'AMKR': '#d4af37',
}

def tkr_html(t):
    c = TKR_C.get(t.upper(), '#666')
    return f'<span class="tkr-mini" style="--tkr-c:{c}">{escape(t)}</span>'

def tkr_badge(t):
    c = TKR_C.get(t.upper(), '#666')
    return f'<span class="tkr" style="--tkr-c:{c}">{escape(t)}</span>'

def tag_html(tags):
    if not tags: return ''
    return ''.join(f'<span class="tag">{escape(t.strip())}</span>' for t in tags.split(','))

def pnl_badge(pnl):
    if not pnl: return ''
    cls = 'pnl-pos' if pnl.startswith('+') else 'pnl-neg' if pnl.startswith('-') else ''
    return f'<span class="pnl {cls}">{escape(pnl)}</span>'

TYPE_LABELS = {'decision': '決策', 'snapshot': '快照', 'study': '研究', 'analysis': '分析'}

def type_badge(t):
    label = TYPE_LABELS.get(t, t)
    return f'<span class="type-badge type-{t}">{label}</span>'

# ── header / footer / nav / date switcher templates ──

def date_switcher_html(all_dates, curr_date, prefix=''):
    """Generate date switcher dropdown. curr_date=None means '全部'."""
    html = '<div class="date-switcher"><label>📅 日期：</label><div class="date-list">'
    sel = 'active' if curr_date is None else ''
    html += f'<a href="{prefix}index.html" class="date-btn {sel}">全部</a>'
    for d in all_dates:
        sel = 'active' if d == curr_date else ''
        html += f'<a href="{prefix}{d}/index.html" class="date-btn {sel}">{d}</a>'
    html += '</div></div>'
    return html

def page_head_html(title, header_kw, prefix='', sel_all='', sel_hld='', sel_stu='', curr_date=None, all_dates=None, hide_date_switcher=False):
    """Generate full page header with tabs and date switcher."""
    ds = '' if hide_date_switcher else (date_switcher_html(all_dates or [], curr_date, prefix) if all_dates else '')
    kw = dict(header_kw, title=title, prefix=prefix,
              sel_all=sel_all, sel_hld=sel_hld, sel_stu=sel_stu,
              date_switcher=ds)
    return PAGE_HEAD.format(**kw)

PAGE_HEAD = '''<!DOCTYPE html>
<html lang="zh-HK">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<link rel="stylesheet" href="{prefix}assets/style.css">
</head>
<body>
<header>
  <div class="hd-inner">
    <h1>📊 股票審計記錄</h1>
    <div class="hd-sub">模擬交易決策日誌 · 共 {count} 條記錄</div>
    <div class="hd-stats">
      <span class="stat">{decisions} 項決策</span>
      <span class="stat">{snapshots} 項快照</span>
      <span class="stat">{studies} 項研究</span>
      <span class="stat">{tickers_n} 隻股票</span>
    </div>
    {ticker_row}
    <div class="hd-last">更新於 {now}</div>
  </div>
  {date_switcher}
  <nav class="tabs">
    <a href="{prefix}index.html" class="tab {sel_all}">📋 時間線</a>
    <a href="{prefix}holdings.html" class="tab {sel_hld}">💼 持倉</a>
    <a href="{prefix}studies.html" class="tab {sel_stu}">📚 研究</a>
  </nav>
</header>
<main>
'''

PAGE_FOOT = '''</main>
<footer>
  <p>由 audit_log.py 自動生成 · <a href="https://github.com/nkyang10/hermes-stock-audit-log">GitHub 原始碼</a></p>
</footer>
</body>
</html>'''

# ── extract latest portfolio snapshot ──

def get_latest_holdings(entries):
    """Return dict of {ticker: pos} from the most recent snapshot with data, or empty dict."""
    for e in entries:
        if e['entry_type'] != 'snapshot':
            continue
        pf = e.get('portfolio', '{}')
        if isinstance(pf, str) and pf.strip():
            try:
                data = json.loads(pf)
            except:
                continue
        elif isinstance(pf, dict):
            data = pf
        else:
            continue
        holdings = data.get('holdings', data)
        if isinstance(holdings, dict):
            clean = {}
            for k, v in holdings.items():
                sym = k.replace('NASDAQ:', '').replace('NYSE:', '')
                clean[sym] = v
            if clean:
                return clean
        return {}
    return {}

# ── generate pages ──

def make_cards(entries, prefix='', curr_date=None):
    cards = []
    for e in entries:
        dt = e['created_at'][:10] if e['created_at'] else ''
        if curr_date and dt == curr_date:
            entry_path = f'{prefix}entry-{e["id"]}.html'
        elif dt:
            entry_path = f'{prefix}{dt}/entry-{e["id"]}.html'
        else:
            entry_path = f'entry-{e["id"]}.html'
        cards.append(f'''\
    <a href="{entry_path}" class="entry-card" data-date="{dt}">
      <div class="entry-meta">
        <span class="entry-time">{fmt_dt(e['created_at'])}</span>
        <div class="entry-badges">{type_badge(e['entry_type'])}{tkr_badge(e['ticker']) if e['ticker'] else ''}{pnl_badge(e['pnl'])}</div>
      </div>
      <div class="entry-title">{escape(e['title'])}</div>
      <div class="entry-tags">{tag_html(e['tags'])}</div>
    </a>''')
    return '\n'.join(cards)

# ── holdings table renderer ──

def render_holdings_table(holdings, cash=0, total_value=0):
    """Render a full holdings table + summary cards. Returns HTML string."""
    if not holdings:
        return '<p class="empty">未有持倉數據</p>'
    rows = []
    total_mv = 0
    grand_cost = 0
    for sym, pos in sorted(holdings.items()):
        shares = pos.get('shares', 0)
        cost = pos.get('avg_cost', pos.get('entry', 0))
        price = pos.get('current_price', pos.get('current', 0))
        chg = pos.get('chg_pct', pos.get('change_pct', ''))
        pnl = pos.get('pnl', pos.get('unrealized_pnl', 0))
        mv = pos.get('market_value', pos.get('mv_usd', 0))
        wt = pos.get('wt', pos.get('concentration_pct', ''))
        total_mv += mv
        grand_cost += shares * cost
        chg_cls = ''
        if isinstance(chg, (int, float)):
            chg_cls = 'pnl-pos' if chg >= 0 else 'pnl-neg'
        pnl_cls = ''
        if isinstance(pnl, (int, float)):
            pnl_cls = 'pnl-pos' if pnl >= 0 else 'pnl-neg'
        rows.append(f'''\
          <tr>
            <td>{tkr_badge(sym)}</td>
            <td class="r">{shares}</td>
            <td class="r">${fmt_num(cost)}</td>
            <td class="r">${fmt_num(price)}</td>
            <td class="r {chg_cls}">{chg}%</td>
            <td class="r {pnl_cls}">${fmt_num(pnl)}</td>
            <td class="r">${fmt_num(mv)}</td>
            <td class="r">{wt}%</td>
          </tr>''')
    total_pnl = total_mv - grand_cost
    pnl_cls = 'pnl-pos' if total_pnl >= 0 else 'pnl-neg'
    return f'''\
    <div class="holdings-summary">
      <div class="hsum-row">
        <span class="hsum-label">總值</span>
        <span class="hsum-val">${fmt_num(total_mv)}</span>
      </div>
      <div class="hsum-row {pnl_cls}">
        <span class="hsum-label">總盈虧</span>
        <span class="hsum-val">{'+' if total_pnl >= 0 else ''}${fmt_num(total_pnl)}</span>
      </div>
      <div class="hsum-row">
        <span class="hsum-label">持倉數目</span>
        <span class="hsum-val">{len(holdings)}</span>
      </div>
    </div>
    <div class="pf-section">
      <table class="pf-table">
        <thead><tr><th>股票</th><th>股數</th><th>平均成本</th><th>現價</th><th>變幅</th><th>盈虧</th><th>市值</th><th>佔比</th></tr></thead>
        <tbody>{''.join(rows)}</tbody>
      </table>
    </div>'''

def gen_snapshot_holdings_page(snap_data, header_kw, all_dates=None, curr_date=None):
    """Generate a standalone holdings page for one specific snapshot."""
    sid = snap_data['id']
    dt_label = curr_date or fmt_dt(snap_data.get('created_at', '')).replace(' HKT', '')
    prefix = '../' if curr_date else ''
    kw = dict(header_kw, sel_all='', sel_hld='active', sel_dec='', sel_stu='')
    kw['title'] = f'💼 持倉 · {dt_label}'

    # Use the new page_head_html with date switcher
    ds = date_switcher_html(all_dates or [], curr_date, prefix)
    kw2 = dict(header_kw, title=kw['title'], prefix=prefix,
               sel_all='', sel_hld='active', sel_dec='', sel_stu='',
               date_switcher=ds)
    page_head = PAGE_HEAD.format(**kw2)

    hld_html = render_holdings_table(snap_data['holdings'], snap_data.get('cash', 0), snap_data.get('total_value', 0))
    html = page_head + f'<h2 class="section-title">💼 持倉 · {dt_label}</h2>\n' + hld_html + PAGE_FOOT
    out_dir = DOCS / curr_date if curr_date else DOCS
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f'holdings.html'
    out_path.write_text(html)

def build_site(entries):
    DOCS.mkdir(parents=True, exist_ok=True)
    ASSETS.mkdir(parents=True, exist_ok=True)
    (DOCS / '.nojekyll').write_text('')

    now = datetime.now(TZ_HK).strftime('%Y-%m-%d %H:%M')
    count = len(entries)
    n_dec = sum(1 for e in entries if e['entry_type'] == 'decision')
    n_snp = sum(1 for e in entries if e['entry_type'] == 'snapshot')
    n_stu = sum(1 for e in entries if e['entry_type'] in ('study','analysis'))
    tickers = sorted(set(e['ticker'] for e in entries if e['ticker']))
    tkr_row = '<div class="hd-tickers">' + ', '.join(tkr_html(t) for t in tickers) + '</div>' if tickers else ''

    header_kw = dict(title='📊 股票審計記錄', count=count,
                     decisions=n_dec, snapshots=n_snp, studies=n_stu,
                     tickers_n=len(tickers), ticker_row=tkr_row, now=now)

    # Collect unique dates
    all_dates = sorted(set(e['created_at'][:10] for e in entries if e['created_at']), reverse=True)

    def write_page(path, title, content, sel_all='', sel_hld='', sel_stu='', curr_date=None, prefix='', hide_date_switcher=False):
        html = page_head_html(title, header_kw, prefix=prefix, curr_date=curr_date,
                              all_dates=all_dates, hide_date_switcher=hide_date_switcher,
                              sel_all=sel_all, sel_hld=sel_hld, sel_stu=sel_stu)
        html += content + PAGE_FOOT
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(html)

    # Collect snapshot data per date
    snapshots_by_date = {}
    for e in entries:
        if e['entry_type'] != 'snapshot':
            continue
        dt = e['created_at'][:10]
        pf = e.get('portfolio', '{}')
        try:
            data = json.loads(pf) if isinstance(pf, str) else {}
        except:
            continue
        hld = data.get('holdings', data) if isinstance(data, dict) else {}
        if isinstance(hld, dict) and hld:
            clean = {}
            for k, v in hld.items():
                sym = k.replace('NASDAQ:', '').replace('NYSE:', '')
                clean[sym] = v
            if dt not in snapshots_by_date:
                snapshots_by_date[dt] = []
            snapshots_by_date[dt].append({
                'id': e['id'], 'holdings': clean,
                'cash': data.get('cash', 0),
                'total_value': data.get('total_value', 0),
                'initial_cash': data.get('initial_cash', 0)
            })

    # ── Root pages (all dates) ──
    # Index with JS date filter — all decisions (trades + holds)
    all_dec_entries = [e for e in entries if e['entry_type'] == 'decision']
    # Group entries by date for compact display
    from collections import defaultdict
    grouped = defaultdict(list)
    for e in all_dec_entries:
        d = e['created_at'][:10] if e['created_at'] else 'unknown'
        grouped[d].append(e)

    all_dates = sorted(grouped.keys(), reverse=True)
    all_dates_json = json.dumps(all_dates, ensure_ascii=False)
    all_cards_html = make_cards(all_dec_entries)  # flat list for date folder pages

    # Build grouped HTML: date header + cards per group
    def fmt_date_header(d):
        return f'<div class="tl-date-group" data-date="{d}"><div class="tl-date-hdr">{d}</div>'

    groups_html = '\n'.join(
        fmt_date_header(d) + '\n'.join(
            f'<a href="{d}/entry-{e["id"]}.html" class="entry-card" data-date="{d}">\n'
            f'  <span class="entry-time">{e["created_at"][11:16]}</span>\n'
            f'  <span class="entry-badges">'
            f'    {type_badge(e["entry_type"])}'
            f'    {tkr_badge(e["ticker"]) if e["ticker"] else ""}'
            f'    {pnl_badge(e["pnl"])}'
            f'  </span>\n'
            f'  <span class="entry-title">{escape(e["title"])}</span>\n'
            f'</a>' for e in entries_of_day
        ) + '\n</div>'
        for d, entries_of_day in [(d, grouped[d]) for d in all_dates]
    )
    index_js = f'''<h2 class="section-title">📋 時間線（買賣記錄）</h2>
<div class="snap-selector">
  <label>📅 月份：</label>
  <div class="snap-list" id="tlMonthList"></div>
</div>
<div class="snap-selector" id="daySelector" style="display:none">
  <label>📆 日子：</label>
  <div class="snap-list" id="tlDayList"></div>
</div>
<div id="tlCards" class="tab-content">
{groups_html}
</div>
<script>
const TL_DATES = {all_dates_json};
const MONTHS = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
let selMonth = null, selDay = null;

function parseYmd(d) {{ const p = d.split('-'); return {{y:p[0],m:p[1],d:p[2]}}; }}

// Build month/day lookup
const hasDate = {{}};
TL_DATES.forEach(d => {{ hasDate[d] = true; }});

// Which months have data (e.g. "2026-07")
const hasMonth = {{}};
TL_DATES.forEach(d => {{
  const p = parseYmd(d);
  hasMonth[p.y+'-'+p.m] = true;
}});

function filterTimeline(fullDate) {{
  document.querySelectorAll('.tl-date-group').forEach(g => {{
    g.style.display = (!fullDate || fullDate === 'all' || g.dataset.date === fullDate) ? 'block' : 'none';
  }});
}}

function renderDays(monthKey, monthsWithData) {{
  const dayContainer = document.getElementById('tlDayList');
  const daySel = document.getElementById('daySelector');
  daySel.style.display = 'block';
  dayContainer.innerHTML = '<a href="#" class="snap-btn'+(selDay===null?' active':'')+'" data-day="all">全部</a>' +
    Array.from({{length:31}},(_,i)=>{{
      const d = String(i+1).padStart(2,'0');
      const full = monthKey+'-'+d;
      const has = hasDate[full];
      return '<a href="#" class="snap-btn'+(selDay===d?' active':'')+(has?'':' dimmed')+'" data-day="'+d+'">'+d+'</a>';
    }}).join('');
}}

function renderMonths() {{
  const container = document.getElementById('tlMonthList');
  const allKeys = [];
  // Generate all year-month combos from available data years
  const years = new Set();
  Object.keys(hasMonth).forEach(k => years.add(k.split('-')[0]));
  years.forEach(y => {{
    for (let m = 1; m <= 12; m++) {{
      const mk = y+'-'+String(m).padStart(2,'0');
      allKeys.push(mk);
    }}
  }});
  container.innerHTML = '<a href="#" class="snap-btn'+(selMonth===null?' active':'')+'" data-month="all">全部</a>' +
    allKeys.sort().map(k => {{
      const p = k.split('-');
      const monthIdx = parseInt(p[1]) - 1;
      const label = MONTHS[monthIdx] + ' ' + p[0];
      const has = hasMonth[k];
      return '<a href="#" class="snap-btn'+(selMonth===k?' active':'')+(has?'':' dimmed')+'" data-month="'+k+'">'+label+'</a>';
    }}).join('');
  if (selMonth) renderDays(selMonth);
}}

function onMonthClick(monthKey) {{
  selMonth = monthKey;
  selDay = null;
  if (monthKey) {{
    renderDays(monthKey);
    filterTimeline(null);
  }} else {{
    document.getElementById('daySelector').style.display = 'none';
    filterTimeline('all');
  }}
  renderMonths();
}}

function onDayClick(day) {{
  selDay = day;
  if (day && selMonth) {{
    filterTimeline(selMonth+'-'+day);
  }} else if (selMonth) {{
    filterTimeline(null);
  }}
  renderDays(selMonth);
}}

document.getElementById('tlMonthList').addEventListener('click', function(e) {{
  const btn = e.target.closest('.snap-btn');
  if (!btn) return; e.preventDefault();
  const m = btn.dataset.month;
  onMonthClick(m === 'all' ? null : m);
}});
document.getElementById('tlDayList').addEventListener('click', function(e) {{
  const btn = e.target.closest('.snap-btn');
  if (!btn) return; e.preventDefault();
  onDayClick(btn.dataset.day === 'all' ? null : btn.dataset.day);
}});

renderMonths();
filterTimeline('all');
</script>'''
    write_page(DOCS / 'index.html', '📊 股票審計記錄', index_js,
               sel_all='active', curr_date=None, prefix='', hide_date_switcher=True)

    # Holdings with JS date selector (replaces static per-date holdings)
    snapshots_json = json.dumps(snapshots_by_date, ensure_ascii=False)
    holdings_js = f'''<div class="snap-selector">
  <label>📅 選擇日期：</label>
  <div class="snap-list" id="snapList"></div>
</div>
<div id="holdingsContainer"><p class="empty">載入中…</p></div>
<script>
const SNAPSHOTS = {snapshots_json};
const TKR_COLORS = {json.dumps(TKR_C, ensure_ascii=False)};
let currentDate = null;
function fmtNum(n) {{ return n.toLocaleString('en-US', {{minimumFractionDigits:2, maximumFractionDigits:2}}); }}
function fmtInt(n) {{ return Math.round(n).toLocaleString('en-US'); }}
function tkrBadge(sym) {{
  const c = TKR_COLORS[sym] || '#666';
  return '<span class="tkr" style="--tkr-c:'+c+'">'+sym+'</span>';
}}
function renderHoldings(date) {{
  currentDate = date;
  const snaps = SNAPSHOTS[date];
  if (!snaps || !snaps.length) {{ document.getElementById('holdingsContainer').innerHTML = '<p class="empty">呢日冇持倉快照</p>'; return; }}
  const snap = snaps[snaps.length-1];
  const h = snap.holdings;
  const cash = snap.cash || 0;
  const totalValue = snap.total_value || 0;
  const initCash = snap.initial_cash || 0;
  let totalMV = 0, totalCost = 0, totalShares = 0;
  const rows = Object.keys(h).sort().map(sym => {{
    const pos = h[sym];
    const sh = pos.shares || 0;
    totalShares += sh;
    const cost = pos.avg_cost || pos.entry || 0;
    const price = pos.current_price || pos.current || 0;
    const mv = pos.market_value || pos.mv_usd || (sh * price);
    const pnl = pos.pnl || pos.unrealized_pnl || (mv - sh * cost);
    const chg = pos.chg_pct || pos.change_pct || ((price/cost-1)*100);
    totalMV += mv; totalCost += sh * cost;
    const chgCls = chg >= 0 ? 'pnl-pos' : 'pnl-neg';
    const pnlCls = pnl >= 0 ? 'pnl-pos' : 'pnl-neg';
    return '<tr><td>'+tkrBadge(sym)+'</td><td class="r">'+sh+'</td><td class="r">$'+fmtNum(cost)+'</td><td class="r">$'+fmtNum(price)+'</td><td class="r '+chgCls+'">'+(typeof chg==='number'?chg.toFixed(2):chg)+'%</td><td class="r '+pnlCls+'">$'+fmtNum(pnl)+'</td><td class="r">$'+fmtNum(mv)+'</td></tr>';
  }});
  const totalPnl = totalMV - totalCost;
  const totalReturn = totalValue - initCash;
  const pnlCls = totalPnl >= 0 ? 'pnl-pos' : 'pnl-neg';
  const retCls = totalReturn >= 0 ? 'pnl-pos' : 'pnl-neg';
  document.getElementById('holdingsContainer').innerHTML =
    '<div class="holdings-summary">' +
    '<div class="hsum-row"><span class="hsum-label">持倉市值</span><span class="hsum-val">$'+fmtInt(totalMV)+'</span></div>' +
    '<div class="hsum-row"><span class="hsum-label">現金</span><span class="hsum-val">$'+fmtInt(cash)+'</span></div>' +
    '<div class="hsum-row"><span class="hsum-label">組合總值</span><span class="hsum-val">$'+fmtInt(totalValue)+'</span></div>' +
    '<div class="hsum-row"><span class="hsum-label">持股數</span><span class="hsum-val">'+fmtInt(totalShares)+'</span></div>' +
    '<div class="hsum-row"><span class="hsum-label">持倉</span><span class="hsum-val">'+Object.keys(h).length+'</span></div>' +
    '<div class="hsum-row '+pnlCls+'"><span class="hsum-label">未實現盈虧</span><span class="hsum-val">'+(totalPnl>=0?'+':'')+'$'+fmtInt(totalPnl)+'</span></div>' +
    '<div class="hsum-row '+retCls+'"><span class="hsum-label">總回報 (vs $'+fmtInt(initCash)+')</span><span class="hsum-val">'+(totalReturn>=0?'+':'')+'$'+fmtInt(totalReturn)+'</span></div>' +
    '</div>' +
    '<div class="pf-section"><table class="pf-table"><thead><tr><th>股票</th><th>股數</th><th>平均成本</th><th>現價</th><th>變幅</th><th>盈虧</th><th>市值</th></tr></thead><tbody>'+rows.join('')+'</tbody></table></div>';
  // Update button active state
  document.querySelectorAll('.snap-btn').forEach(b => b.classList.toggle('active', b.dataset.date === date));
}}
// Render date buttons + latest snapshot
const dates = Object.keys(SNAPSHOTS).sort().reverse();
document.getElementById('snapList').innerHTML = dates.map(d => '<a href="#" class="snap-btn" data-date="'+d+'">'+d+'</a>').join('');
document.getElementById('snapList').addEventListener('click', function(e) {{
  const btn = e.target.closest('.snap-btn');
  if (btn) {{ renderHoldings(btn.dataset.date); e.preventDefault(); }}
}});
if (dates.length) renderHoldings(dates[0]);
</script>'''
    write_page(DOCS / 'holdings.html', '💼 持倉',
               f'<h2 class="section-title">💼 持倉</h2>\n{holdings_js}',
               sel_hld='active', curr_date=None, prefix='', hide_date_switcher=True)

    # Studies with JS date filter
    stu_cards_html = make_cards([e for e in entries if e['entry_type'] in ('study','analysis')])
    write_page(DOCS / 'studies.html', '📚 研究 — 全部',
               f'''<h2 class="section-title">📚 研究分析</h2>
<div class="snap-selector">
  <label>📅 日期：</label>
  <div class="snap-list" id="stuDateList"></div>
</div>
<div id="stuCards" class="tab-content">
{stu_cards_html}
</div>
<script>
const STU_DATES = {all_dates_json};
const stuData = {{}};
document.querySelectorAll('#stuCards .entry-card').forEach(c => {{
  const d = c.dataset.date;
  if (d) {{ if (!stuData[d]) stuData[d] = []; stuData[d].push(c); }}
}});
function filterStu(date) {{
  document.querySelectorAll('#stuCards .entry-card').forEach(c => c.style.display = 'none');
  if (!date || date === 'all') {{
    document.querySelectorAll('#stuCards .entry-card').forEach(c => c.style.display = 'block');
  }} else if (stuData[date]) {{
    stuData[date].forEach(c => c.style.display = 'block');
  }}
  document.querySelectorAll('#stuDateList .snap-btn').forEach(b => b.classList.toggle('active', b.dataset.date === (date||'all')));
}}
document.getElementById('stuDateList').innerHTML = '<a href="#" class="snap-btn active" data-date="all">全部</a>' +
  STU_DATES.map(d => '<a href="#" class="snap-btn" data-date="'+d+'">'+d+'</a>').join('');
document.getElementById('stuDateList').addEventListener('click', function(e) {{
  const btn = e.target.closest('.snap-btn');
  if (btn) {{ filterStu(btn.dataset.date); e.preventDefault(); }}
}});
</script>''',
               sel_stu='active', curr_date=None, prefix='', hide_date_switcher=True)

    # ── Date folder pages ── (JS timeline with auto-filter for date)
    for dt in all_dates:
        day_dir = DOCS / dt
        day_dir.mkdir(parents=True, exist_ok=True)
        dt_json = json.dumps(dt)
        day_html = f'''<div class="snap-selector">
  <label>📅 日期：</label>
  <div class="snap-list" id="tlDateList"></div>
</div>
<div id="tlCards" class="tab-content">
{all_cards_html}
</div>
<script>
const TL_DATES = {all_dates_json};
function filterTimeline(date) {{
  document.querySelectorAll('#tlCards .entry-card').forEach(c => c.style.display = 'none');
  if (!date || date === 'all') {{
    document.querySelectorAll('#tlCards .entry-card').forEach(c => c.style.display = 'block');
  }} else {{
    document.querySelectorAll('#tlCards .entry-card[data-date="'+date+'"]').forEach(c => c.style.display = 'block');
  }}
  document.querySelectorAll('#tlDateList .snap-btn').forEach(b => b.classList.toggle('active', b.dataset.date === (date||'all')));
}}
document.getElementById('tlDateList').innerHTML = '<a href="../index.html" class="snap-btn" data-date="all">全部</a>' +
  TL_DATES.map(d => '<a href="../'+(d===TL_DATES[0]?'index.html':d+'/index.html')+'" class="snap-btn'+(d==={dt_json}?' active':'')+'" data-date="'+d+'">'+d+'</a>').join('');
filterTimeline({dt_json});
</script>'''
        write_page(day_dir / 'index.html', f'📊 {dt} — 股票審計記錄',
                   day_html, curr_date=dt, prefix='../', sel_all='', hide_date_switcher=True)

    # ── Detail pages ── (entries live at root for now)
    detail_entries = entries  # all entries get detail pages at root
    for e in detail_entries:
        generate_detail(e, all_dates)

    return count

# ── detail page ──

def generate_detail(e, all_dates=None):
    portfolio_html = ''
    pf_raw = e.get('portfolio', '{}')
    if pf_raw and pf_raw != '{}':
        try:
            pf = json.loads(pf_raw) if isinstance(pf_raw, str) else pf_raw
        except:
            pf = {}
        holdings = pf.get('holdings', pf)
        if isinstance(holdings, dict) and holdings:
            rows = []
            total = 0
            for sym, pos in holdings.items():
                mv = pos.get('market_value', pos.get('mv_usd', 0))
                total += mv
                sym_clean = sym.replace('NASDAQ:', '')
                tc = TKR_C.get(sym_clean, '#666')
                chg = pos.get('chg_pct', pos.get('change_pct', ''))
                chg_cls = ''
                if isinstance(chg, (int, float)):
                    chg_cls = 'pnl-pos' if chg >= 0 else 'pnl-neg'
                pnl = pos.get('pnl', pos.get('unrealized_pnl', ''))
                pnl_cls = ''
                if isinstance(pnl, (int, float)):
                    pnl_cls = 'pnl-pos' if pnl >= 0 else 'pnl-neg'
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
        <h3>Snapshot 當時嘅持倉</h3>
        <div class="pf-total">總值: <strong>${fmt_num(total)}</strong></div>
        <table class="pf-table">
          <thead><tr><th>股票</th><th>股數</th><th>平均成本</th><th>現價</th><th>變幅</th><th>盈虧</th><th>市值</th><th>佔比</th></tr></thead>
          <tbody>{''.join(rows)}</tbody>
        </table>
      </div>'''

    reasoning_html = render_md(e['reasoning'])
    dt = e['created_at'][:10] if e['created_at'] else ''
    prefix = '../' if dt else ''

    # Use page_head_html like all other pages
    detail_header_kw = dict(
        title=f"#{e['id']} — {escape(e['title'])}",
        count=e.get('_total_count', 0), decisions=0, snapshots=0, studies=0,
        tickers_n=0, ticker_row='', now=''
    )
    page_head = page_head_html(
        f"#{e['id']} — {escape(e['title'])}", detail_header_kw,
        prefix=prefix, all_dates=all_dates, hide_date_switcher=True,
        curr_date=dt
    )

    html = f'''{page_head}
  <a href="{prefix}index.html" class="back-link">← 返去時間線</a>
  <div class="detail-entry">
    <div class="detail-meta">
      <div class="detail-time">{fmt_dt(e['created_at'])}</div>
      <div class="entry-badges">
        {type_badge(e['entry_type'])}
        {tkr_badge(e['ticker']) if e['ticker'] else ''}
        {pnl_badge(e['pnl'])}
      </div>
    </div>
    <h1>{escape(e['title'])}</h1>
    <div class="entry-tags">{tag_html(e['tags'])}</div>
  </div>
  <div class="reasoning">
    {reasoning_html}
  </div>
  {portfolio_html}
</main>
<footer>
  <p>📊 <a href="{prefix}index.html">返回時間線</a> · 記錄 #{e['id']} · {fmt_dt(e['created_at'])}</p>
</footer>
</body>
</html>'''
    out_dir = (DOCS / dt) if dt else DOCS
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"entry-{e['id']}.html").write_text(html)

# ── CSS ──

def write_css():
    css = '''/* ── Stock Audit Log v2 (Tabs) ────────────────── */
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
  padding: 28px 20px 0;
}
.hd-inner { max-width: 800px; margin: 0 auto; }
header h1 { font-size: 1.6em; }
.hd-sub { color: var(--text-muted); font-size: 0.85em; margin: 2px 0 6px; }
.hd-stats { display: flex; gap: 12px; flex-wrap: wrap; margin: 6px 0; }
.stat { background: var(--bg-card); padding: 2px 10px; border-radius: 12px; font-size: 0.82em; border: 1px solid var(--border); }
.hd-tickers { margin: 4px 0; display: flex; gap: 4px; flex-wrap: wrap; }
.hd-last { color: var(--text-muted); font-size: 0.78em; margin-bottom: 4px; }

/* tabs */
.tabs {
  display: flex;
  justify-content: center;
  gap: 4px;
  margin-top: 14px;
  padding: 4px;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 12px;
}
.tab {
  display: inline-block;
  padding: 7px 18px;
  font-size: 0.85em;
  font-weight: 500;
  color: var(--text-muted);
  border-radius: 8px;
  transition: all 0.15s;
  white-space: nowrap;
}
.tab:hover {
  color: var(--text);
  background: var(--bg-hover);
  text-decoration: none;
}
.tab.active {
  color: #fff;
  background: var(--accent);
}
.tab.active:hover {
  background: #4090e0;
}

/* main */
main { max-width: 800px; margin: 0 auto; padding: 16px 20px; }
.section-title { font-size: 1.1em; font-weight: 600; margin-bottom: 12px; color: var(--text-muted); }

/* snapshot date selector */
.snap-selector {
  margin-bottom: 16px;
}
.snap-selector label {
  display: block;
  font-size: 0.82em;
  color: var(--text-muted);
  margin-bottom: 6px;
}
.snap-list {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
.snap-btn {
  display: inline-block;
  padding: 5px 14px;
  font-size: 0.82em;
  font-weight: 500;
  color: var(--text-muted);
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 8px;
  transition: all 0.15s;
}
.snap-btn:hover {
  color: var(--text);
  border-color: var(--accent);
  text-decoration: none;
}
.snap-btn.active {
  color: #fff;
  background: var(--accent);
  border-color: var(--accent);
}

/* iframe for holdings page */
.snap-iframe {
  width: 100%;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--bg);
  min-height: 500px;
}

/* date switcher */
.date-switcher {
  margin: 10px 0 6px;
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.date-switcher label {
  font-size: 0.8em;
  color: var(--text-muted);
  white-space: nowrap;
}
.date-list {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
}
.date-btn {
  display: inline-block;
  padding: 3px 10px;
  font-size: 0.78em;
  font-weight: 500;
  color: var(--text-muted);
  border: 1px solid var(--border);
  border-radius: 6px;
  transition: all 0.15s;
}
.date-btn:hover {
  color: var(--text);
  border-color: var(--accent);
  text-decoration: none;
}
.date-btn.active {
  color: #fff;
  background: var(--accent);
  border-color: var(--accent);
}

/* entry cards */
.entry-card {
  display: block;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 14px 18px;
  margin-bottom: 8px;
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
  margin-bottom: 5px;
  flex-wrap: wrap;
  gap: 4px;
}
.entry-time { color: var(--text-muted); font-size: 0.78em; }
.entry-badges { display: flex; gap: 4px; align-items: center; flex-wrap: wrap; }
.entry-title { font-size: 1.02em; font-weight: 600; margin-bottom: 4px; }
.entry-tags { display: flex; gap: 4px; flex-wrap: wrap; }

/* badges */
.type-badge {
  display: inline-block;
  padding: 1px 8px;
  border-radius: 10px;
  font-size: 0.7em;
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
  font-size: 0.78em;
  font-weight: 700;
  background: color-mix(in srgb, var(--tkr-c) 15%, transparent);
  color: var(--tkr-c);
  border: 1px solid color-mix(in srgb, var(--tkr-c) 40%, transparent);
}
.tkr-mini { display: inline-block; font-weight: 700; color: var(--tkr-c); }
.pnl { font-size: 0.8em; font-weight: 600; padding: 1px 6px; border-radius: 6px; }
.pnl-pos { color: var(--green); }
.pnl-neg { color: var(--red); }

.tag {
  display: inline-block;
  padding: 1px 7px;
  border-radius: 8px;
  font-size: 0.7em;
  font-weight: 500;
  background: var(--bg);
  border: 1px solid var(--border);
  color: var(--text-muted);
}

/* holdings page */
.holdings-summary {
  display: flex;
  gap: 16px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}
.hsum-row {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px 18px;
  text-align: center;
  flex: 1;
  min-width: 120px;
}
.hsum-label { display: block; font-size: 0.78em; color: var(--text-muted); margin-bottom: 4px; }
.hsum-val { display: block; font-size: 1.3em; font-weight: 700; }
.hsum-row.pnl-pos .hsum-val { color: var(--green); }
.hsum-row.pnl-neg .hsum-val { color: var(--red); }

/* detail page */
.detail-hd { padding-bottom: 16px; }
.detail-hd .tabs { margin-top: 0; }
.detail-hd h1 { font-size: 1.4em; margin-top: 8px; }
.detail-meta { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 6px; }
.detail-time { color: var(--text-muted); font-size: 0.82em; }
.back-link { display: inline-block; margin-bottom: 8px; font-size: 0.85em; }

.reasoning {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 18px;
  margin-bottom: 16px;
}
.reasoning p { margin-bottom: 8px; }
.reasoning li { margin-bottom: 3px; margin-left: 18px; }
.reasoning li.sub { list-style-type: circle; margin-left: 32px; color: var(--text-muted); }
.reasoning li.num { list-style-type: decimal; margin-left: 18px; }
.reasoning pre {
  background: #0d1117;
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 10px;
  overflow-x: auto;
  font-size: 0.83em;
  margin: 8px 0;
}
.reasoning code {
  background: #0d1117;
  padding: 1px 5px;
  border-radius: 4px;
  font-size: 0.83em;
}
.reasoning br { display: none; }
.reasoning strong { color: #f0f6fc; }
.empty { color: var(--text-muted); font-style: italic; padding: 20px; text-align: center; }

/* timeline group */
.tl-date-group { margin-bottom: 12px; }
.tl-date-hdr {
  font-size: 0.85em; font-weight: 600; color: var(--accent);
  padding: 6px 0 4px; margin-bottom: 4px;
  border-bottom: 1px solid var(--border);
}
.tl-date-group .entry-card {
  padding: 8px 14px; margin-bottom: 3px;
  display: flex; align-items: center; gap: 8px;
}
.tl-date-group .entry-card .entry-time {
  font-size: 0.72em; color: var(--text-muted); white-space: nowrap; min-width: 3em;
}
.tl-date-group .entry-card .entry-title { font-size: 0.88em; flex: 1; margin: 0; }
.tl-date-group .entry-card .entry-badges { margin: 0; }

/* portfolio table */
.pf-section {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 18px;
  margin-bottom: 16px;
}
.pf-section h3 { margin-bottom: 8px; font-size: 0.95em; color: var(--text-muted); }
.pf-total { text-align: right; margin-bottom: 8px; font-size: 0.95em; color: var(--text-muted); }
.pf-table { width: 100%; border-collapse: collapse; font-size: 0.82em; }
.pf-table th { text-align: left; padding: 5px 8px; border-bottom: 1px solid var(--border); color: var(--text-muted); font-weight: 500; }
.pf-table td { padding: 5px 8px; border-bottom: 1px solid var(--border); }
.pf-table th.r, td.r { text-align: right; }
.pf-table tr:last-child td { border-bottom: none; }

/* footer */
footer {
  max-width: 800px;
  margin: 0 auto;
  padding: 16px 20px;
  text-align: center;
  color: var(--text-muted);
  font-size: 0.78em;
  border-top: 1px solid var(--border);
}
footer a { color: var(--text-muted); }

/* responsive */
@media (max-width: 600px) {
  header { padding: 20px 12px 0; }
  main { padding: 12px; }
  .tab { padding: 5px 10px; font-size: 0.78em; }
  .entry-card { padding: 10px 12px; }
  .holdings-summary { gap: 8px; }
  .hsum-row { padding: 8px 12px; min-width: 80px; }
  .hsum-val { font-size: 1.1em; }
  .pf-table { font-size: 0.72em; }
  .pf-table th, .pf-table td { padding: 3px 5px; }
}
'''
    (ASSETS / 'style.css').write_text(css)

# ── build ──

def cmd_build(args):
    DOCS.mkdir(parents=True, exist_ok=True)
    ASSETS.mkdir(parents=True, exist_ok=True)
    (DOCS / '.nojekyll').write_text('')

    write_css()

    conn = get_db()
    rows = conn.execute("SELECT * FROM entries ORDER BY created_at DESC").fetchall()
    conn.close()

    entries = [dict(r) for r in rows]
    n = build_site(entries)

    print(f"✓ Built {n} entries → {DOCS}/")
    print(f"  index.html | holdings.html | decisions.html | studies.html + {n} detail pages")

# ── push ──

def cmd_push(args):
    msg = args.message or f"Audit log update {datetime.now(TZ_HK).strftime('%Y-%m-%d %H:%M')}"
    for f in DOCS.rglob('*.html'):
        content = f.read_text()
        if '⚠' in content:
            print(f"⚠ WARNING: {f.name} contains ⚠ markers (possible real portfolio data)")
            if not args.force:
                print("  Use --force to push anyway, or review the data first.")
                return

    subprocess.run(['git', '-C', str(HERE), 'add', 'docs/'], check=True)
    result = subprocess.run(['git', '-C', str(HERE), 'diff', '--cached', '--quiet'], capture_output=True)
    if result.returncode == 0:
        print("✓ Nothing new to push")
        return
    subprocess.run(['git', '-C', str(HERE), 'commit', '-m', msg], check=True)
    subprocess.run(['git', '-C', str(HERE), 'push', 'origin', 'main'], check=True)
    print(f"✓ Pushed to GitHub: {msg}")

# ── commit (one-shot) ──

def cmd_commit(args):
    eid = cmd_log(args)
    cmd_build(args)
    cmd_push(args)
    print(f"\n✓ Entry #{eid} committed and pushed")

# ── main ──

def main():
    p = argparse.ArgumentParser(description='Stock Audit Log — record & publish trade decisions')
    sub = p.add_subparsers(dest='cmd')

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
    plog.add_argument('--datetime', default='', help='Custom timestamp (YYYY-MM-DD HH:MM:SS) for historical entries')

    pbuild = sub.add_parser('build', help='Generate HTML site from database')
    ppush = sub.add_parser('push', help='Commit docs/ and push to GitHub')
    ppush.add_argument('message', nargs='?', default='')
    ppush.add_argument('--force', action='store_true')

    pcommit = sub.add_parser('commit', help='Log + build + push in one step')
    for a in ['type','title','ticker','reasoning','price','pnl','portfolio','tags','source','datetime']:
        kw = {'default': '', 'required': a in ('type','title')}
        if a == 'type':
            kw['choices'] = ['decision','snapshot','study','analysis']
        if a == 'price':
            kw['type'] = float; kw.pop('default')
        if a == 'force':
            continue
        pcommit.add_argument(f'--{a}', **kw)
    pcommit.add_argument('--force', action='store_true')

    args = p.parse_args()
    if args.cmd == 'log':      cmd_log(args)
    elif args.cmd == 'build':  cmd_build(args)
    elif args.cmd == 'push':   cmd_push(args)
    elif args.cmd == 'commit': cmd_commit(args)
    else:                      p.print_help()

if __name__ == '__main__':
    main()
