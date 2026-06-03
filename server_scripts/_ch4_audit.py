import paramiko, sys

host = '104.248.32.23'
user = 'root'
pwd = 'Din@mo5055Trade'

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(host, username=user, password=pwd, timeout=20, allow_agent=False, look_for_keys=False)

def run(cmd, desc='', timeout=120):
    if desc:
        print(f'\n=== {desc} ===')
    _, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode('utf-8', errors='replace')
    err = stderr.read().decode('utf-8', errors='replace')
    if out: print(out.rstrip())
    if err and err.strip(): print('[STDERR]', err.rstrip())
    return out

# 1. Ingestion summary per account (from DB files table)
print('\n=== Ingestion progress per account (DB) ===')
print(f"{'Account':<12} {'OK':>8} {'Error':>7} {'Total':>8}")
print('-' * 40)
accounts = {
    'BAT': 'bat', 'CH4': 'ch4', 'DINAMO': 'dinamo_trade',
    'EGOGREEN': 'egogreen', 'ENERGETICA': 'energetica', 'ENERGIT': 'energit',
    'ENJOY': 'enjoy_energy', 'ONDA': 'onda_piu', 'POWERIT': 'power_it',
    'ROYAL': 'royal_group', 'SOS': 'sos', 'TOP': 'top_energy',
}
for acc, schema in accounts.items():
    q = (f"docker exec sii-db-1 psql -U sii -d sii -t -A -c \""
         f"SET search_path TO {schema}; "
         f"SELECT coalesce(sum(case when status='ok' then 1 end),0), "
         f"coalesce(sum(case when status='error' then 1 end),0), "
         f"count(*) FROM files;\"")
    out = run(q, timeout=15)
    parts = [l.strip() for l in out.strip().splitlines() if '|' in l]
    if parts:
        row = parts[-1].split('|')
        ok, err, tot = row[0], row[1], row[2]
        print(f"  {acc:<12} {ok:>8} {err:>7} {tot:>8}")
    else:
        print(f"  {acc:<12} {'?':>8} {'?':>7} {'?':>8}")

# 2. Italian server counts (how many ZIPs exist per account)
SSH_OPTS = '-i /root/.ssh/italian_server -o StrictHostKeyChecking=no -o ConnectTimeout=10 -o BatchMode=yes'
ITALIAN = 'ubuntu@57.131.24.23'
BASE = '/home/ubuntu/SII_CLOUD'
run(f"""ssh {SSH_OPTS} {ITALIAN} "
for acc in BAT CH4 DINAMO EGOGREEN ENERGETICA ENERGIT ENJOY ONDA POWERIT ROYAL SOS TOP; do
    count=$(find {BASE}/$acc -name '*.xml.zip' 2>/dev/null | wc -l)
    printf '  %-12s %8d ZIPs\\n' $acc $count
done" 2>/dev/null""", 'Italian server ZIP counts (total ever)', timeout=60)

# 3. CH4 — why is it so large? Check distinct POD count and date range
run("""docker exec sii-db-1 psql -U sii -d sii -c "
SET search_path TO ch4;
SELECT
    (SELECT count(DISTINCT pod) FROM measurements) AS distinct_pods_E,
    (SELECT min(data_misura) FROM measurements) AS earliest_date,
    (SELECT max(data_misura) FROM measurements) AS latest_date,
    (SELECT count(DISTINCT mese_anno) FROM measurements) AS distinct_months;
" """, 'CH4 measurements scope (PODs, date range)', timeout=60)

# 4. CH4 corrections table — is it abnormally large?
run("""docker exec sii-db-1 psql -U sii -d sii -c "
SET search_path TO ch4;
SELECT
    pg_size_pretty(pg_total_relation_size('corrections')) AS corrections_total,
    (SELECT count(*) FROM corrections) AS corrections_rows,
    pg_size_pretty(pg_total_relation_size('measurements')) AS measurements_total,
    pg_size_pretty(pg_total_relation_size('measurements_secondary')) AS secondary_total;
" """, 'CH4 table sizes with actual row counts', timeout=60)

# 5. Run VACUUM ANALYZE now that disk has space
print('\nRunning VACUUM ANALYZE on CH4 schema (updates row stats)...')
run("""docker exec sii-db-1 psql -U sii -d sii -c "
SET search_path TO ch4;
VACUUM ANALYZE measurements;
VACUUM ANALYZE measurements_secondary;
VACUUM ANALYZE corrections;
VACUUM ANALYZE files;
" """, 'VACUUM ANALYZE CH4 tables', timeout=300)

# 6. Re-check live row counts after vacuum
run("""docker exec sii-db-1 psql -U sii -d sii -c "
SET search_path TO ch4;
SELECT relname, to_char(n_live_tup, '999,999,999') AS live_rows,
       to_char(n_dead_tup, '999,999,999') AS dead_rows,
       pg_size_pretty(pg_total_relation_size(relid)) AS total_size
FROM pg_stat_user_tables
WHERE schemaname = 'ch4'
ORDER BY pg_total_relation_size(relid) DESC
LIMIT 8;
" """, 'CH4 live rows after VACUUM', timeout=30)

client.close()
print('\nDone.')
