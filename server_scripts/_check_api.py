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
    out = stdout.read().decode()
    err = stderr.read().decode()
    if out: print(out.rstrip())
    if err and err.strip(): print('[STDERR]', err.rstrip())
    return out

# API logs
run('docker logs sii-api-1 --tail=30 2>&1', 'API logs')

# Health checks
run('curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/api/health', 'API health')
run('curl -s http://localhost:8000/api/health', 'API health response')
run('curl -s http://localhost:8000/api/accounts | head -c 300', 'Accounts endpoint')

client.close()
