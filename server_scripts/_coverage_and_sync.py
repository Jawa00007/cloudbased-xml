"""Audit all 12 accounts for May 2025–May 2026 coverage, then sync missing ones.
Usage: SII_SSH_PWD=xxx py server_scripts/_coverage_and_sync.py
"""
import os, sys, json, time
import paramiko

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
HOST = "104.248.32.23"; USER = "root"
PW = os.environ.get("SII_SSH_PWD", "")


def connect():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, username=USER, password=PW, timeout=15)
    ssh.get_transport().set_keepalive(20)
    return ssh


def run(ssh, cmd, timeout=30):
    _, o, e = ssh.exec_command(cmd, timeout=timeout)
    out = o.read().decode("utf-8", errors="replace").strip()
    err = e.read().decode("utf-8", errors="replace").strip()
    if err and not any(w in err.lower() for w in ("warning", "notice", "deprecated", "hint")):
        print(f"  stderr: {err[:300]}")
    return out


def main():
    if not PW:
        print("ERROR: SII_SSH_PWD not set"); sys.exit(1)

    ssh = connect()
    print("Connected\n")

    # Read API_KEY from server .env
    api_key = run(ssh, "grep '^API_KEY=' /opt/sii/.env | cut -d= -f2-", 10)
    if not api_key:
        print("ERROR: API_KEY not found in /opt/sii/.env"); sys.exit(1)
    print(f"API_KEY found ({len(api_key)} chars)\n")

    # Call coverage endpoint
    raw = run(ssh,
        f'curl -sk -H "X-API-Key: {api_key}" https://localhost/api/sync/coverage',
        30)
    try:
        data = json.loads(raw)
    except Exception as e:
        print(f"ERROR parsing coverage response: {e}\nRaw: {raw[:500]}"); sys.exit(1)

    if not isinstance(data, list) or not data:
        print(f"Unexpected response: {raw[:300]}"); sys.exit(1)

    # Print table
    print(f"{'ACCOUNT':<14} {'MIN':<12} {'MAX':<12} {'ROWS':>12}  MISSING")
    print("-" * 80)
    needs_sync = []
    for row in sorted(data, key=lambda r: r["account_id"]):
        acc = row["account_id"]
        mn = row.get("min_date") or "-"
        mx = row.get("max_date") or "-"
        rows = row.get("row_count_est", 0)
        missing = row.get("months_missing", [])
        miss_str = ", ".join(missing) if missing else "OK"
        flag = " <--" if missing else ""
        print(f"{acc:<14} {mn:<12} {mx:<12} {rows:>12,}  {miss_str}{flag}")
        if missing:
            needs_sync.append(acc)

    print()
    if not needs_sync:
        print("All accounts fully covered — no sync needed.")
        ssh.close()
        return

    print(f"Accounts needing sync: {', '.join(needs_sync)}")
    print("Triggering sync for each...\n")

    started = []
    blocked = []
    for acc in needs_sync:
        out = run(ssh,
            f'curl -sk -X POST -H "X-API-Key: {api_key}" https://localhost/api/sync/{acc}',
            15)
        try:
            resp = json.loads(out)
            msg = resp.get("message", resp.get("detail", str(resp)))
            print(f"  {acc}: {msg}")
            if "already running" in msg.lower():
                blocked.append(acc)
            else:
                started.append(acc)
        except Exception:
            print(f"  {acc}: {out[:200]}")
            blocked.append(acc)
        time.sleep(2)

    pending_sync = blocked

    def poll_until_done(ssh, api_key, label):
        """Poll /sync/status (list[SyncStatusOut]) until no account is running."""
        print(f"\nPolling until {label} finishes...")
        t0 = time.time()
        while True:
            time.sleep(30)
            elapsed = int(time.time() - t0)
            try:
                ssh.close()
                ssh = connect()
            except Exception as e:
                print(f"  [reconnect failed: {e}]")
                time.sleep(10)
                continue

            try:
                status_raw = run(ssh,
                    f'curl -sk -H "X-API-Key: {api_key}" https://localhost/api/sync/status',
                    60)
                items = json.loads(status_raw)
            except Exception as e:
                print(f"  [{elapsed}s] status error: {e}")
                continue

            # items is list[SyncStatusOut]
            any_running = any(item.get("running", False) for item in items)
            # pick the first running item for progress details
            live = next((i for i in items if i.get("running")), items[0] if items else {})
            current = live.get("current_account") or "?"
            triggered = live.get("triggered_by") or "?"
            done = live.get("accounts_done") or 0
            total = live.get("accounts_total") or 0
            ok_total = sum(i.get("files_ok", 0) for i in items)
            err_total = sum(i.get("files_error", 0) for i in items)
            print(f"  [{elapsed}s] running={any_running}  current={current}"
                  f"  by={triggered}  accounts={done}/{total}  ok={ok_total}  err={err_total}")

            if not any_running:
                print(f"  Done in {elapsed}s")
                return ssh, elapsed
            if elapsed > 7200:
                print("  Timeout after 2 hours")
                return ssh, elapsed

    # Wait for current batch (DINAMO + ENJOY) to finish
    ssh, _ = poll_until_done(ssh, api_key, "DINAMO+ENJOY batch")

    # Now trigger remaining accounts one by one
    for acc in pending_sync:
        print(f"\nTriggering sync for {acc}...")
        out = run(ssh,
            f'curl -sk -X POST -H "X-API-Key: {api_key}" https://localhost/api/sync/{acc}',
            15)
        try:
            resp = json.loads(out)
            print(f"  {acc}: {resp.get('status', resp.get('message', resp))}")
        except Exception:
            print(f"  {acc}: {out[:200]}")
        ssh, _ = poll_until_done(ssh, api_key, acc)

    print("\n=== All syncs complete ===")
    ssh.close()


if __name__ == "__main__":
    main()
