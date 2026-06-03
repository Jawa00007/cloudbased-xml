import paramiko, sys

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

run('df -h /', 'Disk usage')
run('docker ps --format "table {{.Names}}\t{{.Status}}"', 'Container statuses')
run('curl -sk https://localhost/api/health', 'API health')
run('systemctl is-active sii-disk-guardian.timer && systemctl list-timers sii-disk-guardian.timer --no-pager 2>&1 | cat', 'Guardian timer')

client.close()
