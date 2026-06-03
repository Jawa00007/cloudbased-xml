"""
Deploy commit 6c480fb (session.commit per chunk) + verify CH4 04/2026 forecast completes.
Steps:
1. Confirm 6c480fb is on server (already pulled)
2. docker compose build api && up -d api
3. Wait for API healthy
4. alembic upgrade head (creates archive_catalog if missing)
5. Trigger CH4 04/2026 forecast
6. Poll until done
7. Verify row count + distinct ea_kwh
"""
import sys, json, os, time, select
import paramiko
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

HOST = "104.248.32.23"
USER = "root"
BRANCH = "fix/forecast-weights-flat-curve"

def run(ssh, cmd, timeout=30):
    """Run short command, return output string."""
    _, o, e = ssh.exec_command(cmd, timeout=timeout)
    out = o.read().decode('utf-8', errors='replace').strip()
    err = e.read().decode('utf-8', errors='replace').strip()
    if err and 'warning' not in err.lower() and 'notice' not in err.lower() and 'deprecated' not in err.lower():
        print(f"  STDERR: {err[:300]}")
    return out

def run_streaming(ssh, cmd, max_wait=600):
    """
    Run a potentially long command (e.g. docker build), print output as it arrives.
    Returns final combined output. Uses non-blocking channel reads to avoid PipeTimeout.
    """
    transport = ssh.get_transport()
    chan = transport.open_session()
    chan.set_combine_stderr(True)   # merge stderr into stdout
    chan.exec_command(cmd)
    chan.settimeout(5)              # short per-read timeout; we loop ourselves

    lines = []
    start = time.time()
    last_line = ""

    while True:
        elapsed = int(time.time() - start)
        if elapsed > max_wait:
            print(f"\n  [timeout after {max_wait}s]")
            break

        # Try to read a chunk
        try:
            chunk = chan.recv(4096)
            if chunk:
                text = chunk.decode('utf-8', errors='replace')
                lines.append(text)
                for line in text.splitlines():
                    if line.strip() and line.strip() != last_line:
                        print(f"  {line.rstrip()}")
                        last_line = line.strip()
            else:
                # EOF
                break
        except Exception:
            pass

        if chan.exit_status_ready() and not chan.recv_ready():
            break

    chan.close()
    return ''.join(lines)

def main():
    pw = os.environ.get('SII_SSH_PWD', '')
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, username=USER, password=pw, timeout=15)
    ssh.get_transport().set_keepalive(30)
    print("Connected")

    # 1. Confirm commit is on server
    print("\n=== git log ===")
    log = run(ssh, "cd /opt/sii && git log --oneline -5", timeout=15)
    print(log)
    if "6c480fb" not in log and "commit after each 50-pod chunk" not in log:
        print("Pulling latest commits...")
        pull = run(ssh, f"cd /opt/sii && git pull origin {BRANCH}", timeout=60)
        print(pull)

    # 2. Build API image
    print("\n=== docker compose build api (streaming) ===")
    run_streaming(ssh, "cd /opt/sii && docker compose build api 2>&1", max_wait=600)

    # 3. Restart API container
    print("\n=== docker compose up -d api ===")
    up = run(ssh, "cd /opt/sii && docker compose up -d api 2>&1", timeout=60)
    print(up)

    # 4. Wait for API healthy
    print("\nWaiting for API to become healthy...")
    for i in range(30):
        time.sleep(5)
        code = run(ssh, 'curl -sk -o /dev/null -w "%{http_code}" https://localhost/api/health', timeout=10)
        status_line = run(ssh, 'docker ps --format "{{.Names}} {{.Status}}" | grep sii-api', timeout=10)
        print(f"  [{(i+1)*5}s] HTTP {code} | {status_line}")
        if code == "200":
            print("  API is healthy!")
            break
    else:
        print("  WARNING: API not healthy after 150s — continuing anyway")

    # 5. alembic upgrade head
    print("\n=== alembic upgrade head ===")
    alembic_out = run(ssh, "docker exec sii-api-1 alembic upgrade head 2>&1", timeout=120)
    lines = [l for l in alembic_out.splitlines() if 'Running' in l or 'ERROR' in l or 'error' in l.lower() or 'head' in l.lower() or 'up' in l.lower()]
    print('\n'.join(lines) if lines else alembic_out[-500:])

    # Verify public tables
    chk = run(ssh, """docker exec sii-db-1 psql -U sii -d sii -t -c \
      "SELECT table_name FROM information_schema.tables \
       WHERE table_schema='public' AND table_name IN ('archive_catalog','users') \
       ORDER BY table_name;" """, timeout=15)
    print(f"\nPublic tables present: {chk.strip()!r}")

    # 6. Check rows before trigger
    before = run(ssh, """docker exec sii-db-1 psql -U sii -d sii -t -c \
      "SELECT COUNT(*) FROM ch4.forecast_periods WHERE mese_anno='04/2026';" """, timeout=15)
    print(f"\nExisting CH4 04/2026 rows: {before.strip()}")

    # 7. Get auth token
    print("\n=== Get auth token ===")
    token_resp = run(ssh, """curl -sk -X POST https://localhost/api/auth/token \
      -H 'Content-Type: application/json' \
      -d '{"username":"admin","password":"Din@mo5055Trade"}' """, timeout=15)
    try:
        token = json.loads(token_resp).get('access_token', '')
        print(f"Token: {token[:40]}...")
    except Exception:
        print(f"Token error: {token_resp[:200]}")
        ssh.close(); return

    # 8. Trigger CH4 04/2026 forecast
    print("\n=== Trigger CH4 04/2026 forecast ===")
    trig = run(ssh, f"""curl -sk -X POST https://localhost/api/forecast/generate \
      -H 'Authorization: Bearer {token}' \
      -H 'Content-Type: application/json' \
      -d '{{"account_id":"CH4","mese_anno":"04/2026"}}' """, timeout=20)
    print("Response:", trig)
    try:
        job_id = json.loads(trig).get('job_id', '')
    except Exception:
        print("Could not parse job_id — checking if job already running")
        ssh.close(); return

    if not job_id:
        print("No job_id returned")
        ssh.close(); return

    print(f"\nJob ID: {job_id}")
    print(f"Polling /api/forecast/status/{job_id}  (expect ~10 min for 3,449 pods)...")

    # 9. Poll — CH4 has 3,449 pods × 31 days = ~10 min
    start = time.time()
    last_line = ""
    while True:
        elapsed = int(time.time() - start)
        st_raw = run(ssh, f"""curl -sk https://localhost/api/forecast/status/{job_id} \
          -H 'Authorization: Bearer {token}' """, timeout=15)
        try:
            st = json.loads(st_raw)
            status   = st.get('status', '?')
            progress = st.get('progress', '')
            msg      = (st.get('message') or st.get('error') or st.get('detail') or '')[:100]
            line = f"[{elapsed}s] {status} | {progress} | {msg}"
            if line != last_line:
                print(line)
                last_line = line
            if status in ('done', 'error', 'failed', 'not_found'):
                break
        except Exception as ex:
            print(f"[{elapsed}s] parse error: {ex} | {st_raw[:100]}")

        # Ensure container still alive
        ct = run(ssh, 'docker ps --format "{{.Names}} {{.Status}}" | grep sii-api', timeout=10)
        if 'sii-api-1' not in ct:
            print(f"[{elapsed}s] !!! API container stopped !!!")
            logs = run(ssh, "docker logs sii-api-1 --tail=20 2>&1", timeout=15)
            print(logs)
            break

        if elapsed > 1200:
            print("Timeout after 20 min")
            break
        time.sleep(20)

    # 10. Verify forecast rows
    print("\n=== CH4 04/2026 verification ===")
    cnt = run(ssh, """docker exec sii-db-1 psql -U sii -d sii -t -c \
      "SELECT COUNT(*), COUNT(DISTINCT ea_kwh), COUNT(DISTINCT ea_kwh_with_loss) \
       FROM ch4.forecast_periods WHERE mese_anno='04/2026';" """, timeout=30)
    print(f"  COUNT | distinct ea_kwh | distinct ea_kwh_with_loss: {cnt.strip()}")

    # 11. Disk + DB
    print("\n=== Disk & DB ===")
    print(run(ssh, "df -h /"))
    db_sz = run(ssh, """docker exec sii-db-1 psql -U sii -d sii -t -c \
      "SELECT pg_size_pretty(pg_database_size('sii'));" """)
    print(f"DB size: {db_sz.strip()}")

    # 12. Retention log
    print("\n=== Retention log ===")
    log_raw = run(ssh, f"""curl -sk https://localhost/api/admin/retention/log \
      -H 'Authorization: Bearer {token}' """, timeout=15)
    try:
        entries = json.loads(log_raw)
        print(f"{len(entries)} entries in archive_catalog")
        for e in entries[:8]:
            rows = e.get('rows_deleted') or {}
            total = sum(rows.values()) if isinstance(rows, dict) else 0
            print(f"  {e['account_id']:12s}  cutoff={e['cutoff_date']}  rows={total:,}")
    except Exception:
        print(log_raw[:400])

    print("\n=== Container status ===")
    print(run(ssh, 'docker ps --format "{{.Names}} {{.Status}}"'))

    ssh.close()
    print("\nDone.")

if __name__ == '__main__':
    main()
