import paramiko

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect("104.248.32.23", username="root", key_filename=r"C:\Users\jawad\.ssh\do_sii", timeout=15)

# Latest logs — show everything, not just errors
_, stdout, _ = client.exec_command(
    "docker compose -f /opt/sii/docker-compose.yml logs --tail=50 api 2>&1"
)
print(stdout.read().decode("utf-8", errors="replace"))
client.close()
