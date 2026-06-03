import paramiko, sys

host = '104.248.32.23'
user = 'root'
pwd = 'Din@mo5055Trade'

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(host, username=user, password=pwd, timeout=30, allow_agent=False, look_for_keys=False)

def run(cmd, desc='', timeout=120):
    if desc:
        print(f'\n=== {desc} ===')
    _, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode('utf-8', errors='replace')
    err = stderr.read().decode('utf-8', errors='replace')
    if out: print(out.rstrip())
    if err and err.strip(): print('[STDERR]', err.rstrip())
    return out

# 1. DB total size
run('docker exec sii-db-1 psql -U sii -d sii -c "SELECT pg_size_pretty(pg_database_size(\'sii\')) AS total_db_size;"', 'Total DB size')

# 2. Schema sizes breakdown
run("""docker exec sii-db-1 psql -U sii -d sii -c "
SELECT nspname AS schema,
       pg_size_pretty(SUM(pg_total_relation_size(c.oid))) AS total_size,
       pg_size_pretty(SUM(pg_relation_size(c.oid))) AS table_size,
       pg_size_pretty(SUM(pg_indexes_size(c.oid))) AS index_size
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE nspname NOT IN ('pg_catalog','information_schema','pg_toast')
  AND c.relkind IN ('r','t')
GROUP BY nspname
ORDER BY SUM(pg_total_relation_size(c.oid)) DESC;
" """, 'Schema sizes')

# 3. WAL size
run('docker exec sii-db-1 psql -U sii -d sii -c "SELECT pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(), \'0/0\')) AS total_wal;"', 'WAL size')

# 4. Dead tuples (bloat)
run("""docker exec sii-db-1 psql -U sii -d sii -c "
SELECT schemaname, relname AS table_name,
       n_dead_tup AS dead_rows,
       pg_size_pretty(pg_total_relation_size(schemaname||'.'||relname)) AS total_size
FROM pg_stat_user_tables
WHERE n_dead_tup > 1000
ORDER BY n_dead_tup DESC
LIMIT 20;
" """, 'Tables with dead tuples (bloat)')

# 5. Run VACUUM ANALYZE on all schemas
print('\nRunning VACUUM ANALYZE on all schemas (may take a minute)...')
run("""docker exec sii-db-1 psql -U sii -d sii -c "
VACUUM ANALYZE;
" 2>&1""", 'VACUUM ANALYZE all tables', timeout=300)

# 6. Check WAL files on disk
run('docker exec sii-db-1 ls /var/lib/postgresql/data/pg_wal/ | wc -l', 'WAL file count')
run('docker exec sii-db-1 du -sh /var/lib/postgresql/data/pg_wal/', 'WAL disk usage')

client.close()
print('\nDone.')
