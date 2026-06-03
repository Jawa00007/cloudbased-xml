"""Full backlog ingestion: rsync all unprocessed Italian server ZIPs, account by account.
Overcomes the BATCH_SIZE=500 cap in sync_sii.sh — processes 10,000 files per chunk,
ingests them (process+delete), repeats until Italian server count == DB count.
Usage: SII_SSH_PWD=xxx py server_scripts/_full_backfill_sync.py
"""
import os, sys, json, time
import paramiko

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
HOST = "104.248.32.23"; USER = "root"
PW = os.environ.get("SII_SSH_PWD", "")

SSH_OPTS = ("-i /root/.ssh/italian_server -o StrictHostKeyChecking=no "
            "-o ConnectTimeout=30 -o ServerAliveInterval=60 -o BatchMode=yes")
ITAL = "ubuntu@57.131.24.23"
ITAL_BASE = "/home/ubuntu/SII_CLOUD"
LOCAL_DATA = "/opt/sii/data"
CHUNK_SIZE = 10000
MIN_FREE_GB = 5

# Ordered largest backlog first for fastest visible progress
ACCOUNTS = [
    ("ENERGIT",   "energit"),
    ("ONDA",      "onda_piu"),
    ("EGOGREEN",  "egogreen"),
    ("POWERIT",   "power_it"),
    ("CH4",       "ch4"),
    ("ENJOY",     "enjoy_energy"),
    ("SOS",       "sos"),
    ("ROYAL",     "royal_group"),
    ("ENERGETICA","energetica"),
    ("BAT",       "bat"),
    ("DINAMO",    "dinamo_trade"),
    ("TOP",       "top_energy"),
]


def connect():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, username=USER, password=PW, timeout=15)
    ssh.get_transport().set_keepalive(30)
    return ssh


def run(ssh, cmd, timeout=60):
    _, o, e = ssh.exec_command(cmd, timeout=timeout)
    out = o.read().decode("utf-8", errors="replace").strip()
    err = e.read().decode("utf-8", errors="replace").strip()
    if err and not any(w in err.lower() for w in ("warning", "notice", "deprecated", "hint")):
        print(f"  stderr: {err[:200]}")
    return out


def free_gb(ssh):
    out = run(ssh, "df -BG / | awk 'NR==2 {gsub(\"G\",\"\",$4); print $4}'", 10)
    try:
        return int(out)
    except ValueError:
        return 99


def get_api_key(ssh):
    key = run(ssh, "grep '^API_KEY=' /opt/sii/.env | cut -d= -f2-", 10)
    if not key:
        print("ERROR: API_KEY not found in /opt/sii/.env"); sys.exit(1)
    return key


def get_remote_files(ssh, account):
    """Returns sorted list of relative paths (from ITAL_BASE/account/) for all ZIPs."""
    cmd = (f'ssh {SSH_OPTS} {ITAL} '
           f'"cd {ITAL_BASE}/{account} 2>/dev/null && '
           f"find . -name '*.xml.zip' -printf '%P\\n' | sort\" 2>/dev/null")
    out = run(ssh, cmd, 300)
    return [line for line in out.splitlines() if line.strip()]


def get_db_processed(ssh, schema):
    """Returns set of file_name (basename without .zip) for status='ok' files."""
    out = run(ssh,
        f"docker exec sii-db-1 psql -U sii -d sii -t -A -c "
        f"\"SELECT file_name FROM {schema}.files WHERE status='ok'\"", 60)
    return set(line.strip() for line in out.splitlines() if line.strip())


def write_remote_file(ssh, remote_path, content: str):
    """Write content to a remote file via stdin of cat — avoids SFTP connection drops."""
    transport = ssh.get_transport()
    channel = transport.open_session()
    channel.exec_command(f"cat > {remote_path}")
    channel.sendall(content.encode("utf-8"))
    channel.shutdown_write()
    channel.recv_exit_status()
    channel.close()


def rsync_chunk(ssh, account, rel_paths):
    """Write file list via stdin-pipe, rsync those paths from Italian server to local data dir."""
    tmpfile = f"/tmp/sii_rsync_{account.lower()}.txt"
    write_remote_file(ssh, tmpfile, "\n".join(rel_paths) + "\n")

    run(ssh, f"mkdir -p {LOCAL_DATA}/{account}", 5)
    rsync_cmd = (
        f'rsync -az --files-from={tmpfile} '
        f'-e "ssh {SSH_OPTS}" '
        f'"{ITAL}:{ITAL_BASE}/{account}/" '
        f'"{LOCAL_DATA}/{account}/" 2>&1 | tail -3'
    )
    out = run(ssh, rsync_cmd, 600)
    if out:
        print(f"  rsync: {out}")
    run(ssh, f"rm -f {tmpfile}", 5)


def trigger_ingest(ssh, api_key, account):
    out = run(ssh,
        f'curl -sk -X POST -H "X-API-Key: {api_key}" https://localhost/api/sync/{account}',
        15)
    try:
        resp = json.loads(out)
        msg = resp.get("message", resp.get("status", str(resp)))
        print(f"  Triggered: {msg}")
        return "already running" not in msg.lower()
    except Exception:
        print(f"  Triggered: {out[:100]}")
        return True


def poll_until_idle(ssh, api_key, label):
    print(f"  Polling until {label} finishes...")
    t0 = time.time()
    while True:
        time.sleep(30)
        elapsed = int(time.time() - t0)
        try:
            ssh.close(); ssh = connect()
        except Exception as ex:
            print(f"  [reconnect failed: {ex}]"); time.sleep(15); continue
        try:
            raw = run(ssh,
                f'curl -sk -H "X-API-Key: {api_key}" https://localhost/api/sync/status', 60)
            items = json.loads(raw)
        except Exception as ex:
            print(f"  [{elapsed}s] status error: {ex}"); continue
        any_running = any(item.get("running", False) for item in items)
        live = next((i for i in items if i.get("running")), items[0] if items else {})
        ok = sum(i.get("files_ok", 0) for i in items)
        err = sum(i.get("files_error", 0) for i in items)
        print(f"  [{elapsed}s] running={any_running}  current={live.get('current_account', '?')}"
              f"  ok={ok}  err={err}")
        if not any_running:
            print(f"  Done in {elapsed}s")
            return ssh
        if elapsed > 7200:
            print("  Timeout after 2h — continuing")
            return ssh


def main():
    if not PW:
        print("ERROR: SII_SSH_PWD not set"); sys.exit(1)

    ssh = connect()
    print("Connected to DO server")
    api_key = get_api_key(ssh)
    print(f"API_KEY found ({len(api_key)} chars)\n")

    for account, schema in ACCOUNTS:
        print(f"\n{'='*65}")
        print(f"Account: {account}  (schema: {schema})")

        round_num = 0
        while True:
            round_num += 1
            try:
                ssh.close(); ssh = connect()
            except Exception as ex:
                print(f"Reconnect failed: {ex}"); time.sleep(15); ssh = connect()

            gb = free_gb(ssh)
            if gb < MIN_FREE_GB:
                print(f"  ABORT: only {gb}GB free on server — stopping to avoid disk full")
                ssh.close(); sys.exit(1)

            print(f"  Round {round_num}: fetching file lists... ({gb}GB free)", flush=True)
            remote = get_remote_files(ssh, account)
            processed = get_db_processed(ssh, schema)

            # Build name → relative-path lookup
            remote_by_name = {}
            for rel in remote:
                name = rel.split("/")[-1].replace(".zip", "")
                remote_by_name[name] = rel

            unprocessed_names = sorted(set(remote_by_name.keys()) - processed)
            remaining = len(unprocessed_names)

            if remaining == 0:
                print(f"  Round {round_num}: fully ingested — {len(processed):,} files in DB / "
                      f"{len(remote):,} on Italian server")
                break

            chunk_names = unprocessed_names[:CHUNK_SIZE]
            chunk_paths = [remote_by_name[n] for n in chunk_names]
            print(f"  Round {round_num}: {remaining:,} unprocessed → rsyncing {len(chunk_paths):,} files")

            rsync_chunk(ssh, account, chunk_paths)

            # Wait if another ingestion is already running
            try:
                raw = run(ssh,
                    f'curl -sk -H "X-API-Key: {api_key}" https://localhost/api/sync/status', 30)
                items = json.loads(raw)
                if any(item.get("running", False) for item in items):
                    print("  Another ingestion running — waiting for it to finish first...")
                    ssh = poll_until_idle(ssh, api_key, "current run")
            except Exception:
                pass

            trigger_ingest(ssh, api_key, account)
            ssh = poll_until_idle(ssh, api_key, account)

    # Final coverage check
    print("\n\n=== FINAL COVERAGE CHECK ===")
    try:
        ssh.close(); ssh = connect()
    except Exception:
        pass
    raw = run(ssh,
        f'curl -sk -H "X-API-Key: {api_key}" https://localhost/api/sync/coverage', 60)
    try:
        data = json.loads(raw)
        print(f"\n{'ACCOUNT':<14} {'MIN':<12} {'MAX':<12} {'ROWS':>12}  MISSING")
        print("-" * 80)
        for row in sorted(data, key=lambda r: r["account_id"]):
            missing = row.get("months_missing", [])
            miss_str = ", ".join(missing) if missing else "OK"
            flag = " <--" if missing else ""
            print(f"{row['account_id']:<14} {row.get('min_date') or '-':<12} "
                  f"{row.get('max_date') or '-':<12} {row.get('row_count_est', 0):>12,}  "
                  f"{miss_str}{flag}")
    except Exception as ex:
        print(f"Coverage parse error: {ex}\nRaw: {raw[:400]}")

    print("\n=== All backfill syncs complete ===")
    ssh.close()


if __name__ == "__main__":
    main()
