"""Check API logs and re-trigger CH4 forecast."""
import sys, json, os
import paramiko
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

HOST = "104.248.32.23"
USER = "root"
JOB_ID = "d123f7c6-e4c5-49a0-a85b-3bc0e7f24569"

def run(ssh, cmd, timeout=30):
    _, o, e = ssh.exec_command(cmd, timeout=timeout)
    out = o.read().decode('utf-8', errors='replace').strip()
    return out

def main():
    pw = os.environ.get('SII_SSH_PWD', '')
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, username=USER, password=pw, timeout=15)

    # Get token
    token_resp = run(ssh, """curl -sk -X POST https://localhost/api/auth/token \
      -H 'Content-Type: application/json' \
      -d '{"username":"admin","password":"Din@mo5055Trade"}' """)
    token = json.loads(token_resp).get('access_token', '')
    print("Token:", token[:20] + "...")

    # Check job status directly with verbose output
    print("\n--- Job status (raw) ---")
    raw = run(ssh, f"""curl -sk -w "\\nHTTP_STATUS:%{{http_code}}" \
      https://localhost/api/forecast/job/{JOB_ID} \
      -H 'Authorization: Bearer {token}' """)
    print(raw)

    # Check API logs for errors
    print("\n--- API logs (last 40 lines) ---")
    logs = run(ssh, "docker logs sii-api-1 --tail=40 2>&1", timeout=20)
    print(logs)

    # Check CH4 forecast rows
    print("\n--- CH4 forecast_periods count ---")
    cnt = run(ssh, """docker exec sii-db-1 psql -U sii -d sii -t -c \
      "SELECT COUNT(*), COUNT(DISTINCT ea_kwh) FROM ch4.forecast_periods WHERE mese_anno='04/2026';" """)
    print(cnt.strip())

    # Try to trigger a fresh forecast
    print("\n--- Triggering fresh CH4 04/2026 forecast ---")
    trig = run(ssh, f"""curl -sk -X POST https://localhost/api/forecast/generate \
      -H 'Authorization: Bearer {token}' \
      -H 'Content-Type: application/json' \
      -d '{{"account_id":"CH4","mese_anno":"04/2026"}}' """, timeout=20)
    print("Response:", trig)

    ssh.close()

if __name__ == '__main__':
    main()
