import paramiko

HOST = "104.248.32.23"
USER = "root"
PASS = "Din@mo5055Trade"

def run(cmd, timeout=20):
    _, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    return (stdout.read() + stderr.read()).decode("utf-8", errors="replace").strip()

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, password=PASS, timeout=30)

api_key = run("grep '^API_KEY=' /opt/sii/.env | cut -d= -f2 | tr -d '\\r'")

print("=== Health check ===")
print(run(f"curl -sf -H 'X-API-Key: {api_key}' https://forecast.dinamoservice.it/api/health 2>&1 | python3 -c 'import sys,json; d=json.load(sys.stdin); print(\"status:\", d[\"status\"], \"db:\", d[\"database\"][\"status\"])' 2>&1"))

print("\n=== GET /admin/users ===")
print(run(f"curl -sf -H 'X-API-Key: {api_key}' https://forecast.dinamoservice.it/api/admin/users 2>&1"))

print("\n=== GET /admin/system/status (disk only) ===")
sysstat = run(f"curl -sf -H 'X-API-Key: {api_key}' https://forecast.dinamoservice.it/api/admin/system/status 2>&1")
print(sysstat[:400])

print("\n=== Container statuses ===")
print(run("docker ps --format '{{.Names}}\\t{{.Status}}'"))

ssh.close()
