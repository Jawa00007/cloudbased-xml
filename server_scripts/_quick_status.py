"""Direct DB check: is retention running? archive_catalog content? Re-trigger if needed."""
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

print("=== ACTIVE DB QUERIES ===")
active = run(
    'docker exec sii-db-1 psql -U sii -d sii -t -c '
    '"SELECT pid, extract(epoch FROM (now()-query_start))::int AS secs, state, left(query,80) '
    'FROM pg_stat_activity WHERE state=\'active\' '
    'AND query NOT ILIKE \'%pg_stat_activity%\' ORDER BY secs DESC LIMIT 10;"', 15
)
print(active if active else "(no active queries)")

print("\n=== archive_catalog (direct DB) ===")
catalog = run(
    'docker exec sii-db-1 psql -U sii -d sii -t -c '
    '"SELECT account_id, cutoff_date, deleted_at, rows_deleted '
    'FROM public.archive_catalog ORDER BY deleted_at DESC LIMIT 20;"', 15
)
print(catalog if catalog else "(empty)")

print("\n=== TABLE EXISTS ===")
tbl = run(
    'docker exec sii-db-1 psql -U sii -d sii -t -c '
    '"SELECT COUNT(*) FROM information_schema.tables '
    'WHERE table_schema=\'public\' AND table_name=\'archive_catalog\';"', 10
)
print("archive_catalog count:", tbl.strip())

print("\n=== OLDEST DATA IN ch4.measurements ===")
oldest = run(
    'docker exec sii-db-1 psql -U sii -d sii -t -c '
    '"SELECT MIN(data_misura), MAX(data_misura), COUNT(*) FROM ch4.measurements;"', 25
)
print(oldest)

print("\n=== RE-TRIGGER RETENTION PURGE ===")
token = json.loads(run(
    'curl -s -X POST https://localhost/api/auth/token --insecure '
    '-H "Content-Type: application/json" '
    '-d \'{"username":"admin","password":"Din@mo5055Trade"}\'', 10
)).get('access_token', '')
resp = run(
    f'curl -s -X POST https://localhost/api/admin/retention/run --insecure '
    f'-H "Authorization: Bearer {token}"', 15
)
print("Response:", resp)

print("\nDisk:", run("df -h / | tail -1", 10))
ssh.close()
print("Done.")
