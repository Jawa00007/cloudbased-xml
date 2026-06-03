"""Quick snapshot: retention log progress + disk."""
import os, sys, json, paramiko

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
HOST = "104.248.32.23"; USER = "root"
PW = os.environ.get('SII_SSH_PWD', '')

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, password=PW, timeout=15)
ssh.get_transport().set_keepalive(20)

def run(cmd, t=20):
    _, o, e = ssh.exec_command(cmd, timeout=t)
    return o.read().decode('utf-8', errors='replace').strip()

token = json.loads(run(
    'curl -s -X POST https://localhost/api/auth/token --insecure '
    '-H "Content-Type: application/json" '
    '-d \'{"username":"admin","password":"Din@mo5055Trade"}\'', 10
)).get('access_token', '')

log_raw = run(f'curl -s -H "Authorization: Bearer {token}" https://localhost/api/admin/retention/log --insecure', 15)
try:
    log = json.loads(log_raw)
    print(f"Retention log — {len(log)} entries:")
    total_del = 0
    for e in sorted(log, key=lambda x: x.get('account_id', '')):
        rows = e.get('rows_deleted', {})
        total = sum(rows.values()) if isinstance(rows, dict) else 0
        total_del += total
        print(f"  {e['account_id']:20s}  cutoff={e['cutoff_date']}  deleted_at={e['deleted_at'][:19]}  rows={total:,}")
    print(f"\nTotal deleted: {total_del:,}")
except Exception:
    print("Log parse error:", log_raw[:200])

print()
print("Disk:", run("df -h / | tail -1", 10))
db = run("docker exec sii-db-1 psql -U sii -d sii -t -c \"SELECT pg_size_pretty(pg_database_size('sii'));\"", 15)
print("DB:  ", db.strip())
ssh.close()
