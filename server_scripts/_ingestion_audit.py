import paramiko, sys

host = '104.248.32.23'
user = 'root'
pwd = 'Din@mo5055Trade'

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(host, username=user, password=pwd, timeout=20, allow_agent=False, look_for_keys=False)

def run(cmd, desc='', timeout=60):
    if desc:
        print(f'\n=== {desc} ===')
    _, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode('utf-8', errors='replace')
    err = stderr.read().decode('utf-8', errors='replace')
    if out: print(out.rstrip())
    if err and err.strip(): print('[STDERR]', err.rstrip())
    return out

# --- Ingestion status per account ---
accounts = {
    'BAT': 'bat',
    'CH4': 'ch4',
    'DINAMO': 'dinamo_trade',
    'EGOGREEN': 'egogreen',
    'ENERGETICA': 'energetica',
    'ENERGIT': 'energit',
    'ENJOY': 'enjoy_energy',
    'ONDA': 'onda_piu',
    'POWERIT': 'power_it',
    'ROYAL': 'royal_group',
    'SOS': 'sos',
    'TOP': 'top_energy',
}

print('\n=== Ingestion status (DB ok/error/total per account) ===')
for acc, schema in accounts.items():
    out = run(
        f"docker exec sii-db-1 psql -U sii -d sii -t -A -c "
        f"\"SET search_path TO {schema}; "
        f"SELECT status, count(*) FROM files GROUP BY status ORDER BY status;\"",
        timeout=15
    )
    lines = [l.strip() for l in out.strip().splitlines() if l.strip()]
    summary = ', '.join(lines) if lines else 'no data'
    print(f"  {acc:12s}: {summary}")

# --- CH4 deep dive ---
print('\n=== CH4 table row counts and sizes ===')
run("""docker exec sii-db-1 psql -U sii -d sii -c "
SET search_path TO ch4;
SELECT
    relname AS table_name,
    to_char(n_live_tup, '999,999,999') AS live_rows,
    pg_size_pretty(pg_relation_size(relid)) AS table_size,
    pg_size_pretty(pg_indexes_size(relid)) AS index_size,
    pg_size_pretty(pg_total_relation_size(relid)) AS total_size
FROM pg_stat_user_tables
ORDER BY pg_total_relation_size(relid) DESC;
" """, 'CH4 table breakdown')

# --- CH4 measurements breakdown by tipo_dato ---
run("""docker exec sii-db-1 psql -U sii -d sii -c "
SET search_path TO ch4;
SELECT tipo_dato, count(*) AS rows
FROM measurements
GROUP BY tipo_dato
ORDER BY count(*) DESC;
" """, 'CH4 measurements by tipo_dato (E/S/A)')

run("""docker exec sii-db-1 psql -U sii -d sii -c "
SET search_path TO ch4;
SELECT tipo_dato, count(*) AS rows
FROM measurements_secondary
GROUP BY tipo_dato
ORDER BY count(*) DESC;
" """, 'CH4 measurements_secondary by tipo_dato')

# --- CH4 index bloat check ---
run("""docker exec sii-db-1 psql -U sii -d sii -c "
SET search_path TO ch4;
SELECT indexrelname, pg_size_pretty(pg_relation_size(indexrelid)) AS idx_size
FROM pg_stat_user_indexes
ORDER BY pg_relation_size(indexrelid) DESC
LIMIT 10;
" """, 'CH4 largest indexes')

# --- CH4 distinct POD count ---
run("""docker exec sii-db-1 psql -U sii -d sii -c "
SET search_path TO ch4;
SELECT count(DISTINCT pod) AS distinct_pods FROM measurements;
" """, 'CH4 distinct PODs in measurements')

# --- CH4 files breakdown by cod_flusso ---
run("""docker exec sii-db-1 psql -U sii -d sii -c "
SET search_path TO ch4;
SELECT cod_flusso, status, count(*) AS cnt
FROM files
GROUP BY cod_flusso, status
ORDER BY count(*) DESC
LIMIT 20;
" """, 'CH4 files by flow type and status')

# --- Data on Italian server for each account ---
SSH_OPTS = '-i /root/.ssh/italian_server -o StrictHostKeyChecking=no -o ConnectTimeout=10 -o BatchMode=yes'
ITALIAN_HOST = 'ubuntu@57.131.24.23'
ITALIAN_BASE = '/home/ubuntu/SII_CLOUD'

print('\n=== Files on Italian server per account ===')
run(f"""ssh {SSH_OPTS} {ITALIAN_HOST} "
for acc in BAT CH4 DINAMO EGOGREEN ENERGETICA ENERGIT ENJOY ONDA POWERIT ROYAL SOS TOP; do
    count=$(find {ITALIAN_BASE}/$acc -name '*.xml.zip' 2>/dev/null | wc -l)
    echo \"  $acc: $count ZIPs\"
done
" 2>/dev/null""", 'Italian server ZIP counts', timeout=30)

client.close()
print('\nDone.')
