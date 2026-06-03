"""Check API logs for retention errors + check if pre-May-2025 data exists."""
import os, sys, paramiko

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
HOST = "104.248.32.23"; USER = "root"
PW = os.environ.get('SII_SSH_PWD', '')

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, password=PW, timeout=15)
ssh.get_transport().set_keepalive(20)

def run(cmd, t=25):
    _, o, e = ssh.exec_command(cmd, timeout=t)
    return o.read().decode('utf-8', errors='replace').strip()

print("=== API LOGS — retention/error lines (last 2h) ===")
logs = run(
    "docker logs sii-api-1 --since 2h 2>&1 | "
    "grep -i 'retention\\|archive\\|cutoff\\|Traceback\\|Error\\|error' | tail -50", 20
)
print(logs if logs else "(none)")

print("\n=== API LOGS — last 30 lines ===")
print(run("docker logs sii-api-1 --tail=30 2>&1", 15))

print("\n=== PRE-MAY-2025 ROW COUNTS (sample schemas) ===")
for schema in ['ch4', 'bat', 'power_it', 'egogreen', 'dinamo_trade']:
    count = run(
        f"docker exec sii-db-1 psql -U sii -d sii -t -c "
        f"\"SET search_path TO {schema}; "
        f"SELECT COUNT(*) FROM measurements WHERE data_misura < '2025-05-01';\"", 20
    )
    print(f"  {schema:15s}: {count.strip()} rows before 2025-05-01")

print("\n=== ARCHIVE_CATALOG ROW COUNT ===")
count = run(
    'docker exec sii-db-1 psql -U sii -d sii -t -c '
    '"SELECT COUNT(*) FROM public.archive_catalog;"', 10
)
print(f"  {count.strip()} rows")

ssh.close()
print("\nDone.")
