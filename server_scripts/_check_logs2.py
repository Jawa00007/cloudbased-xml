import paramiko, time

HOST = "104.248.32.23"
USER = "root"
PASS = "Din@mo5055Trade"

def run(cmd, timeout=30):
    _, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    return out + err

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, password=PASS, timeout=30)

print("=== docker ps ===")
print(run("docker ps -a --format '{{.Names}}\\t{{.Status}}'"))

print("\n=== API logs (last 60) ===")
print(run("docker logs sii-api-1 --tail=60 2>&1"))

print("\n=== Alembic versions ===")
print(run("docker exec sii-db-1 psql -U sii -d sii -c \"SELECT version_num, is_current FROM alembic_version\" 2>&1"))

print("\n=== Run migration with new container ===")
# Try to run alembic in new container with nohup
print(run("cd /opt/sii && nohup docker compose run --rm --no-deps api alembic upgrade head > /tmp/alembic.log 2>&1 &"))
time.sleep(15)
print(run("cat /tmp/alembic.log 2>/dev/null | tail -20"))

ssh.close()
