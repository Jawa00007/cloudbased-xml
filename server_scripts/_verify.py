import paramiko, sys

host = '104.248.32.23'
user = 'root'
pwd = 'Din@mo5055Trade'

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(host, username=user, password=pwd, timeout=30, allow_agent=False, look_for_keys=False)

def run(cmd, desc='', timeout=30):
    if desc:
        print(f'\n=== {desc} ===')
    _, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode()
    err = stderr.read().decode()
    if out: print(out.rstrip())
    if err and err.strip(): print('[STDERR]', err.rstrip())
    return out

# Test through nginx (HTTPS, skip cert verification)
run('curl -sk https://localhost/api/health', 'Health via nginx HTTPS')
run('curl -sk https://localhost/api/accounts | head -c 500', 'Accounts via nginx HTTPS')

# Check running containers
run('docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"', 'All containers')

# Disk
run('df -h /', 'Disk status')

client.close()
print('\nSite is back up!' if True else '')
