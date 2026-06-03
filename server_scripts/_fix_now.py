"""Hot-patch retention.py, restart API, re-trigger purge, poll results."""
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

    print("\n=== GIT PULL ===")
    out = run(ssh, "cd /opt/sii && git pull origin main 2>&1", 20)
    print(out)
    log = run(ssh, "cd /opt/sii && git log --oneline -3", 10)
    print(log)

    grep = run(ssh, "grep -n 'cast.*rows.*jsonb\\|AS jsonb' /opt/sii/backend/db/retention.py", 10)
    print(f"\nFix on disk: {grep if grep else 'NOT FOUND — cannot continue'}")
    if not grep:
        ssh.close(); return

    print("\n=== HOT-PATCH ===")
    cp1 = run(ssh, "docker cp /opt/sii/backend/db/retention.py sii-api-1:/app/backend/db/retention.py 2>&1", 10)
    print(f"  retention.py cp: {cp1 if cp1 else 'ok'}")
    run(ssh, "docker restart sii-api-1 2>&1", 30)
    print("  Restarted. Waiting 12s...")
    time.sleep(12)

    health = run(ssh, "curl -s https://localhost/api/health --insecure", 10)
    try:
        h = json.loads(health)
        print(f"  API: {h.get('status')} | DB: {h.get('database',{}).get('status')}")
    except Exception:
        print(f"  Health: {health[:80]}")

    token_raw = run(ssh,
        'curl -s -X POST https://localhost/api/auth/token --insecure '
        '-H "Content-Type: application/json" '
        '-d \'{"username":"admin","password":"Din@mo5055Trade"}\'', 10
    )
    token = json.loads(token_raw).get('access_token', '') if token_raw else ''
    print(f"  Auth: {'OK' if token else 'FAILED'}")
    if not token:
        ssh.close(); return

    disk = run(ssh, "df -h / | tail -1", 10)
    db = run(ssh, "docker exec sii-db-1 psql -U sii -d sii -t -c \"SELECT pg_size_pretty(pg_database_size('sii'));\"", 15)
    print(f"\nBefore — disk: {disk}")
    print(f"Before — DB:   {db.strip()}")

    print("\n=== TRIGGERING RETENTION PURGE ===")
    resp = run(ssh,
        f'curl -s -X POST https://localhost/api/admin/retention/run --insecure '
        f'-H "Authorization: Bearer {token}"', 15
    )
    print(f"Response: {resp}")

    print("\nPolling archive_catalog (up to 10 min)...")
    t0 = time.time()

    while True:
        time.sleep(30)
        try:
            ssh.close()
        except Exception:
            pass
        ssh = connect()
        token_raw = run(ssh,
            'curl -s -X POST https://localhost/api/auth/token --insecure '
            '-H "Content-Type: application/json" '
            '-d \'{"username":"admin","password":"Din@mo5055Trade"}\'', 10
        )
        token = json.loads(token_raw).get('access_token', '') if token_raw else token

        catalog = run(ssh,
            'docker exec sii-db-1 psql -U sii -d sii -t -c '
            '"SELECT account_id, cutoff_date, rows_deleted '
            'FROM public.archive_catalog ORDER BY account_id;"', 15
        )
        rows = [l for l in catalog.splitlines() if '|' in l]
        elapsed = int(time.time() - t0)
        print(f"  [{elapsed}s] {len(rows)}/12 accounts logged", flush=True)

        if len(rows) >= 12:
            print("\n=== RETENTION COMPLETE ===")
            total = 0
            for line in rows:
                parts = [p.strip() for p in line.split('|')]
                if len(parts) >= 3:
                    try:
                        rd = json.loads(parts[2]) if parts[2] else {}
                        n = sum(rd.values()) if isinstance(rd, dict) else 0
                        total += n
                        print(f"  {parts[0]:20s}  cutoff={parts[1]}  deleted={n:,}")
                    except Exception:
                        print(f"  {line.strip()}")
            print(f"\nTotal rows deleted: {total:,}")
            break

        if elapsed > 600:
            print(f"Timeout. Current catalog ({len(rows)} entries):")
            print(catalog)
            break

    disk2 = run(ssh, "df -h / | tail -1", 10)
    db2 = run(ssh, "docker exec sii-db-1 psql -U sii -d sii -t -c \"SELECT pg_size_pretty(pg_database_size('sii'));\"", 15)
    print(f"\nAfter  — disk: {disk2}")
    print(f"After  — DB:   {db2.strip()}")

    ssh.close()
    print("\nDone.")


if __name__ == "__main__":
    main()
