"""
Progressive VACUUM FULL — smallest-first, escalating as space frees up.

Strategy:
  1. Find all tables with dead tuples, ordered by size ASC.
  2. For each: if estimated live-data size <= available free space, run VACUUM FULL.
  3. After each success, re-check free space and move to next larger table.
  4. Repeat passes until disk < TARGET_PCT or no more tables fit.
"""
import os, sys, time, paramiko

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
HOST = "104.248.32.23"; USER = "root"
PW = os.environ.get('SII_SSH_PWD', '')

SAFETY_MARGIN_GB = 1.5   # always keep this much free
MIN_DEAD_TUPLES  = 1_000 # skip trivially small tables
TARGET_PCT       = 75    # stop when disk usage drops below this %


def connect():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, username=USER, password=PW, timeout=15)
    ssh.get_transport().set_keepalive(20)
    return ssh


def run(ssh, cmd, t=30):
    _, o, e = ssh.exec_command(cmd, timeout=t)
    return o.read().decode('utf-8', errors='replace').strip()


def disk_stats(ssh):
    out = run(ssh, "df / | tail -1", 10)
    parts = out.split()
    total_kb = int(parts[1])
    used_kb  = int(parts[2])
    free_kb  = int(parts[3])
    pct      = int(parts[4].replace('%', ''))
    return pct, free_kb / 1_048_576  # pct, free_gb


def get_dead_tables(ssh):
    """Tables with dead tuples, ordered smallest first."""
    q = (
        "SELECT schemaname, tablename, "
        "pg_total_relation_size(schemaname||'.'||tablename) AS sz, "
        "n_dead_tup, n_live_tup "
        "FROM pg_stat_user_tables "
        f"WHERE n_dead_tup > {MIN_DEAD_TUPLES} "
        "AND schemaname NOT IN ('pg_catalog','information_schema','public') "
        "ORDER BY sz ASC"
    )
    out = run(ssh, f'docker exec sii-db-1 psql -U sii -d sii -t -c "{q}"', 20)
    rows = []
    for line in out.splitlines():
        parts = [p.strip() for p in line.split('|')]
        if len(parts) >= 5:
            try:
                rows.append((
                    parts[0], parts[1],
                    int(parts[2]), int(parts[3]), int(parts[4])
                ))
            except ValueError:
                pass
    return rows  # [(schema, table, size_bytes, dead_tup, live_tup)]


def fmt_size(b):
    if b >= 1_073_741_824:
        return f"{b / 1_073_741_824:.2f} GB"
    return f"{b / 1_048_576:.0f} MB"


def vacuum_table(ssh, schema, table):
    t0 = time.time()
    out = run(ssh,
        f'docker exec sii-db-1 psql -U sii -d sii -c '
        f'"VACUUM FULL {schema}.{table};" 2>&1',
        t=1200
    )
    elapsed = int(time.time() - t0)
    success = 'VACUUM' in out or not out  # psql prints 'VACUUM' on success; empty also ok
    return elapsed, success, out[:200] if not success else ''


def main():
    if not PW:
        print("ERROR: SII_SSH_PWD not set"); return

    ssh = connect()
    pct, free_gb = disk_stats(ssh)
    print(f"Connected  |  Disk: {pct}% used, {free_gb:.1f} GB free")
    print(f"Target: < {TARGET_PCT}%\n")

    grand_total_freed = 0.0
    grand_vacuumed = 0
    pass_num = 0

    while True:
        pass_num += 1
        ssh.close(); ssh = connect()
        pct, free_gb = disk_stats(ssh)

        print(f"\n{'='*64}")
        print(f"PASS {pass_num}  |  {pct}% used, {free_gb:.1f} GB free")
        print(f"{'='*64}")

        if pct <= TARGET_PCT:
            print(f"Target reached ({pct}% <= {TARGET_PCT}%). Stopping.")
            break

        tables = get_dead_tables(ssh)
        if not tables:
            print("No tables with significant dead tuples. Nothing to do.")
            break

        print(f"Tables with dead tuples: {len(tables)}")
        for s, t, sz, dead, live in tables[:15]:
            dpct = int(dead * 100 / max(dead + live, 1))
            print(f"  {s}.{t:35s} {fmt_size(sz):10s}  dead={dead:>10,} ({dpct}%)")

        did_any_this_pass = False

        for s, t, sz, dead, live in tables:
            ssh.close(); ssh = connect()
            pct, free_gb = disk_stats(ssh)

            if pct <= TARGET_PCT:
                print(f"\nTarget reached mid-pass ({pct}%). Stopping.")
                break

            total = dead + live
            dead_frac = dead / max(total, 1)
            live_size_gb = (sz / 1_073_741_824) * (1 - dead_frac)
            needed_gb = live_size_gb + SAFETY_MARGIN_GB

            dpct = int(dead_frac * 100)
            print(f"\n  [{pct}% disk, {free_gb:.1f} GB free]  "
                  f"{s}.{t}  ({fmt_size(sz)}, {dpct}% dead)")

            if free_gb < needed_gb:
                print(f"    SKIP — needs ~{needed_gb:.1f} GB, only {free_gb:.1f} GB free")
                continue

            print(f"    Running VACUUM FULL (~{live_size_gb:.1f} GB live data)...")
            elapsed, ok, err = vacuum_table(ssh, s, t)

            ssh.close(); ssh = connect()
            pct_after, free_after = disk_stats(ssh)
            freed = free_after - free_gb

            if ok:
                grand_vacuumed += 1
                grand_total_freed += max(freed, 0)
                did_any_this_pass = True
                print(f"    OK  {elapsed}s  freed: {freed:+.2f} GB  disk: {pct_after}%")
            else:
                print(f"    FAILED  {elapsed}s  {err}")

        if not did_any_this_pass:
            print("\nNo tables vacuumed this pass — all remaining are too large for current free space.")
            print(f"Current free: {free_gb:.1f} GB. Cannot proceed further without more disk.")
            break

    # ── Final state ────────────────────────────────────────────────────────────
    print(f"\n{'='*64}")
    print("FINAL STATE")
    print(f"{'='*64}")
    ssh.close(); ssh = connect()
    pct, free_gb = disk_stats(ssh)
    db = run(ssh, "docker exec sii-db-1 psql -U sii -d sii -t -c "
                  "\"SELECT pg_size_pretty(pg_database_size('sii'));\"", 15)
    top = run(ssh,
        'docker exec sii-db-1 psql -U sii -d sii -t -c '
        '"SELECT schemaname, pg_size_pretty(SUM(pg_total_relation_size'
        "(schemaname||'.'||tablename))::bigint) "
        "FROM pg_tables WHERE schemaname NOT IN ('pg_catalog','information_schema') "
        "GROUP BY schemaname ORDER BY 2 DESC LIMIT 8;\"", 20)
    print(f"Tables vacuumed : {grand_vacuumed}")
    print(f"Total freed     : ~{grand_total_freed:.1f} GB")
    print(f"Disk            : {pct}% used, {free_gb:.1f} GB free")
    print(f"DB size         : {db.strip()}")
    print(f"\nTop schemas:\n{top}")
    ssh.close()
    print("\nDone.")


if __name__ == "__main__":
    main()
