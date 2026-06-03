"""Investigate sync/status 500 and check git state on server."""
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

# Get token
token_raw = run(
    'curl -s -X POST https://localhost/api/auth/token --insecure '
    '-H "Content-Type: application/json" '
    '-d \'{"username":"admin","password":"Din@mo5055Trade"}\'', 15
)
token = json.loads(token_raw).get('access_token', '')

print("=== GET /sync/status response ===")
body = run(f'curl -s -H "Authorization: Bearer {token}" https://localhost/api/sync/status --insecure', 15)
print(body[:800])

print("\n=== API logs last 40 lines ===")
print(run("docker logs sii-api-1 --tail=40 2>&1", 25))

print("\n=== git log on server (HEAD) ===")
print(run("cd /opt/sii && git log --oneline -10", 10))

print("\n=== git remote tracking ===")
print(run("cd /opt/sii && git fetch --dry-run 2>&1", 15))
print(run("cd /opt/sii && git status", 10))

print("\n=== remaining endpoint checks ===")
def chk(path, label):
    code = run(f'curl -s -o /dev/null -w "%{{http_code}}" -H "Authorization: Bearer {token}" https://localhost/api{path} --insecure', 15)
    status = "OK  " if code in ("200","201","204") else "FAIL"
    print(f"  [{status}] {label}  ->  HTTP {code}")

chk('/forecast/measurements/months?account_id=CH4', 'GET /forecast/measurements/months (CH4)')
chk('/admin/retention/log', 'GET /admin/retention/log')
chk('/monitoring/missing?account=CH4&mese_anno=04/2026', 'GET /monitoring/missing')
chk('/monitoring/corrections?account=CH4', 'GET /monitoring/corrections')

print("\n=== DB schema sizes ===")
sizes = run(
    'docker exec sii-db-1 psql -U sii -d sii -t -c '
    '"SELECT schemaname, pg_size_pretty(SUM(pg_total_relation_size'
    "(schemaname||'.'||tablename))::bigint) "
    "FROM pg_tables WHERE schemaname NOT IN ('pg_catalog','information_schema') "
    "GROUP BY schemaname ORDER BY SUM(pg_total_relation_size(schemaname||'.'||tablename)) DESC LIMIT 15;\"",
    25
)
for line in sizes.splitlines():
    if line.strip():
        print(f"  {line.strip()}")

ssh.close()
print("\nDone.")
