import json, urllib.request, urllib.error, time

BASE = "http://localhost:8000/api"

def post(path, body, token=None):
    data = json.dumps(body).encode()
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(BASE + path, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"error": e.code, "body": e.read().decode()}

def get(path, token=None):
    headers = {}
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(BASE + path, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"error": e.code, "body": e.read().decode()}

resp = post("/auth/token", {"username": "admin", "password": "Din@mo5055Trade"})
print("login:", json.dumps(resp)[:200])
token = resp.get("access_token")
if not token:
    print("No token — exiting")
    exit(1)

def regenerate(account_id, mese_anno):
    print(f"\n=== {account_id} / {mese_anno} ===")
    r = post("/forecast/generate", {"account_id": account_id, "mese_anno": mese_anno}, token)
    print("submit:", r)
    job_id = r.get("job_id")
    if not job_id:
        return
    for i in range(120):
        time.sleep(5)
        r = get("/forecast/status/" + job_id, token)
        status = r.get("status", "?")
        detail = r.get("result") or r.get("error") or ""
        print(f"  [{(i+1)*5}s] {status} {detail}")
        if status in ("done", "error"):
            break

regenerate("BAT", "04/2026")
print("\nAll done.")
