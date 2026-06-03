"""Check deployed git version + key endpoint health on server."""
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

def ok(label, good, detail=''):
    print(f"  [{'OK  ' if good else 'FAIL'}] {label}" + (f"  ->  {detail}" if detail else ''))

print("=== DEPLOYED GIT STATE ===")
branch = run("cd /opt/sii && git branch --show-current")
log = run("cd /opt/sii && git log --oneline -6")
print(f"Branch: {branch}")
print(log)

expected_head = "873b2d0"  # fix: sync/status 500
deployed_head = run("cd /opt/sii && git rev-parse --short HEAD")
ok("Latest commit deployed", deployed_head == expected_head,
   f"HEAD={deployed_head} (want {expected_head})")

print("\n=== CONTAINERS ===")
containers = run('docker ps --format "{{.Names}}  {{.Status}}"')
for line in containers.splitlines():
    name = line.split()[0] if line.strip() else ''
    up = 'Up' in line
    ok(name, up, line.split('  ', 1)[-1] if '  ' in line else line)

print("\n=== API HEALTH ===")
health_raw = run("curl -s https://localhost/api/health --insecure", 10)
try:
    h = json.loads(health_raw)
    db = h.get('database', {})
    sched = h.get('scheduler', {})
    ok("API responding", True, health_raw[:100])
    ok("DB connected", db.get('status') == 'ok', str(db))
    ok("Scheduler running", sched.get('running') is True, f"next_run={sched.get('next_run','?')}")
except Exception:
    ok("API health", False, health_raw[:150])

print("\n=== AUTH + KEY ENDPOINTS ===")
token_raw = run(
    'curl -s -X POST https://localhost/api/auth/token --insecure '
    '-H "Content-Type: application/json" '
    '-d \'{"username":"admin","password":"Din@mo5055Trade"}\'', 10
)
try:
    token = json.loads(token_raw).get('access_token', '')
except Exception:
    token = ''
ok("Login (admin)", bool(token), "token OK" if token else token_raw[:80])

if token:
    def chk(path, label, t=15):
        code = run(
            f'curl -s -o /dev/null -w "%{{http_code}}" '
            f'-H "Authorization: Bearer {token}" '
            f'https://localhost/api{path} --insecure', t
        )
        ok(label, code in ('200','201','204'), f"HTTP {code}")
        return code

    chk('/sync/status', 'GET /sync/status  (was 500 — fixed)')
    chk('/accounts', 'GET /accounts')
    chk('/admin/users', 'GET /admin/users')
    chk('/admin/system/status', 'GET /admin/system/status')
    chk('/admin/loss-config', 'GET /admin/loss-config')
    chk('/admin/dispatching-config', 'GET /admin/dispatching-config')
    chk('/admin/anagrafica/months?account_id=CH4', 'GET /admin/anagrafica/months')
    chk('/admin/retention/log', 'GET /admin/retention/log')
    chk('/forecast/CH4/04%2F2026?limit=3', 'GET /forecast/CH4/04/2026')
    chk('/monitoring/missing?account=CH4&mese_anno=04/2026', 'GET /monitoring/missing')
    chk('/monitoring/corrections?account=CH4', 'GET /monitoring/corrections')

print("\n=== DISK ===")
disk = run("df -h / | tail -1")
print(f"  {disk}")

ssh.close()
print("\nDone.")
