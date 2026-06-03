"""Read-only ingestion status: which months May 2025–May 2026 are ingested per account."""
import os, sys
import paramiko

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
HOST = "104.248.32.23"; USER = "root"
PW = os.environ.get('SII_SSH_PWD', '')

ACCOUNTS = {
    'BAT': 'bat', 'CH4': 'ch4', 'DINAMO': 'dinamo_trade', 'EGOGREEN': 'egogreen',
    'ENERGETICA': 'energetica', 'ENERGIT': 'energit', 'ENJOY': 'enjoy_energy',
    'ONDA': 'onda_piu', 'POWERIT': 'power_it', 'ROYAL': 'royal_group',
    'SOS': 'sos', 'TOP': 'top_energy',
}
EXPECTED = [
    '05/2025', '06/2025', '07/2025', '08/2025', '09/2025', '10/2025', '11/2025', '12/2025',
    '01/2026', '02/2026', '03/2026', '04/2026', '05/2026',
]


def connect():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, username=USER, password=PW, timeout=15)
    ssh.get_transport().set_keepalive(20)
    return ssh


def run(ssh, cmd, t=30):
    _, o, e = ssh.exec_command(cmd, timeout=t)
    return o.read().decode('utf-8', errors='replace').strip()


def main():
    if not PW:
        print("ERROR: SII_SSH_PWD not set"); return

    ssh = connect()
    print(f"{'ACCOUNT':<12} {'MIN DATE':<12} {'MAX DATE':<12} {'ROWS':>14}  MISSING MONTHS")
    print("-" * 100)

    for acc, schema in ACCOUNTS.items():
        try:
            ssh.close()
        except Exception:
            pass
        ssh = connect()

        # date range + total row count in measurements
        q = (f"SELECT to_char(MIN(data_misura),'YYYY-MM-DD'), "
             f"to_char(MAX(data_misura),'YYYY-MM-DD'), COUNT(*) "
             f"FROM {schema}.measurements WHERE account_id='{acc}'")
        row = run(ssh, f"docker exec sii-db-1 psql -U sii -d sii -t -A -F'|' -c \"{q}\"", 90)
        parts = row.split('|') if row else []
        mn  = parts[0].strip() if len(parts) > 0 else '?'
        mx  = parts[1].strip() if len(parts) > 1 else '?'
        cnt = int(parts[2].strip()) if len(parts) > 2 and parts[2].strip().isdigit() else 0

        # which mese_anno values have at least one ok file
        q2 = (f"SELECT DISTINCT mese_anno FROM {schema}.files "
              f"WHERE account_id='{acc}' AND status='ok' AND mese_anno IS NOT NULL "
              f"ORDER BY mese_anno")
        months_out = run(ssh, f"docker exec sii-db-1 psql -U sii -d sii -t -A -c \"{q2}\"", 30)
        have = set(months_out.splitlines()) if months_out else set()
        missing = [m for m in EXPECTED if m not in have]
        miss_str = ', '.join(missing) if missing else 'none'

        print(f"{acc:<12} {mn:<12} {mx:<12} {cnt:>14,}  {miss_str}")

    # per-account file counts: ok / error / total
    print()
    print(f"{'ACCOUNT':<12} {'FILES OK':>10} {'ERRORS':>8} {'TOTAL':>8}")
    print("-" * 44)
    for acc, schema in ACCOUNTS.items():
        try:
            ssh.close()
        except Exception:
            pass
        ssh = connect()
        q = (f"SELECT status, COUNT(*) FROM {schema}.files "
             f"WHERE account_id='{acc}' GROUP BY status")
        out = run(ssh, f"docker exec sii-db-1 psql -U sii -d sii -t -A -F'|' -c \"{q}\"", 20)
        ok = err = total = 0
        for line in out.splitlines():
            p = line.split('|')
            if len(p) == 2 and p[1].strip().isdigit():
                n = int(p[1].strip())
                total += n
                if p[0].strip() == 'ok':    ok = n
                if p[0].strip() == 'error': err = n
        print(f"{acc:<12} {ok:>10,} {err:>8,} {total:>8,}")

    # Italian server remaining ZIPs
    SSH_OPTS = '-i /root/.ssh/italian_server -o StrictHostKeyChecking=no -o ConnectTimeout=10 -o BatchMode=yes'
    ITAL = 'ubuntu@57.131.24.23'
    BASE = '/home/ubuntu/SII_CLOUD'
    print("\n=== Remaining ZIPs on Italian server ===")
    out = run(ssh, (
        f'ssh {SSH_OPTS} {ITAL} "'
        'for acc in BAT CH4 DINAMO EGOGREEN ENERGETICA ENERGIT ENJOY ONDA POWERIT ROYAL SOS TOP; do '
        f'count=$(find {BASE}/$acc -name \'*.xml.zip\' 2>/dev/null | wc -l); '
        'echo "  $acc: $count ZIPs"; '
        'done" 2>/dev/null'
    ), 40)
    print(out if out else "  (Italian server unreachable or 0 remaining)")

    ssh.close()
    print("\nDone.")


if __name__ == "__main__":
    main()
