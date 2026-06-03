"""VACUUM FULL ch4.measurements — the one table that failed due to disk full."""
import sys, os, time
import paramiko

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
HOST = "104.248.32.23"; USER = "root"
PW   = os.environ.get('SII_SSH_PWD', '')


def connect():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, username=USER, password=PW, timeout=15)
    ssh.get_transport().set_keepalive(20)
    return ssh


def run(ssh, cmd, timeout=30):
    _, o, e = ssh.exec_command(cmd, timeout=timeout)
    out = o.read().decode('utf-8', errors='replace').strip()
    err = e.read().decode('utf-8', errors='replace').strip()
    if err and not any(w in err.lower() for w in ('warning', 'notice', 'deprecated', 'hint')):
        print(f"  stderr: {err[:300]}")
    return out


def vacuum_running(ssh):
    """Returns (bool running, int seconds_elapsed). Matches only actual VACUUM commands."""
    # Use ~ regex so the pattern doesn't match this SELECT itself
    row = run(ssh, r"""docker exec sii-db-1 psql -U sii -d sii -t -c \
      "SELECT extract(epoch FROM (now()-query_start))::int \
       FROM pg_stat_activity \
       WHERE query ~ '^VACUUM' AND state='active' LIMIT 1;" """, timeout=15)
    val = row.strip()
    if val and val.isdigit():
        return True, int(val)
    return False, 0


def main():
    if not PW:
        print("ERROR: SII_SSH_PWD not set"); return

    ssh = connect()
    print("Connected")

    # ── Check / print current state ───────────────────────────────────────────
    disk = run(ssh, "df -h / | tail -1", timeout=10)
    size = run(ssh, """docker exec sii-db-1 psql -U sii -d sii -t -c \
      "SELECT pg_size_pretty(pg_total_relation_size('ch4.measurements'));" """, timeout=10)
    db   = run(ssh, """docker exec sii-db-1 psql -U sii -d sii -t -c \
      "SELECT pg_size_pretty(pg_database_size('sii'));" """, timeout=10)
    print(f"Disk before:           {disk}")
    print(f"ch4.measurements size: {size.strip()}")
    print(f"DB total before:       {db.strip()}")

    # ── Start VACUUM if not already running ───────────────────────────────────
    running, secs = vacuum_running(ssh)
    if running:
        print(f"VACUUM already running ({secs}s elapsed). Waiting...")
    else:
        print("\nStarting VACUUM FULL ch4.measurements (background inside container)...")
        # docker exec -d: detached — psql runs in container, returns immediately.
        # The VACUUM survives even if our SSH session drops.
        run(ssh, "docker exec -d sii-db-1 psql -U sii -d sii -c 'VACUUM FULL ch4.measurements;'", timeout=15)
        time.sleep(5)
        print("  Started. Polling until done...")

    # ── Poll until VACUUM completes (reconnect SSH each iteration) ────────────
    t0 = time.time()
    while True:
        time.sleep(60)
        try:
            # Fresh SSH connection each poll — avoids session-timeout errors
            ssh.close()
        except Exception:
            pass
        try:
            ssh = connect()
        except Exception as e:
            print(f"  [reconnect failed: {e}] retrying in 30s...")
            time.sleep(30)
            continue

        running, secs = vacuum_running(ssh)
        elapsed_total = int(time.time() - t0)
        if not running:
            print(f"  VACUUM finished! (total wait: {elapsed_total}s)")
            break
        print(f"  Still running... {secs}s in DB / {elapsed_total}s total", flush=True)

    # ── Final state ───────────────────────────────────────────────────────────
    disk2 = run(ssh, "df -h / | tail -1", timeout=10)
    size2 = run(ssh, """docker exec sii-db-1 psql -U sii -d sii -t -c \
      "SELECT pg_size_pretty(pg_total_relation_size('ch4.measurements'));" """, timeout=10)
    db2   = run(ssh, """docker exec sii-db-1 psql -U sii -d sii -t -c \
      "SELECT pg_size_pretty(pg_database_size('sii'));" """, timeout=10)
    print(f"\nDisk after:            {disk2}")
    print(f"ch4.measurements size: {size2.strip()}")
    print(f"DB total after:        {db2.strip()}")

    ssh.close()
    print("\nDone.")


if __name__ == "__main__":
    main()
