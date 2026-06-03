import sys, time, json
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import paramiko

HOST = "104.248.32.23"
USER = "root"

def run(ssh, cmd, timeout=30):
    _, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode('utf-8', errors='replace').strip()
    err = stderr.read().decode('utf-8', errors='replace').strip()
    return out, err

def main():
    pw = __import__('os').environ.get('SII_SSH_PWD', '')
    if not pw:
        print("Set SII_SSH_PWD env var"); return

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, username=USER, password=pw, timeout=15)
    print("Connected")

    # Get token
    out, _ = run(ssh, """curl -s -X POST http://localhost:8000/auth/login \
        -H 'Content-Type: application/json' \
        -d '{"username":"admin","password":"Din@mo5055Trade"}'""", timeout=15)
    token = json.loads(out).get('access_token')
    if not token:
        print("Login failed:", out); ssh.close(); return
    print("Token OK")

    # Trigger CH4 04/2026 forecast
    out, _ = run(ssh, f"""curl -s -X POST http://localhost:8000/api/forecast/generate \
        -H 'Content-Type: application/json' \
        -H 'Authorization: Bearer {token}' \
        -d '{{"account_id":"CH4","mese_anno":"04/2026"}}'""", timeout=20)
    print("Trigger response:", out)
    try:
        job_id = json.loads(out).get('job_id')
    except Exception:
        job_id = None
    if not job_id:
        print("No job_id — may already be running or error"); ssh.close(); return
    print(f"Job ID: {job_id}")

    # Poll
    start = time.time()
    while True:
        elapsed = int(time.time() - start)
        out, _ = run(ssh, f"""curl -s http://localhost:8000/api/forecast/status/{job_id} \
            -H 'Authorization: Bearer {token}'""", timeout=15)
        try:
            st = json.loads(out)
            status = st.get('status')
            msg = st.get('message','')
            print(f"[{elapsed}s] {status} — {msg}")
            if status in ('done', 'error'):
                break
        except Exception:
            print(f"[{elapsed}s] parse error:", out[:200])
        time.sleep(20)

    # Verify
    print("\nVerifying CH4 04/2026 distinct ea_kwh values...")
    out, _ = run(ssh, """docker exec sii-db-1 psql -U sii -d sii -t -c \
        "SELECT COUNT(DISTINCT ea_kwh) FROM ch4.forecast_periods WHERE mese_anno='04/2026';" """, timeout=20)
    print("Distinct ea_kwh:", out.strip())

    out, _ = run(ssh, """docker exec sii-db-1 psql -U sii -d sii -t -c \
        "SELECT COUNT(*) FROM ch4.forecast_periods WHERE mese_anno='04/2026';" """, timeout=20)
    print("Total rows:", out.strip())

    ssh.close()
    print("Done")

if __name__ == '__main__':
    main()
