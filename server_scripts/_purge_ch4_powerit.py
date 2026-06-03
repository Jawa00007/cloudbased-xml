"""Finish the purge for ch4 (month-by-month DELETE to avoid timeout) and VACUUM FULL power_it.

ch4.measurements is 43 GB — deleting 7 months at once timed out at 180s.
This script deletes one month at a time (Jun→Dec 2025), then VACUUM FULL both tables.
power_it had 0 rows to delete but has dead tuples from the previous retention run —
VACUUM FULL reclaims that space.
"""
import os, sys, time
import paramiko

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
HOST = "104.248.32.23"; USER = "root"
PW = os.environ.get('SII_SSH_PWD', '')

MONTHS = [
    ("2025-06-01", "2025-07-01"),
    ("2025-07-01", "2025-08-01"),
    ("2025-08-01", "2025-09-01"),
    ("2025-09-01", "2025-10-01"),
    ("2025-10-01", "2025-11-01"),
    ("2025-11-01", "2025-12-01"),
    ("2025-12-01", "2026-01-01"),
]


def connect():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, username=USER, password=PW, timeout=15)
    ssh.get_transport().set_keepalive(30)
    return ssh


def run(ssh, cmd, timeout=60):
    _, o, e = ssh.exec_command(cmd, timeout=timeout)
    out = o.read().decode('utf-8', errors='replace').strip()
    err = e.read().decode('utf-8', errors='replace').strip()
    if err and not any(w in err.lower() for w in ('warning', 'notice', 'deprecated', 'hint')):
        print(f"  stderr: {err[:300]}")
    return out


def disk_free_gb(ssh):
    out = run(ssh, "df / | tail -1", 10)
    return int(out.split()[3]) / 1_048_576


def vacuum_running(ssh):
    row = run(ssh, r"""docker exec sii-db-1 psql -U sii -d sii -t -c \
      "SELECT extract(epoch FROM (now()-query_start))::int \
       FROM pg_stat_activity WHERE query ~ '^VACUUM' AND state='active' LIMIT 1;" """, 15)
    val = row.strip()
    return (True, int(val)) if (val and val.isdigit()) else (False, 0)


def vacuum_full(ssh, schema, table="measurements"):
    """Launch detached VACUUM FULL and poll until done. Returns updated ssh."""
    running, _ = vacuum_running(ssh)
    if not running:
        run(ssh,
            f"docker exec -d sii-db-1 psql -U sii -d sii -c "
            f"'VACUUM FULL {schema}.{table};'", 15)
        time.sleep(5)
        print(f"  VACUUM FULL {schema}.{table} launched. Polling every 60s...")

    t0 = time.time()
    while True:
        time.sleep(60)
        try: ssh.close()
        except: pass
        try:
            ssh = connect()
        except Exception as exc:
            print(f"  [reconnect failed: {exc}] retrying...")
            time.sleep(30)
            continue
        running, secs = vacuum_running(ssh)
        elapsed = int(time.time() - t0)
        if not running:
            print(f"  VACUUM FULL done [{elapsed}s]")
            return ssh
        print(f"  vacuuming... {secs}s in-DB / {elapsed}s total", flush=True)


def main():
    if not PW:
        print("ERROR: SII_SSH_PWD not set"); return

    ssh = connect()
    free = disk_free_gb(ssh)
    print(f"Connected  |  disk free: {free:.1f} GB\n")

    # ── CH4: delete month by month ─────────────────────────────────────────────
    print("=" * 62)
    print("CH4 — deleting Jun–Dec 2025 one month at a time")
    print("=" * 62)
    total_ch4 = 0
    for start, end in MONTHS:
        ssh.close(); ssh = connect()
        for table in ("measurements", "measurements_secondary"):
            q = (f"DELETE FROM ch4.{table} WHERE account_id = 'CH4' "
                 f"AND data_misura >= '{start}' AND data_misura < '{end}'")
            out = run(ssh, f'docker exec sii-db-1 psql -U sii -d sii -t -c "{q}"', 300)
            n = 0
            for tok in out.split():
                if tok.isdigit(): n = int(tok); break
            total_ch4 += n
            print(f"  {start[:7]}  {table}: {n:,} rows deleted")

        # totalizer + aux tables for this month
        for extra_q in [
            f"DELETE FROM ch4.measurements_totalizer WHERE account_id='CH4' "
            f"AND ((data_misura>='{start}' AND data_misura<'{end}') "
            f"OR (data_misura IS NULL AND mese_anno IS NOT NULL "
            f"AND to_date(mese_anno,'MM/YYYY')>='{start}' AND to_date(mese_anno,'MM/YYYY')<'{end}'))",
            f"DELETE FROM ch4.files WHERE account_id='CH4' AND mese_anno IS NOT NULL "
            f"AND to_date(mese_anno,'MM/YYYY')>='{start}' AND to_date(mese_anno,'MM/YYYY')<'{end}'",
            f"DELETE FROM ch4.corrections WHERE account_id='CH4' "
            f"AND data_misura>='{start}' AND data_misura<'{end}'",
            f"DELETE FROM ch4.forecast_periods WHERE account_id='CH4' "
            f"AND forecast_date>='{start}' AND forecast_date<'{end}'",
        ]:
            run(ssh, f"docker exec sii-db-1 psql -U sii -d sii -t -c \"{extra_q}\"", 120)

    print(f"\nCH4 total measurements deleted: {total_ch4:,}")

    ssh.close(); ssh = connect()
    free_before_ch4_vac = disk_free_gb(ssh)
    print(f"Disk free before VACUUM: {free_before_ch4_vac:.1f} GB")
    print("Starting VACUUM FULL ch4.measurements...")
    ssh = vacuum_full(ssh, "ch4")
    ssh.close(); ssh = connect()
    free_after_ch4 = disk_free_gb(ssh)
    print(f"Freed: {free_after_ch4 - free_before_ch4_vac:+.1f} GB  |  disk free: {free_after_ch4:.1f} GB")

    # ── POWER_IT: no new rows to delete, but vacuum for dead-tuple space ───────
    print()
    print("=" * 62)
    print("POWER_IT — VACUUM FULL (reclaim dead tuples from previous retention)")
    print("=" * 62)
    ssh.close(); ssh = connect()
    free_before_pit = disk_free_gb(ssh)
    print(f"Disk free before VACUUM: {free_before_pit:.1f} GB")
    ssh = vacuum_full(ssh, "power_it")
    ssh.close(); ssh = connect()
    free_after_pit = disk_free_gb(ssh)
    print(f"Freed: {free_after_pit - free_before_pit:+.1f} GB  |  disk free: {free_after_pit:.1f} GB")

    # ── Final report ───────────────────────────────────────────────────────────
    print()
    print("=" * 62)
    print("DONE")
    ssh.close(); ssh = connect()
    db = run(ssh,
        'docker exec sii-db-1 psql -U sii -d sii -t -c '
        '"SELECT pg_size_pretty(pg_database_size(\'sii\'));"', 15)
    top = run(ssh,
        'docker exec sii-db-1 psql -U sii -d sii -t -c '
        '"SELECT schemaname, pg_size_pretty(SUM(pg_total_relation_size'
        "(schemaname||'.'||tablename))::bigint) "
        "FROM pg_tables WHERE schemaname NOT IN ('pg_catalog','information_schema') "
        'GROUP BY schemaname ORDER BY 2 DESC LIMIT 12;"', 20)
    free_final = disk_free_gb(ssh)
    print(f"Final disk free: {free_final:.1f} GB")
    print(f"DB size:         {db.strip()}")
    print(f"\nTop schemas:\n{top}")
    ssh.close()


if __name__ == "__main__":
    main()
