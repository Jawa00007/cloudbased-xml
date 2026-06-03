import paramiko, sys, time

host = '104.248.32.23'
user = 'root'
pwd = 'Din@mo5055Trade'

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(host, username=user, password=pwd, timeout=30, allow_agent=False, look_for_keys=False)

def run(cmd, desc='', timeout=60):
    if desc:
        print(f'\n=== {desc} ===')
    _, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode('utf-8', errors='replace')
    err = stderr.read().decode('utf-8', errors='replace')
    # strip unicode arrows/symbols that break cp1252 console
    for ch in ['→', '←', '✔', '✘']:
        out = out.replace(ch, '->')
        err = err.replace(ch, '->')
    if out: print(out.rstrip())
    if err and err.strip(): print('[STDERR]', err.rstrip())
    return out

# Enable and start the timer
run('systemctl daemon-reload && systemctl enable --now sii-disk-guardian.timer 2>&1 | cat', 'Enable disk guardian timer')

# Verify timer is active
run('systemctl is-active sii-disk-guardian.timer', 'Timer active check')
run('systemctl list-timers sii-disk-guardian.timer --no-pager 2>&1 | cat', 'Timer schedule')

# Run it once now to confirm it works (disk at 96% will trigger cleanup)
run('/opt/sii/disk_guardian.sh 2>&1', 'Run guardian now')

# Show final log
run('tail -30 /opt/sii/logs/disk_monitor.log', 'Guardian log')

# Final disk status
run('df -h /', 'Final disk status')

client.close()
print('\nDisk guardian deployed successfully.')
