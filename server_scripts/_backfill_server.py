#!/usr/bin/env python3
"""Backfill runner — executes on the DO server directly.
Calls sync_sii.sh in a loop with BATCH_SIZE_OVERRIDE=10000 until all accounts
report 0 new files. Logs to /var/log/sii-backfill.log.
Start: nohup python3 /opt/sii/backfill_all.py > /var/log/sii-backfill.log 2>&1 &
Check: tail -f /var/log/sii-backfill.log
"""
import subprocess, time, re, os, sys, json

SCRIPT = "/opt/sii/server_scripts/sync_sii.sh"
if os.path.exists("/opt/sii/sync_sii.sh"):
    SCRIPT = "/opt/sii/sync_sii.sh"

LOG = "/var/log/sii-backfill.log"
SYNC_LOG = "/var/log/sii-sync.log"
STATUS_FILE = "/opt/sii/data/.backfill_status.json"

env = dict(os.environ)
env["BATCH_SIZE_OVERRIDE"] = "10000"

MAX_ROUNDS = 300


def log(msg):
    line = "[%s] %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg)
    print(line, flush=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")


def write_status(running, round_num, new_files=None, current_account=None):
    try:
        data = {
            "running": running,
            "round": round_num if running else None,
            "current": current_account,
            "accounts_done": round_num - 1,
            "accounts_total": MAX_ROUNDS,
            "files_total": new_files,
        }
        with open(STATUS_FILE, "w") as f:
            json.dump(data, f)
    except Exception as ex:
        log("Warning: could not write status file: %s" % ex)


def clear_status():
    try:
        with open(STATUS_FILE, "w") as f:
            json.dump({"running": False}, f)
    except Exception:
        pass


log("=== Backfill started. Script: %s ===" % SCRIPT)

for round_num in range(1, MAX_ROUNDS + 1):
    write_status(True, round_num)
    log("=== Round %d ===" % round_num)
    open(SYNC_LOG, "a").close()
    proc = subprocess.Popen(["bash", SCRIPT], env=env)
    current_acc = None
    with open(SYNC_LOG, "r", encoding="utf-8", errors="replace") as log_f:
        log_f.seek(0, 2)
        while proc.poll() is None:
            line = log_f.readline()
            if line.strip():
                m = re.search(r'\]\s+([A-Z0-9]+):\s+(?:\d+ new files|ingesting)', line)
                if m and m.group(1) != current_acc:
                    current_acc = m.group(1)
                    write_status(True, round_num, current_account=current_acc)
            else:
                time.sleep(2)
    proc.wait()

    try:
        with open(SYNC_LOG) as f:
            lines = [l.strip() for l in f if l.strip()]
        new = 0
        for line in reversed(lines):
            m = re.search(r"(\d+) new files", line)
            if m:
                new = int(m.group(1))
                log("Sync result: %s" % line)
                break
        else:
            log("Sync result (no summary line found): %s" % (lines[-1] if lines else ""))
    except Exception as ex:
        log("Could not read sync log: %s" % ex)
        new = 1

    write_status(True, round_num, new)
    log("New files this round: %d" % new)
    if new == 0:
        log("All accounts up to date. Backfill complete.")
        break
    time.sleep(5)

clear_status()
log("=== Status file cleared. Done. ===")
