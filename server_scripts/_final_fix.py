"""
Final fix sequence:
1. git pull (env.py fix)
2. alembic upgrade head (creates public.archive_catalog + public.users)
3. VACUUM bat+ch4 measurements (correct syntax — no transaction wrapper)
4. Re-trigger CH4 04/2026 forecast, poll until done
"""
import sys, json, os, time
import paramiko
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

HOST = "104.248.32.23"
USER = "root"
BRANCH = "fix/forecast-weights-flat-curve"

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

    # 1. git pull
    print("\n=== git pull ===")
    print(run(ssh, f"cd /opt/sii && git pull origin {BRANCH}"))

    # 2. alembic upgrade head (includes public schema now)
    print("\n=== alembic upgrade head ===")
    alembic_out = run(ssh, "docker exec sii-api-1 alembic upgrade head 2>&1", timeout=120)
    # Show only lines mentioning Running or errors
    relevant = [l for l in alembic_out.splitlines() if 'Running' in l or 'ERROR' in l or 'error' in l.lower()]
    print('\n'.join(relevant) if relevant else alembic_out[-500:])

    # Verify tables created
    chk = run(ssh, """docker exec sii-db-1 psql -U sii -d sii -t -c \
      "SELECT table_name FROM information_schema.tables \
       WHERE table_schema='public' AND table_name IN ('archive_catalog','users') \
       ORDER BY table_name;" """, timeout=15)
    print(f"\nPublic tables created: {chk.strip()}")

    # 3. VACUUM (correct syntax — standalone, no transaction block)
    print("\n=== VACUUM measurements tables ===")
    for schema in ['bat', 'ch4', 'dinamo_trade']:
        v = run(ssh, f"""docker exec sii-db-1 psql -U sii -d sii -c \
          "VACUUM {schema}.measurements;" 2>&1""", timeout=300)
        size_row = [l for l in v.splitlines() if 'VACUUM' in l or 'ERROR' in l]
        print(f"  {schema}: {size_row[0] if size_row else v[:60]}")

    # 4. DB size after vacuum
    print("\n=== DB size after VACUUM ===")
    db_sz = run(ssh, """docker exec sii-db-1 psql -U sii -d sii -t -c \
      "SELECT pg_size_pretty(pg_database_size('sii'));" """)
    print(db_sz.strip())

    print("\n=== Disk after VACUUM ===")
    print(run(ssh, "df -h /"))

    # 5. Trigger CH4 04/2026 forecast
    print("\n=== Trigger CH4 04/2026 forecast ===")
    token_resp = run(ssh, """curl -sk -X POST https://localhost/api/auth/token \
      -H 'Content-Type: application/json' \
      -d '{"username":"admin","password":"Din@mo5055Trade"}' """)
    token = json.loads(token_resp).get('access_token', '')

    trig = run(ssh, f"""curl -sk -X POST https://localhost/api/forecast/generate \
      -H 'Authorization: Bearer {token}' \
      -H 'Content-Type: application/json' \
      -d '{{"account_id":"CH4","mese_anno":"04/2026"}}' """, timeout=20)
    print("Trigger:", trig)
    job_id = json.loads(trig).get('job_id', '')

    if not job_id:
        print("No job_id")
        ssh.close(); return

    # 6. Poll (correct URL: /forecast/status/)
    print(f"\nPolling /api/forecast/status/{job_id} ...")
    start = time.time()
    while True:
        elapsed = int(time.time() - start)
        st_raw = run(ssh, f"""curl -sk https://localhost/api/forecast/status/{job_id} \
          -H 'Authorization: Bearer {token}' """)
        try:
            st = json.loads(st_raw)
            status   = st.get('status', '?')
            progress = st.get('progress', '')
            msg      = (st.get('message') or st.get('error') or st.get('detail') or '')[:80]
            print(f"[{elapsed}s] {status} | {progress} | {msg}")
            if status in ('done', 'error', 'failed', 'not_found'):
                break
        except Exception as ex:
            print(f"[{elapsed}s] {ex} | {st_raw[:100]}")

        ct = run(ssh, 'docker ps --format "{{.Names}} {{.Status}}" | grep sii-api')
        if 'sii-api-1' not in ct:
            print(f"[{elapsed}s] !!! API container stopped !!!")
            break

        if elapsed > 1200:
            print("Timeout after 20 min")
            break
        time.sleep(15)

    # 7. Verify
    print("\n=== DB verification ===")
    cnt = run(ssh, """docker exec sii-db-1 psql -U sii -d sii -t -c \
      "SELECT COUNT(*), COUNT(DISTINCT ea_kwh), COUNT(DISTINCT ea_kwh_with_loss) \
       FROM ch4.forecast_periods WHERE mese_anno='04/2026';" """, timeout=30)
    print("CH4 04/2026:", cnt.strip())

    print("\n=== Retention log (archive_catalog) ===")
    log_raw = run(ssh, f"""curl -sk https://localhost/api/admin/retention/log \
      -H 'Authorization: Bearer {token}' """)
    try:
        entries = json.loads(log_raw)
        print(f"{len(entries)} entries in archive_catalog")
        for e in entries[:5]:
            print(f"  {e['account_id']:12s}  cutoff={e['cutoff_date']}  rows={sum((e.get('rows_deleted') or {}).values()):,}")
    except Exception:
        print(log_raw[:200])

    print("\n=== Final container status ===")
    print(run(ssh, 'docker ps --format "{{.Names}} {{.Status}}"'))

    ssh.close()
    print("\nAll done.")

if __name__ == '__main__':
    main()
