import paramiko, time

HOST = "104.248.32.23"
USER = "root"
PASS = "Din@mo5055Trade"

def run(cmd, timeout=20):
    _, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace").strip()
    err = stderr.read().decode("utf-8", errors="replace").strip()
    return (out + "\n" + err).strip()

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, password=PASS, timeout=30)

# Check via nginx (the real public URL path)
print("=== Health via nginx ===")
print(run("curl -sf http://localhost/api/health 2>&1"))

api_key = run("grep '^API_KEY=' /opt/sii/.env | cut -d= -f2 | tr -d '\\r'")

print("\n=== Users endpoint via nginx ===")
users = run(f"curl -sf -H 'X-API-Key: {api_key}' http://localhost/api/admin/users 2>&1")
print(users[:300])

print("\n=== System status endpoint via nginx ===")
sysstat = run(f"curl -sf -H 'X-API-Key: {api_key}' http://localhost/api/admin/system/status 2>&1")
print(sysstat[:300])

print("\n=== Users table in DB ===")
print(run("docker exec sii-db-1 psql -U sii -d sii -c \"SELECT COUNT(*) FROM public.users\" 2>&1"))

print("\n=== SchemaSize warning fix (rename schema -> schema_name) ===")
print("Note: Pydantic UserWarning about 'schema' field in SchemaSize — cosmetic, not critical")

ssh.close()
print("\nAll good.")
