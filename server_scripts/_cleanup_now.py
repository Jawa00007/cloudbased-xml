"""
Disk audit + one-time data retention purge.

Steps:
  1. Before-state: disk, Docker, DB sizes
  2. Trigger POST /admin/retention/run (cutoff = 2025-05-01)
  3. Poll retention log until all accounts appear (up to 15 min)
  4. docker builder prune + docker image prune
  5. VACUUM ANALYZE
  6. After-state: disk comparison
"""
import sys, json, time, os
import paramiko
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

HOST = "104.248.32.23"
USER = "root"

def run(ssh, cmd, timeout=60):
    _, o, e = ssh.exec_command(cmd, timeout=timeout)
    out = o.read().decode('utf-8', errors='replace').strip()
    err = e.read().decode('utf-8', errors='replace').strip()
    if err and 'warning' not in err.lower() and 'notice' not in err.lower():
        print(f"  STDERR: {err[:200]}")
    return out

def fire(ssh, cmd):
    ssh.exec_command(cmd)

def get_token(ssh):
    resp = run(ssh, """curl -sk -X POST https://localhost/api/auth/token \
      -H 'Content-Type: application/json' \
      -d '{"username":"admin","password":"Din@mo5055Trade"}' """)
    try:
        return json.loads(resp).get('access_token', '')
    except Exception:
        print(f"Token error: {resp[:100]}")
        return ''

def get_disk_pct(ssh):
    out = run(ssh, "df / --output=pcent | tail -1 | tr -d ' %'")
    try:
        return int(out)
    except Exception:
        return -1

def main():
    pw = os.environ.get('SII_SSH_PWD', '')
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, username=USER, password=pw, timeout=15)
    print("Connected to", HOST)

    # ── BEFORE STATE ──────────────────────────────────────────────────────
    print("\n" + "="*60)
    print("DISK AUDIT — BEFORE")
    print("="*60)

    disk = run(ssh, "df -h /")
    print(disk)

    print("\n--- Top space consumers ---")
    # Use df for docker volumes (du on /var/lib/docker is too slow); du only for known-small dirs
    print(run(ssh, "du -sh /opt/sii/data/ 2>/dev/null || echo 'n/a'", timeout=60))
    print(run(ssh, "du -sh /opt/sii/logs/ /tmp/ 2>/dev/null", timeout=30))

    print("\n--- Docker space ---")
    ds = run(ssh, "docker system df", timeout=30)
    print(ds)

    print("\n--- PostgreSQL DB size ---")
    db_size = run(ssh, """docker exec sii-db-1 psql -U sii -d sii -t -c \
      "SELECT pg_size_pretty(pg_database_size('sii'));" """, timeout=20)
    print("Total DB:", db_size.strip())

    print("\n--- Top 10 schemas by size ---")
    schemas = run(ssh, """docker exec sii-db-1 psql -U sii -d sii -t -c \
      "SELECT schemaname, pg_size_pretty(sum(pg_total_relation_size(schemaname||'.'||tablename))::bigint) AS sz
       FROM information_schema.tables
       WHERE schemaname NOT IN ('pg_catalog','information_schema')
       GROUP BY schemaname
       ORDER BY sum(pg_total_relation_size(schemaname||'.'||tablename)) DESC
       LIMIT 10;" """, timeout=30)
    print(schemas)

    print("\n--- Date range of data in BAT (sample) ---")
    bat_range = run(ssh, """docker exec sii-db-1 psql -U sii -d sii -t -c \
      "SELECT MIN(data_misura), MAX(data_misura), COUNT(*) FROM bat.measurements;" """, timeout=20)
    print("BAT measurements:", bat_range.strip())

    disk_before_pct = get_disk_pct(ssh)

    # ── TRIGGER RETENTION PURGE ───────────────────────────────────────────
    print("\n" + "="*60)
    print("TRIGGERING RETENTION PURGE")
    print("="*60)

    token = get_token(ssh)
    if not token:
        print("No token — aborting")
        ssh.close(); return

    trig = run(ssh, f"""curl -sk -X POST https://localhost/api/admin/retention/run \
      -H 'Authorization: Bearer {token}' \
      -H 'Content-Type: application/json' """, timeout=15)
    print("Trigger response:", trig)

    # ── POLL RETENTION LOG ────────────────────────────────────────────────
    print("\nPolling retention log (up to 15 min)...")
    start = time.time()
    accounts_done = set()

    while True:
        elapsed = int(time.time() - start)
        log_resp = run(ssh, f"""curl -sk https://localhost/api/admin/retention/log \
          -H 'Authorization: Bearer {token}' """, timeout=20)
        try:
            entries = json.loads(log_resp)
            accounts_done = {e['account_id'] for e in entries}
            total_deleted = sum(
                sum((e.get('rows_deleted') or {}).values())
                for e in entries
            )
            print(f"[{elapsed}s] accounts logged: {len(accounts_done)}, total rows deleted: {total_deleted:,}")
            if len(accounts_done) >= 12:
                print("All accounts purged.")
                break
        except Exception as ex:
            print(f"[{elapsed}s] parse error: {ex} | {log_resp[:100]}")

        if elapsed > 900:
            print("Timeout — purge may still be running in background")
            break
        time.sleep(20)

    # ── PRINT RETENTION DETAILS ───────────────────────────────────────────
    print("\n--- Retention log (latest 12 entries) ---")
    log_resp = run(ssh, f"""curl -sk https://localhost/api/admin/retention/log \
      -H 'Authorization: Bearer {token}' """, timeout=20)
    try:
        entries = json.loads(log_resp)
        for e in entries[:12]:
            rd = e.get('rows_deleted') or {}
            total = sum(rd.values())
            print(f"  {e['account_id']:12s} cutoff={e['cutoff_date']}  rows_deleted={total:>10,}  {rd}")
    except Exception:
        print(log_resp[:500])

    # ── DOCKER CLEANUP ────────────────────────────────────────────────────
    print("\n" + "="*60)
    print("DOCKER CLEANUP")
    print("="*60)

    print("Pruning build cache...")
    bc = run(ssh, "docker builder prune -f", timeout=120)
    print(bc)

    print("Pruning dangling images...")
    ip = run(ssh, "docker image prune -f", timeout=60)
    print(ip)

    # ── VACUUM ANALYZE ────────────────────────────────────────────────────
    print("\n--- Running VACUUM ANALYZE (returns pages to OS) ---")
    print("This may take 5-10 minutes for large tables...")
    vac = run(ssh, """docker exec sii-db-1 psql -U sii -d sii -c \
      "VACUUM ANALYZE;" """, timeout=600)
    print(vac)

    # ── AFTER STATE ───────────────────────────────────────────────────────
    print("\n" + "="*60)
    print("DISK AUDIT — AFTER")
    print("="*60)

    disk_after = run(ssh, "df -h /")
    print(disk_after)

    disk_after_pct = get_disk_pct(ssh)
    freed = disk_before_pct - disk_after_pct
    print(f"\nDisk usage: {disk_before_pct}% → {disk_after_pct}%  (freed ~{freed} pct points)")

    print("\n--- DB size after ---")
    db_after = run(ssh, """docker exec sii-db-1 psql -U sii -d sii -t -c \
      "SELECT pg_size_pretty(pg_database_size('sii'));" """, timeout=20)
    print("Total DB after:", db_after.strip())

    print("\n--- BAT measurements min date after purge ---")
    bat_min = run(ssh, """docker exec sii-db-1 psql -U sii -d sii -t -c \
      "SELECT MIN(data_misura), COUNT(*) FROM bat.measurements;" """, timeout=20)
    print("BAT:", bat_min.strip())

    ssh.close()
    print("\nCleanup complete.")

if __name__ == '__main__':
    main()
