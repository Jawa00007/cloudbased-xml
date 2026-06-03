"""Poll archive_catalog every 60s until retention entries appear, then show disk."""
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

    t0 = time.time()
    last_count = -1

    while True:
        try:
            ssh = connect()
        except Exception as e:
            print(f"[{int(time.time()-t0)}s] reconnect failed: {e}")
            time.sleep(30)
            continue

        # Active queries
        active = run(ssh,
            'docker exec sii-db-1 psql -U sii -d sii -t -c '
            '"SELECT left(query,70), extract(epoch FROM (now()-query_start))::int '
            'FROM pg_stat_activity WHERE state=\'active\' '
            'AND query NOT ILIKE \'%pg_stat_activity%\' ORDER BY 2 DESC LIMIT 6;"', 15
        )

        # archive_catalog
        catalog = run(ssh,
            'docker exec sii-db-1 psql -U sii -d sii -t -c '
            '"SELECT account_id, cutoff_date, deleted_at '
            'FROM public.archive_catalog ORDER BY deleted_at DESC LIMIT 15;"', 15
        )
        disk = run(ssh, "df -h / | tail -1", 10)
        db = run(ssh,
            'docker exec sii-db-1 psql -U sii -d sii -t -c '
            '"SELECT pg_size_pretty(pg_database_size(\'sii\'));"', 15
        )

        row_count = len([l for l in catalog.splitlines() if l.strip() and '|' in l])
        elapsed = int(time.time() - t0)

        if row_count != last_count:
            print(f"\n[{elapsed}s] archive_catalog: {row_count} entries")
            if catalog.strip():
                print(catalog)
            print(f"  Disk: {disk}")
            print(f"  DB:   {db.strip()}")
            print(f"  Active queries:")
            for line in active.splitlines():
                if line.strip():
                    print(f"    {line.strip()}")
            last_count = row_count
        else:
            pct = disk.split()[4] if disk else '?'
            print(f"[{elapsed}s] waiting... {row_count} entries, disk={pct}", flush=True)

        ssh.close()

        if row_count >= 12:
            print(f"\nAll 12 accounts done!")
            break
        if elapsed > 2400:
            print("Timeout 40 min — check manually")
            break

        time.sleep(60)


if __name__ == "__main__":
    main()
