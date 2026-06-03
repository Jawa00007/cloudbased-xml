"""Per-account, per-year file audit: Italian server vs DB ingestion status.
Usage: SII_SSH_PWD=xxx py server_scripts/_italian_audit.py
"""
import os, sys, paramiko

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
HOST = "104.248.32.23"; USER = "root"
PW = os.environ.get("SII_SSH_PWD", "")

SSH_OPTS = "-i /root/.ssh/italian_server -o StrictHostKeyChecking=no -o ConnectTimeout=15 -o BatchMode=yes"
ITAL = "ubuntu@57.131.24.23"
BASE = "/home/ubuntu/SII_CLOUD"

ACCOUNTS = {
    "BAT": "bat", "CH4": "ch4", "DINAMO": "dinamo_trade", "EGOGREEN": "egogreen",
    "ENERGETICA": "energetica", "ENERGIT": "energit", "ENJOY": "enjoy_energy",
    "ONDA": "onda_piu", "POWERIT": "power_it", "ROYAL": "royal_group",
    "SOS": "sos", "TOP": "top_energy",
}


def connect():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, username=USER, password=PW, timeout=15)
    ssh.get_transport().set_keepalive(20)
    return ssh


def run(ssh, cmd, timeout=60):
    _, o, e = ssh.exec_command(cmd, timeout=timeout)
    out = o.read().decode("utf-8", errors="replace").strip()
    err = e.read().decode("utf-8", errors="replace").strip()
    if err and not any(w in err.lower() for w in ("warning", "notice", "deprecated", "hint")):
        print(f"  stderr: {err[:200]}")
    return out


def italian_year_counts(ssh, account):
    """Returns dict {year: count} for ZIP files on Italian server for given account."""
    cmd = (f'ssh {SSH_OPTS} {ITAL} '
           f'"find {BASE}/{account} -name \'*.xml.zip\' 2>/dev/null '
           f'| grep -oP \'/[0-9]{{4}}/\' | sort | uniq -c" 2>/dev/null')
    out = run(ssh, cmd, 180)
    counts = {}
    for line in out.splitlines():
        parts = line.strip().split()
        if len(parts) == 2 and parts[1].strip('/').isdigit():
            counts[parts[1].strip('/')] = int(parts[0])
    return counts


def db_year_counts(ssh, schema, account_id):
    """Returns dict {year: count} of ok files ingested, derived from mese_anno MM/YYYY."""
    q = (f"SELECT SUBSTRING(mese_anno FROM 4 FOR 4) AS yr, COUNT(*) "
         f"FROM {schema}.files WHERE account_id='{account_id}' AND status='ok' "
         f"AND mese_anno IS NOT NULL GROUP BY yr ORDER BY yr")
    out = run(ssh, f'docker exec sii-db-1 psql -U sii -d sii -t -A -F"|" -c "{q}"', 30)
    counts = {}
    for line in out.splitlines():
        parts = line.split("|")
        if len(parts) == 2 and parts[0].strip().isdigit():
            counts[parts[0].strip()] = int(parts[1].strip())
    return counts


def main():
    if not PW:
        print("ERROR: SII_SSH_PWD not set"); sys.exit(1)

    ssh = connect()
    print("Connected to DO server\n")

    test = run(ssh, f'ssh {SSH_OPTS} {ITAL} "echo OK" 2>/dev/null', 20)
    if test != "OK":
        print(f"ERROR: Cannot reach Italian server (got: {test!r})"); sys.exit(1)
    print("Italian server reachable\n")

    all_years = set()
    results = {}

    for acc, schema in ACCOUNTS.items():
        print(f"  Auditing {acc}...", flush=True)
        italian = italian_year_counts(ssh, acc)
        db = db_year_counts(ssh, schema, acc)
        results[acc] = {"italian": italian, "db": db}
        all_years |= set(italian.keys()) | set(db.keys())

    years = sorted(all_years)

    print("\n" + "=" * 110)
    hdr = f"{'ACCOUNT':<12}  {'ITALIAN TOTAL':>13}  {'DB OK TOTAL':>11}  " + \
          "  ".join(f"{y}(I/D)" for y in years)
    print(hdr)
    print("-" * 110)

    for acc in ACCOUNTS:
        r = results[acc]
        ital_total = sum(r["italian"].values())
        db_total = sum(r["db"].values())
        year_cols = "  ".join(
            f"{r['italian'].get(y, 0):>5}/{r['db'].get(y, 0):<5}" for y in years
        )
        gap = ital_total - db_total
        flag = f"  <- {gap:,} not ingested" if gap > 100 else ""
        print(f"{acc:<12}  {ital_total:>13,}  {db_total:>11,}  {year_cols}{flag}")

    print("\nI = files on Italian server  D = files ingested in DB (status=ok)")
    print("Note: DB counts months (mese_anno), Italian server counts individual ZIPs")
    ssh.close()


if __name__ == "__main__":
    main()
