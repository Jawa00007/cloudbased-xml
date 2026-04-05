"""
Client data confirmation report — reads live data from Supabase and generates
an HTML report showing PODs, date ranges, record counts, and sample measurements.

Usage:
    py report.py --account=BAT
    py report.py --all
"""

from __future__ import annotations

import argparse
import asyncio
import selectors
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from sqlalchemy import text
from backend.db.session import get_session
from backend.ingestion.ingest import ACCOUNT_SCHEMA_MAP, schema_for

# ── Windows SelectorEventLoop fix ─────────────────────────────────────────────
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


# ── Data collection ────────────────────────────────────────────────────────────

async def collect_account_data(account_id: str, schema: str) -> dict:
    data = {}

    async with get_session(schema) as session:
        # File ingestion summary
        r = await session.execute(text("""
            SELECT status, COUNT(*) as cnt
            FROM files
            GROUP BY status
            ORDER BY cnt DESC
        """))
        data["file_summary"] = r.fetchall()

        # Recent files
        r = await session.execute(text("""
            SELECT file_name, cod_flusso, mese_anno, status, processed_at
            FROM files
            ORDER BY processed_at DESC
            LIMIT 20
        """))
        data["recent_files"] = r.fetchall()

        # POD list with stats
        r = await session.execute(text("""
            SELECT
                pod,
                MIN(data_misura)  AS from_date,
                MAX(data_misura)  AS to_date,
                COUNT(DISTINCT data_misura) AS days,
                COUNT(*)          AS periods,
                ROUND(SUM(ea_kwh)::numeric, 3) AS total_kwh,
                tipo_dato
            FROM measurements
            GROUP BY pod, tipo_dato
            ORDER BY pod, tipo_dato
        """))
        data["pod_curves"] = r.fetchall()

        # Totalizer PODs
        r = await session.execute(text("""
            SELECT
                pod,
                MIN(data_misura) AS from_date,
                MAX(data_misura) AS to_date,
                COUNT(*)         AS records,
                ROUND(COALESCE(SUM(ea_f1),0) + COALESCE(SUM(ea_f2),0) + COALESCE(SUM(ea_f3),0)
                      + COALESCE(SUM(ea_m),0)::numeric, 3) AS total_kwh
            FROM measurements_totalizer
            GROUP BY pod
            ORDER BY pod
        """))
        data["pod_totalizer"] = r.fetchall()

        # Overall counts
        r = await session.execute(text("""
            SELECT
                (SELECT COUNT(*) FROM measurements)            AS curves,
                (SELECT COUNT(*) FROM measurements_secondary)  AS secondary,
                (SELECT COUNT(*) FROM measurements_totalizer)  AS totalizer,
                (SELECT COUNT(*) FROM corrections)             AS corrections,
                (SELECT COUNT(*) FROM files WHERE status='ok') AS files_ok,
                (SELECT COUNT(*) FROM files WHERE status='error') AS files_err,
                (SELECT COUNT(*) FROM files WHERE status='skipped') AS files_skip
        """))
        data["counts"] = r.fetchone()

        # Flow type breakdown
        r = await session.execute(text("""
            SELECT cod_flusso, COUNT(*) as cnt
            FROM files
            WHERE status = 'ok'
            GROUP BY cod_flusso
            ORDER BY cnt DESC
        """))
        data["flow_types"] = r.fetchall()

        # Sample measurements (5 rows)
        r = await session.execute(text("""
            SELECT pod, data_misura, periodo, ea_kwh, tipo_dato, source_file
            FROM measurements
            ORDER BY data_misura DESC, pod, periodo
            LIMIT 10
        """))
        data["sample_measurements"] = r.fetchall()

    return data


# ── HTML generation ────────────────────────────────────────────────────────────

CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
       background: #f0f2f5; color: #1a1a2e; }
.header { background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
          color: white; padding: 40px 48px; }
.header h1 { font-size: 28px; font-weight: 700; letter-spacing: -0.5px; }
.header p  { margin-top: 6px; opacity: 0.7; font-size: 14px; }
.badge { display: inline-block; background: rgba(255,255,255,0.15);
         border-radius: 20px; padding: 3px 12px; font-size: 12px; margin-top: 10px; }
.container { max-width: 1200px; margin: 0 auto; padding: 32px 24px; }
.grid-4 { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin-bottom: 28px; }
.grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 28px; }
.card { background: white; border-radius: 12px; padding: 24px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.08); }
.stat-card { text-align: center; }
.stat-card .value { font-size: 36px; font-weight: 700; color: #0f3460; }
.stat-card .label { font-size: 12px; color: #888; margin-top: 4px; text-transform: uppercase;
                    letter-spacing: 0.5px; }
.stat-card .sub   { font-size: 11px; color: #aaa; margin-top: 2px; }
h2 { font-size: 16px; font-weight: 600; margin-bottom: 16px; color: #1a1a2e; }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th { text-align: left; padding: 10px 12px; background: #f8f9fb;
     color: #555; font-weight: 600; font-size: 11px; text-transform: uppercase;
     letter-spacing: 0.4px; border-bottom: 1px solid #e8eaed; }
td { padding: 10px 12px; border-bottom: 1px solid #f0f2f5; color: #333; }
tr:last-child td { border-bottom: none; }
tr:hover td { background: #fafbfc; }
.pill { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 11px;
        font-weight: 600; }
.pill-ok      { background: #d1fae5; color: #065f46; }
.pill-error   { background: #fee2e2; color: #991b1b; }
.pill-skip    { background: #fef3c7; color: #92400e; }
.pill-E       { background: #dbeafe; color: #1e40af; }
.pill-S       { background: #ede9fe; color: #5b21b6; }
.full { grid-column: 1 / -1; }
.footer { text-align: center; padding: 24px; color: #aaa; font-size: 12px; }
"""

def fmt_num(n) -> str:
    if n is None:
        return "—"
    try:
        return f"{int(n):,}"
    except Exception:
        return str(n)

def fmt_kwh(n) -> str:
    if n is None:
        return "—"
    try:
        return f"{float(n):,.3f}"
    except Exception:
        return str(n)

def pill(text: str, cls: str = "") -> str:
    return f'<span class="pill pill-{cls}">{text}</span>'

def status_pill(s: str) -> str:
    return pill(s, s)

def tipo_pill(t: str) -> str:
    return pill(t, t)


def build_html(account_id: str, schema: str, d: dict) -> str:
    counts = d["counts"]
    now = datetime.now().strftime("%d %B %Y, %H:%M")

    # ── stat cards ──
    cards = [
        (fmt_num(counts[0]), "Curve records", "quarter-hourly measurements"),
        (fmt_num(counts[2]), "Totalizer records", "band-total measurements"),
        (fmt_num(counts[1]), "Secondary records", "estimated / fallback"),
        (fmt_num(counts[3]), "Corrections logged", "Flusso 2 audit entries"),
    ]
    cards_html = "".join(f"""
      <div class="card stat-card">
        <div class="value">{v}</div>
        <div class="label">{l}</div>
        <div class="sub">{s}</div>
      </div>""" for v, l, s in cards)

    file_cards = [
        (fmt_num(counts[4]), "Files OK", "successfully ingested"),
        (fmt_num(counts[5]), "Files errored", "parse / DB errors"),
        (fmt_num(counts[6]), "Files skipped", "F2G / already processed"),
        (fmt_num(len(d["pod_curves"]) + len(d["pod_totalizer"])), "POD+type rows", "unique (pod, tipo_dato) pairs"),
    ]
    file_cards_html = "".join(f"""
      <div class="card stat-card">
        <div class="value">{v}</div>
        <div class="label">{l}</div>
        <div class="sub">{s}</div>
      </div>""" for v, l, s in file_cards)

    # ── pod table (curves) ──
    pod_rows = ""
    for row in d["pod_curves"]:
        pod, from_d, to_d, days, periods, kwh, tipo = row
        pod_rows += f"""<tr>
          <td><code>{pod}</code></td>
          <td>{from_d}</td>
          <td>{to_d}</td>
          <td style="text-align:right">{fmt_num(days)}</td>
          <td style="text-align:right">{fmt_num(periods)}</td>
          <td style="text-align:right">{fmt_kwh(kwh)}</td>
          <td>{tipo_pill(tipo or '?')}</td>
        </tr>"""

    pod_curve_table = f"""
    <div class="card full">
      <h2>Quarter-Hourly PODs ({len(d["pod_curves"])} rows)</h2>
      <table>
        <tr>
          <th>POD</th><th>From</th><th>To</th>
          <th style="text-align:right">Days</th>
          <th style="text-align:right">96-min periods</th>
          <th style="text-align:right">Total kWh</th>
          <th>TipoDato</th>
        </tr>
        {pod_rows or '<tr><td colspan="7" style="color:#aaa;text-align:center">No curve records</td></tr>'}
      </table>
    </div>"""

    # ── pod table (totalizer) ──
    tot_rows = ""
    for row in d["pod_totalizer"]:
        pod, from_d, to_d, recs, kwh = row
        tot_rows += f"""<tr>
          <td><code>{pod}</code></td>
          <td>{from_d}</td>
          <td>{to_d}</td>
          <td style="text-align:right">{fmt_num(recs)}</td>
          <td style="text-align:right">{fmt_kwh(kwh)}</td>
        </tr>"""

    pod_tot_table = f"""
    <div class="card full">
      <h2>Totalizer PODs ({len(d["pod_totalizer"])} rows)</h2>
      <table>
        <tr>
          <th>POD</th><th>From</th><th>To</th>
          <th style="text-align:right">Records</th>
          <th style="text-align:right">Total kWh (F1+F2+F3+M)</th>
        </tr>
        {tot_rows or '<tr><td colspan="5" style="color:#aaa;text-align:center">No totalizer records</td></tr>'}
      </table>
    </div>"""

    # ── flow type breakdown ──
    flow_rows = "".join(
        f"<tr><td>{cod}</td><td style='text-align:right'>{fmt_num(cnt)}</td></tr>"
        for cod, cnt in d["flow_types"]
    )
    flow_table = f"""
    <div class="card">
      <h2>Flow Types Ingested</h2>
      <table>
        <tr><th>CodFlusso</th><th style="text-align:right">Files</th></tr>
        {flow_rows or '<tr><td colspan="2" style="color:#aaa">No data</td></tr>'}
      </table>
    </div>"""

    # ── recent files ──
    recent_rows = "".join(
        f"""<tr>
          <td style="font-size:11px;color:#666">{fn}</td>
          <td>{cod or '—'}</td>
          <td>{ma or '—'}</td>
          <td>{status_pill(st)}</td>
        </tr>"""
        for fn, cod, ma, st, _ in d["recent_files"]
    )
    recent_table = f"""
    <div class="card">
      <h2>Recently Ingested Files</h2>
      <table>
        <tr><th>File name</th><th>Flow</th><th>Month</th><th>Status</th></tr>
        {recent_rows or '<tr><td colspan="4" style="color:#aaa">No files</td></tr>'}
      </table>
    </div>"""

    # ── sample measurements ──
    sample_rows = "".join(
        f"""<tr>
          <td><code style="font-size:11px">{pod}</code></td>
          <td>{dm}</td>
          <td style="text-align:right">{per}</td>
          <td style="text-align:right">{fmt_kwh(kwh)}</td>
          <td>{tipo_pill(td or '?')}</td>
          <td style="font-size:11px;color:#999">{sf}</td>
        </tr>"""
        for pod, dm, per, kwh, td, sf in d["sample_measurements"]
    )
    sample_table = f"""
    <div class="card full">
      <h2>Sample Measurements (latest 10 records)</h2>
      <table>
        <tr>
          <th>POD</th><th>Date</th>
          <th style="text-align:right">Period</th>
          <th style="text-align:right">Ea kWh</th>
          <th>Type</th><th>Source file</th>
        </tr>
        {sample_rows}
      </table>
    </div>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>SII Data Confirmation — {account_id}</title>
  <style>{CSS}</style>
</head>
<body>
  <div class="header">
    <h1>SII Measurement Data — {account_id}</h1>
    <p>Data confirmation report for client review</p>
    <span class="badge">Schema: {schema} &nbsp;·&nbsp; Generated: {now}</span>
  </div>
  <div class="container">

    <div class="grid-4">
      {cards_html}
    </div>

    <div class="grid-4" style="margin-bottom:28px">
      {file_cards_html}
    </div>

    <div class="grid-2">
      {flow_table}
      {recent_table}
    </div>

    <div class="grid-2" style="margin-bottom:28px">
      {pod_curve_table}
    </div>

    <div class="grid-2" style="margin-bottom:28px">
      {pod_tot_table}
    </div>

    <div class="grid-2" style="margin-bottom:28px">
      {sample_table}
    </div>

  </div>
  <div class="footer">
    SII Energy Measurement Analytics Platform &nbsp;·&nbsp; Confidential &mdash; Client review only
  </div>
</body>
</html>"""


# ── Main ───────────────────────────────────────────────────────────────────────

async def generate_report(account_id: str, out_path: Path) -> None:
    schema = schema_for(account_id)
    print(f"Collecting data for {account_id} (schema: {schema}) …")
    data = await collect_account_data(account_id, schema)
    html = build_html(account_id, schema, data)
    out_path.write_text(html, encoding="utf-8")
    print(f"Report saved -> {out_path}")


async def main_async(args) -> None:
    out_dir = Path(__file__).parent / "reports"
    out_dir.mkdir(exist_ok=True)

    if args.all:
        for acc in ACCOUNT_SCHEMA_MAP:
            out = out_dir / f"report_{acc.lower().replace(' ', '_')}.html"
            try:
                await generate_report(acc, out)
            except Exception as e:
                print(f"  ERROR {acc}: {e}")
    else:
        out = out_dir / f"report_{args.account.lower()}.html"
        await generate_report(args.account, out)


def main() -> None:
    parser = argparse.ArgumentParser(description="SII client data confirmation report")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--account", help="Account name, e.g. BAT")
    group.add_argument("--all", action="store_true")
    args = parser.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
