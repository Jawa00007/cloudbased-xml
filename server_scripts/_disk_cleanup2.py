import paramiko, sys

host = '104.248.32.23'
user = 'root'
pwd = 'Din@mo5055Trade'

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(host, username=user, password=pwd, timeout=30, allow_agent=False, look_for_keys=False)

def run(cmd, desc=''):
    if desc:
        print(f'\n=== {desc} ===')
    _, stdout, stderr = client.exec_command(cmd, timeout=120)
    out = stdout.read().decode()
    err = stderr.read().decode()
    if out: print(out.rstrip())
    if err: print('[STDERR]', err.rstrip(), file=sys.stderr)
    return out

# 1. Check API health
run('curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/api/health', 'API health check')

# 2. Clean journal logs (keep only 50 MB)
run('journalctl --vacuum-size=50M', 'Vacuum journal logs')

# 3. Remove old backfill logs (keep last 3)
run('ls -t /opt/sii/logs/backfill_*.log | tail -n +4 | xargs rm -f 2>/dev/null; echo "done"', 'Remove old backfill logs')

# 4. Check Docker volumes detail
run('docker volume ls && docker system df -v 2>/dev/null | grep -A5 "Local Volumes"', 'Docker volumes')

# 5. Check what is in the PostgreSQL volume (size breakdown)
run('docker exec sii-db-1 psql -U sii -d sii -c "SELECT pg_size_pretty(pg_database_size(\'sii\')) AS db_size, pg_size_pretty(pg_total_relation_size(\'public.accounts\')) AS accounts_table;" 2>/dev/null', 'DB size')

# 6. Check schema sizes
run('''docker exec sii-db-1 psql -U sii -d sii -t -A -c "
SELECT schema_name,
       pg_size_pretty(sum(pg_total_relation_size(quote_ident(schema_name)||'.'||quote_ident(table_name)))) AS size
FROM information_schema.tables
WHERE table_schema NOT IN ('pg_catalog','information_schema')
GROUP BY schema_name
ORDER BY sum(pg_total_relation_size(quote_ident(schema_name)||'.'||quote_ident(table_name))) DESC;
" 2>/dev/null''', 'DB schema sizes')

# 7. Final disk status
run('df -h /', 'Disk after cleanup')

client.close()
print('\nDone.')
