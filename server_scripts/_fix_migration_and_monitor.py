"""
Fix two issues:
1. Run alembic upgrade head to create public.archive_catalog
2. Verify/fix monitor.sh on server (it must use HTTPS)
3. Re-trigger CH4 04/2026 forecast with correct job poll URL
"""
import sys, json, os, time
import paramiko
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

HOST = "104.248.32.23"
USER = "root"

def run(ssh, cmd, timeout=30):
    _, o, e = ssh.exec_command(cmd, timeout=timeout)
    out = o.read().decode('utf-8', errors='replace').strip()
    err = e.read().decode('utf-8', errors='replace').strip()
    if err and 'warning' not in err.lower() and 'notice' not in err.lower():
        print(f"  STDERR: {err[:200]}")
    return out

def main():
    pw = os.environ.get('SII_SSH_PWD', '')
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, username=USER, password=pw, timeout=15)
    print("Connected")

    # ── 1. Check and fix monitor.sh ────────────────────────────────────────
    print("\n=== monitor.sh check ===")
    monitor = run(ssh, "cat /opt/sii/monitor.sh | grep -A2 'API_CODE\\|curl.*health' | head -10")
    print(monitor)
    if "http://localhost/health" in monitor or ("https" not in monitor and "health" in monitor):
        print("!!! monitor.sh is using wrong URL — fixing...")
        run(ssh, r"""sed -i 's|http://localhost/health|https://localhost/api/health|g' /opt/sii/monitor.sh""")
        run(ssh, r"""sed -i 's|curl -s http://localhost|curl -sk https://localhost|g' /opt/sii/monitor.sh""")
        print("Fixed. New health check line:")
        print(run(ssh, "grep -A1 'API_CODE\\|curl.*health' /opt/sii/monitor.sh | head -6"))
    else:
        print("monitor.sh looks correct (uses HTTPS)")

    # ── 2. Run alembic upgrade head ────────────────────────────────────────
    print("\n=== alembic upgrade head ===")
    alembic = run(ssh, "docker exec sii-api-1 alembic upgrade head 2>&1 | tail -20", timeout=60)
    print(alembic)

    # Verify archive_catalog was created
    print("\n--- archive_catalog check ---")
    chk = run(ssh, """docker exec sii-db-1 psql -U sii -d sii -t -c \
      "SELECT to_regclass('public.archive_catalog');" """, timeout=15)
    print("archive_catalog:", chk.strip())

    # ── 3. Container status ────────────────────────────────────────────────
    print("\n=== Container status ===")
    print(run(ssh, 'docker ps --format "{{.Names}} {{.Status}}" | grep sii'))

    # ── 4. Health check ────────────────────────────────────────────────────
    print("\n=== API health ===")
    print(run(ssh, "curl -sk https://localhost/api/health | python3 -m json.tool 2>/dev/null || curl -sk https://localhost/api/health"))

    # ── 5. Re-trigger CH4 04/2026 forecast ────────────────────────────────
    print("\n=== Triggering CH4 04/2026 forecast ===")
    token_resp = run(ssh, """curl -sk -X POST https://localhost/api/auth/token \
      -H 'Content-Type: application/json' \
      -d '{"username":"admin","password":"Din@mo5055Trade"}' """)
    token = json.loads(token_resp).get('access_token', '')

    trig = run(ssh, f"""curl -sk -X POST https://localhost/api/forecast/generate \
      -H 'Authorization: Bearer {token}' \
      -H 'Content-Type: application/json' \
      -d '{{"account_id":"CH4","mese_anno":"04/2026"}}' """, timeout=20)
    print("Trigger:", trig)

    try:
        job_id = json.loads(trig).get('job_id', '')
    except Exception:
        job_id = ''

    if not job_id:
        print("No job_id returned")
        ssh.close(); return

    print(f"\nPolling job {job_id} (correct URL: /forecast/status/)...")
    start = time.time()
    while True:
        elapsed = int(time.time() - start)
        st_raw = run(ssh, f"""curl -sk https://localhost/api/forecast/status/{job_id} \
          -H 'Authorization: Bearer {token}' """)
        try:
            st = json.loads(st_raw)
            status   = st.get('status', '?')
            progress = st.get('progress', '')
            msg      = (st.get('message') or st.get('error') or '')[:80]
            print(f"[{elapsed}s] {status} | {progress} | {msg}")
            if status in ('done', 'error', 'failed'):
                break
            if status == 'not_found':
                print("Job disappeared — container may have restarted!")
                break
        except Exception as ex:
            print(f"[{elapsed}s] parse error: {ex} | {st_raw[:100]}")

        # Check container still running
        ct = run(ssh, 'docker ps --format "{{.Names}} {{.Status}}" | grep sii-api')
        if 'sii-api-1' not in ct:
            print(f"[{elapsed}s] !!! API container stopped !!!")
            break

        if elapsed > 900:
            print("Timeout")
            break
        time.sleep(15)

    # Final DB check
    print("\n=== DB verification ===")
    cnt = run(ssh, """docker exec sii-db-1 psql -U sii -d sii -t -c \
      "SELECT COUNT(*), COUNT(DISTINCT ea_kwh) FROM ch4.forecast_periods WHERE mese_anno='04/2026';" """, timeout=20)
    print("CH4 04/2026 forecast rows:", cnt.strip())

    ssh.close()

if __name__ == '__main__':
    main()
