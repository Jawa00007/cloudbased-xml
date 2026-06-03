"""Trigger retention purge and poll until all accounts processed, then VACUUM ANALYZE."""
import os, sys, json, time, paramiko

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
HOST = "104.248.32.23"; USER = "root"
PW = os.environ.get('SII_SSH_PWD', '')


def connect():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, username=USER, password=PW, timeout=15)
    ssh.get_transport().set_keepalive(20)
    return ssh


def run(ssh, cmd, t=20):
    _, o, e = ssh.exec_command(cmd, timeout=t)
    return o.read().decode('utf-8', errors='replace').strip()


def main():
    if not PW:
        print("ERROR: SII_SSH_PWD not set"); return

    ssh = connect()
    print("Connected")

    # ── Get auth token ─────────────────────────────────────────────────────
    token_raw = run(ssh,
        'curl -s -X POST https://localhost/api/auth/token --insecure '
        '-H "Content-Type: application/json" '
        '-d \'{"username":"admin","password":"Din@mo5055Trade"}\'', 15
    )
    token = json.loads(token_raw).get('access_token', '')
    if not token:
        print("ERROR: could not get auth token"); return
    print("Auth OK")

    # ── Before state ───────────────────────────────────────────────────────
    disk_before = run(ssh, "df -h / | tail -1", 10)
    db_before = run(ssh, "docker exec sii-db-1 psql -U sii -d sii -t -c \"SELECT pg_size_pretty(pg_database_size('sii'));\"", 15)
    print(f"\nBefore — disk:  {disk_before}")
    print(f"Before — DB:    {db_before.strip()}")

    # ── Trigger retention purge ────────────────────────────────────────────
    print("\nTriggering POST /admin/retention/run ...")
    resp = run(ssh,
        f'curl -s -X POST https://localhost/api/admin/retention/run --insecure '
        f'-H "Authorization: Bearer {token}"', 15
    )
    print(f"Response: {resp}")

    # ── Poll retention log until all 12 accounts have new entries ─────────
    print("\nPolling retention log (up to 30 min)...")
    t0 = time.time()

    while True:
        time.sleep(30)
        try:
            ssh.close()
        except Exception:
            pass
        try:
            ssh = connect()
        except Exception as e:
            print(f"  [reconnect failed: {e}] retrying...")
            time.sleep(30)
            continue

        token_raw = run(ssh,
            'curl -s -X POST https://localhost/api/auth/token --insecure '
            '-H "Content-Type: application/json" '
            '-d \'{"username":"admin","password":"Din@mo5055Trade"}\'', 10
        )
        token = json.loads(token_raw).get('access_token', '') if token_raw else token

        log_raw = run(ssh,
            f'curl -s -H "Authorization: Bearer {token}" '
            'https://localhost/api/admin/retention/log --insecure', 15
        )
        try:
            log = json.loads(log_raw)
        except Exception:
            print(f"  Could not parse log: {log_raw[:100]}")
            continue

        elapsed = int(time.time() - t0)
        recent = [e for e in log if e.get('rows_deleted')]
        print(f"  [{elapsed}s] {len(recent)} accounts with retention entries")

        if len(recent) >= 12:
            print(f"\nAll 12 accounts processed!")
            total_deleted = 0
            for entry in sorted(recent, key=lambda x: x.get('account_id', ''))[:12]:
                rows = entry.get('rows_deleted', {})
                total = sum(rows.values()) if isinstance(rows, dict) else 0
                total_deleted += total
                print(f"  {entry['account_id']:20s}  cutoff={entry['cutoff_date']}  rows={total:,}")
            print(f"\nTotal rows deleted: {total_deleted:,}")
            break

        if elapsed > 1800:
            print("Timeout after 30 min — check log manually")
            break

    # ── VACUUM ANALYZE to mark freed pages reusable ───────────────────────
    print("\nRunning VACUUM ANALYZE (background — marks freed pages reusable)...")
    run(ssh, "docker exec -d sii-db-1 psql -U sii -d sii -c 'VACUUM ANALYZE;'", 15)
    print("Started. Waiting 60s for initial cleanup...")
    time.sleep(60)

    # ── After state ────────────────────────────────────────────────────────
    disk_after = run(ssh, "df -h / | tail -1", 10)
    db_after = run(ssh, "docker exec sii-db-1 psql -U sii -d sii -t -c \"SELECT pg_size_pretty(pg_database_size('sii'));\"", 15)
    print(f"\nAfter  — disk:  {disk_after}")
    print(f"After  — DB:    {db_after.strip()}")
    print("\nNote: VACUUM ANALYZE runs in background. Run 'df -h /' again in 10 min to see full effect.")
    print("To return OS space, run VACUUM FULL — but that needs ~30 min and free disk >= table size.")

    ssh.close()
    print("\nDone.")


if __name__ == "__main__":
    main()
