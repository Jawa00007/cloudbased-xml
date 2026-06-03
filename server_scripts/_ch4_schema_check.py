"""Check CH4 schema state and new forecast job status."""
import sys, json, os
import paramiko
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

HOST = "104.248.32.23"
USER = "root"
NEW_JOB = "4048b484-cdd5-47d7-84fe-d3a7d2d40e6e"

def run(ssh, cmd, timeout=30):
    _, o, e = ssh.exec_command(cmd, timeout=timeout)
    return o.read().decode('utf-8', errors='replace').strip()

def main():
    pw = os.environ.get('SII_SSH_PWD', '')
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, username=USER, password=pw, timeout=15)

    # Auth token
    token_resp = run(ssh, """curl -sk -X POST https://localhost/api/auth/token \
      -H 'Content-Type: application/json' \
      -d '{"username":"admin","password":"Din@mo5055Trade"}' """)
    token = json.loads(token_resp).get('access_token', '')

    # Check new job status (correct URL this time: /status/ not /job/)
    print("--- New job status ---")
    st = run(ssh, f"""curl -sk https://localhost/api/forecast/status/{NEW_JOB} \
      -H 'Authorization: Bearer {token}' """)
    print(st)

    # Check CH4 forecast_periods columns
    print("\n--- CH4 forecast_periods columns ---")
    cols = run(ssh, """docker exec sii-db-1 psql -U sii -d sii -t -c \
      "SELECT column_name, data_type FROM information_schema.columns \
       WHERE table_schema='ch4' AND table_name='forecast_periods' \
       ORDER BY ordinal_position;" """, timeout=20)
    print(cols if cols else "(table does not exist)")

    # Check CH4 forecast_periods row count
    print("\n--- CH4 forecast_periods count ---")
    cnt = run(ssh, """docker exec sii-db-1 psql -U sii -d sii -t -c \
      "SELECT COUNT(*), COUNT(DISTINCT ea_kwh) FROM ch4.forecast_periods WHERE mese_anno='04/2026';" 2>&1""", timeout=20)
    # Try ea_mwh if ea_kwh fails
    if 'does not exist' in cnt:
        cnt2 = run(ssh, """docker exec sii-db-1 psql -U sii -d sii -t -c \
          "SELECT COUNT(*), COUNT(DISTINCT ea_mwh) FROM ch4.forecast_periods WHERE mese_anno='04/2026';" """, timeout=20)
        print(f"ea_kwh not found, ea_mwh: {cnt2.strip()}")
    else:
        print(cnt.strip())

    # Check Alembic version on CH4 schema
    print("\n--- Alembic version on CH4 schema ---")
    ver = run(ssh, """docker exec sii-db-1 psql -U sii -d sii -t -c \
      "SET search_path TO ch4; SELECT version_num FROM alembic_version;" 2>&1""", timeout=15)
    print(ver.strip())

    # Check API logs for forecast job errors
    print("\n--- API logs (last 30 lines) ---")
    logs = run(ssh, "docker logs sii-api-1 --tail=30 2>&1", timeout=20)
    print(logs)

    ssh.close()

if __name__ == '__main__':
    main()
