import paramiko, sys, time

host = '104.248.32.23'
user = 'root'
pwd = 'Din@mo5055Trade'

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(host, username=user, password=pwd, timeout=20, allow_agent=False, look_for_keys=False)

def run(cmd, desc='', timeout=30):
    if desc:
        print(f'\n=== {desc} ===')
    _, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode('utf-8', errors='replace')
    err = stderr.read().decode('utf-8', errors='replace')
    if out: print(out.rstrip())
    if err and err.strip(): print('[STDERR]', err.rstrip())
    return out

# Kick off VACUUM ANALYZE in the background (non-blocking)
run("nohup docker exec sii-db-1 psql -U sii -d sii -c "
    "\"VACUUM ANALYZE ch4.measurements; VACUUM ANALYZE ch4.measurements_secondary; "
    "VACUUM ANALYZE ch4.corrections;\" "
    "> /opt/sii/logs/vacuum.log 2>&1 &",
    'Launch VACUUM ANALYZE in background')

# Fast: row count estimates from pg_class (no table scan needed)
run("""docker exec sii-db-1 psql -U sii -d sii -c "
SELECT
    n.nspname AS schema,
    c.relname AS table_name,
    to_char(c.reltuples::bigint, '999,999,999') AS est_rows,
    pg_size_pretty(pg_relation_size(c.oid)) AS table_size,
    pg_size_pretty(pg_indexes_size(c.oid)) AS index_size,
    pg_size_pretty(pg_total_relation_size(c.oid)) AS total_size
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'ch4'
  AND c.relkind = 'r'
  AND pg_total_relation_size(c.oid) > 1000000
ORDER BY pg_total_relation_size(c.oid) DESC;
" """, 'CH4 table sizes (fast, from pg_class estimates)')

# Fast: CH4 files breakdown by cod_flusso — which flow types dominate?
run("""docker exec sii-db-1 psql -U sii -d sii -c "
SET search_path TO ch4;
SELECT cod_flusso,
       count(*) FILTER (WHERE status='ok') AS ok,
       count(*) FILTER (WHERE status='error') AS errors,
       count(*) AS total
FROM files
GROUP BY cod_flusso
ORDER BY count(*) DESC
LIMIT 20;
" """, 'CH4 files by flow type')

# Fast: CH4 measurements — how many distinct PODs? Use pg_stats
run("""docker exec sii-db-1 psql -U sii -d sii -c "
SELECT n_distinct, tablename, attname
FROM pg_stats
WHERE schemaname = 'ch4'
  AND tablename = 'measurements'
  AND attname IN ('pod', 'data_misura', 'mese_anno')
ORDER BY attname;
" """, 'CH4 statistics (pod cardinality estimate)')

# DB size breakdown: schema vs schema
run("""docker exec sii-db-1 psql -U sii -d sii -c "
SELECT nspname AS schema,
       pg_size_pretty(sum(pg_total_relation_size(c.oid))) AS total,
       to_char(sum(c.reltuples::bigint), '999,999,999') AS est_total_rows
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE nspname NOT IN ('pg_catalog','information_schema','pg_toast')
  AND c.relkind = 'r'
GROUP BY nspname
ORDER BY sum(pg_total_relation_size(c.oid)) DESC;
" """, 'All schemas: size and estimated rows')

# Check if Italian server SSH key works
run("ssh -i /root/.ssh/italian_server -o StrictHostKeyChecking=no -o ConnectTimeout=10 "
    "-o BatchMode=yes ubuntu@57.131.24.23 'ls /home/ubuntu/SII_CLOUD/ | head -5' 2>&1",
    'Italian server directory listing', timeout=20)

client.close()
print('\nDone. VACUUM ANALYZE running in background — check /opt/sii/logs/vacuum.log in a few minutes.')
