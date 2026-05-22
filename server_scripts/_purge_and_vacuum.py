"""Delete Jun–Dec 2025 data from all schemas + VACUUM FULL measurements, smallest schema first.

Strategy:
  1. Order schemas by current size ASC (smallest first).
  2. For each schema: DELETE data_misura in [2025-06-01, 2026-01-01), then immediately
     VACUUM FULL measurements before autovacuum can reset the dead-tuple stats.
  3. Each VACUUM FULL returns freed space, enabling the next larger schema.

Expected: 220 GB → ~135 GB used after all schemas complete (~2–3 hours total).
"""
import os, sys, time
import paramiko

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
HOST = "104.248.32.23"; USER = "root"
PW = os.environ.get('SII_SSH_PWD', '')

DELETE_START = "2025-06-01"   # inclusive: delete from this date
DELETE_END   = "2026-01-01"   # exclusive: up to (not including) this date


def connect():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, username=USER, password=PW, timeout=15)
    ssh.get_transport().set_keepalive(30)
    return ssh


def run(ssh, cmd, timeout=30):
    _, o, e = ssh.exec_command(cmd, timeout=timeout)
    out = o.read().decode('utf-8', errors='replace').strip()
    err = e.read().decode('utf-8', errors='replace').strip()
    if err and not any(w in err.lower() for w in ('warning', 'notice', 'deprecated', 'hint')):
        print(f"  stderr: {err[:300]}")
    return out


def disk_free_gb(ssh):
    out = run(ssh, "df / | tail -1", 10)
    parts = out.split()
    return int(parts[3]) / 1_048_576


def vacuum_running(ssh):
    """Returns (running: bool, seconds_elapsed: int). Matches only active VACUUM commands."""
    row = run(ssh, r"""docker exec sii-db-1 psql -U sii -d sii -t -c \
      "SELECT extract(epoch FROM (now()-query_start))::int \
       FROM pg_stat_activity WHERE query ~ '^VACUUM' AND state='active' LIMIT 1;" """, 15)
    val = row.strip()
    return (True, int(val)) if (val and val.isdigit()) else (False, 0)


def get_schemas_by_size(ssh):
    """Returns [(schema_name, total_bytes)] ordered ASC by size, skipping system schemas."""
    q = ("SELECT schemaname, SUM(pg_total_relation_size(schemaname||'.'||tablename))::bigint "
         "FROM pg_tables "
         "WHERE schemaname NOT IN ('pg_catalog','information_schema','public') "
         "GROUP BY schemaname ORDER BY 2 ASC")
    out = run(ssh, f'docker exec sii-db-1 psql -U sii -d sii -t -c "{q}"', 20)
    rows = []
    for line in out.splitlines():
        parts = [p.strip() for p in line.split('|')]
        if len(parts) >= 2 and parts[1].isdigit():
            rows.append((parts[0], int(parts[1])))
    return rows


def delete_schema_data(ssh, schema, account_id):
    """Delete Jun–Dec 2025 data from all measurement tables for this schema.

    Returns total rows deleted from the two main measurements tables.
    """
    total = 0

    for table in ("measurements", "measurements_secondary"):
        q = (f"DELETE FROM {schema}.{table} "
             f"WHERE account_id = '{account_id}' "
             f"AND data_misura >= '{DELETE_START}' AND data_misura < '{DELETE_END}'")
        out = run(ssh, f'docker exec sii-db-1 psql -U sii -d sii -t -c "{q}"', 180)
        # psql returns "DELETE N" — extract the number
        n = 0
        for tok in out.split():
            if tok.isdigit():
                n = int(tok)
                break
        total += n
        print(f"    {table}: {n:,} rows deleted")

    # Totalizer — data_misura nullable, fall back to mese_anno parse
    q = (f"DELETE FROM {schema}.measurements_totalizer "
         f"WHERE account_id = '{account_id}' "
         f"AND ((data_misura >= '{DELETE_START}' AND data_misura < '{DELETE_END}') "
         f"OR (data_misura IS NULL AND mese_anno IS NOT NULL "
         f"    AND to_date(mese_anno,'MM/YYYY') >= '{DELETE_START}' "
         f"    AND to_date(mese_anno,'MM/YYYY') < '{DELETE_END}'))")
    out = run(ssh, f'docker exec sii-db-1 psql -U sii -d sii -t -c "{q}"', 60)
    print(f"    measurements_totalizer: {out.strip()}")

    # Files log — keyed by mese_anno
    q = (f"DELETE FROM {schema}.files "
         f"WHERE account_id = '{account_id}' AND mese_anno IS NOT NULL "
         f"AND to_date(mese_anno,'MM/YYYY') >= '{DELETE_START}' "
         f"AND to_date(mese_anno,'MM/YYYY') < '{DELETE_END}'")
    run(ssh, f'docker exec sii-db-1 psql -U sii -d sii -t -c "{q}"', 60)

    # Corrections
    q = (f"DELETE FROM {schema}.corrections "
         f"WHERE account_id = '{account_id}' "
         f"AND data_misura >= '{DELETE_START}' AND data_misura < '{DELETE_END}'")
    run(ssh, f'docker exec sii-db-1 psql -U sii -d sii -t -c "{q}"', 60)

    # Forecast periods — keyed by forecast_date
    q = (f"DELETE FROM {schema}.forecast_periods "
         f"WHERE account_id = '{account_id}' "
         f"AND forecast_date >= '{DELETE_START}' AND forecast_date < '{DELETE_END}'")
    run(ssh, f'docker exec sii-db-1 psql -U sii -d sii -t -c "{q}"', 60)

    return total


def vacuum_full_measurements(ssh, schema):
    """Launch detached VACUUM FULL on schema.measurements and poll until done.

    Returns (updated_ssh, elapsed_seconds).
    Uses docker exec -d so VACUUM survives SSH reconnects.
    """
    running, secs = vacuum_running(ssh)
    if running:
        print(f"    VACUUM already running ({secs}s). Waiting...")
    else:
        run(ssh,
            f"docker exec -d sii-db-1 psql -U sii -d sii -c "
            f"'VACUUM FULL {schema}.measurements;'", 15)
        time.sleep(5)
        print(f"    VACUUM FULL launched (background). Polling every 60s...")

    t0 = time.time()
    while True:
        time.sleep(60)
        try:
            ssh.close()
        except Exception:
            pass
        try:
            ssh = connect()
        except Exception as exc:
            print(f"    [reconnect failed: {exc}] retrying in 30s...")
            time.sleep(30)
            continue

        running, secs = vacuum_running(ssh)
        elapsed = int(time.time() - t0)
        if not running:
            print(f"    VACUUM FULL done  [{elapsed}s]")
            return ssh, elapsed
        print(f"    still vacuuming... {secs}s in-DB / {elapsed}s total", flush=True)


def main():
    if not PW:
        print("ERROR: SII_SSH_PWD not set"); return

    ssh = connect()
    free_before = disk_free_gb(ssh)
    print(f"Connected  |  disk free: {free_before:.1f} GB")
    print(f"Will delete data_misura in [{DELETE_START}, {DELETE_END})\n")

    schemas = get_schemas_by_size(ssh)
    print("Schemas ordered smallest → largest:")
    for s, sz in schemas:
        print(f"  {s:30s}  {sz/1_073_741_824:.2f} GB")
    print()

    # Build schema → account_id mapping from public.accounts
    acct_out = run(ssh,
        'docker exec sii-db-1 psql -U sii -d sii -t -c '
        '"SELECT account_id, schema_name FROM public.accounts WHERE active=true"', 15)
    schema_to_acct: dict[str, str] = {}
    for line in acct_out.splitlines():
        parts = [p.strip() for p in line.split('|')]
        if len(parts) >= 2 and parts[0] and parts[1]:
            schema_to_acct[parts[1]] = parts[0]

    total_freed = 0.0

    for schema, sz_bytes in schemas:
        account_id = schema_to_acct.get(schema, schema.upper())
        sz_gb = sz_bytes / 1_073_741_824

        ssh.close(); ssh = connect()
        free_gb = disk_free_gb(ssh)

        print(f"\n{'='*62}")
        print(f"Schema: {schema}  ({sz_gb:.2f} GB total)  |  disk free: {free_gb:.1f} GB")
        print(f"Account ID: {account_id}")

        # ── DELETE ─────────────────────────────────────────────────────────────
        print(f"  Deleting Jun–Dec 2025...")
        deleted = delete_schema_data(ssh, schema, account_id)
        print(f"  measurements rows deleted: {deleted:,}")

        if deleted == 0:
            print(f"  No measurements rows deleted — skipping VACUUM FULL for this schema")
            continue

        # ── VACUUM FULL ────────────────────────────────────────────────────────
        print(f"  Starting VACUUM FULL {schema}.measurements...")
        ssh, elapsed = vacuum_full_measurements(ssh, schema)

        ssh.close(); ssh = connect()
        free_after = disk_free_gb(ssh)
        freed = free_after - free_gb
        total_freed += max(freed, 0)
        print(f"  Freed: {freed:+.1f} GB  |  disk free now: {free_after:.1f} GB")

    # ── Final report ───────────────────────────────────────────────────────────
    print(f"\n{'='*62}")
    print("COMPLETE")
    ssh.close(); ssh = connect()
    free_final = disk_free_gb(ssh)
    db = run(ssh,
        'docker exec sii-db-1 psql -U sii -d sii -t -c '
        '"SELECT pg_size_pretty(pg_database_size(\'sii\'));"', 15)
    top = run(ssh,
        'docker exec sii-db-1 psql -U sii -d sii -t -c '
        '"SELECT schemaname, pg_size_pretty(SUM(pg_total_relation_size'
        "(schemaname||'.'||tablename))::bigint) "
        "FROM pg_tables WHERE schemaname NOT IN ('pg_catalog','information_schema') "
        'GROUP BY schemaname ORDER BY 2 DESC LIMIT 10;"', 20)
    print(f"Total freed:   ~{total_freed:.1f} GB")
    print(f"Final free:    {free_final:.1f} GB")
    print(f"DB size:       {db.strip()}")
    print(f"\nTop schemas:\n{top}")
    ssh.close()
    print("\nDone.")


if __name__ == "__main__":
    main()
