import paramiko, sys

host = '104.248.32.23'
user = 'root'
pwd = 'Din@mo5055Trade'

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
try:
    client.connect(host, username=user, password=pwd, timeout=20, allow_agent=False, look_for_keys=False)

    def run(cmd):
        _, stdout, stderr = client.exec_command(cmd)
        out = stdout.read().decode()
        err = stderr.read().decode()
        if out: print(out)
        if err: print('[STDERR]', err, file=sys.stderr)

    run('df -h /')
    print('---')
    run('docker system df')
    print('---')
    run('du -sh /opt/sii/data/* 2>/dev/null | sort -rh | head -20')
    print('---')
    run('du -sh /var/lib/docker 2>/dev/null')
    client.close()
except Exception as e:
    print(f'ERROR: {e}', file=sys.stderr)
    sys.exit(1)
