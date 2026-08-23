import re

path = "backend/tests/test_phase4_api_security.py"
with open(path, "r") as f:
    code = f.read()

# Fix check get
code = code.replace(
    'check = client.get("/api/permissions/check", params={"category": "file_write"})',
    'check = client.get("/api/permissions/check", params={"category": "file_write"}, headers=_auth_headers())'
)

# Fix session creations
code = code.replace(
    'session = client.post("/api/sessions").json()',
    'session = client.post("/api/sessions", headers=_auth_headers()).json()'
)

code = code.replace(
    'client.post(f"/api/sessions/{session[\'session_id\']}/invalidate")',
    'client.post(f"/api/sessions/{session[\'session_id\']}/invalidate", headers=_auth_headers())'
)

code = code.replace(
    'response = client.post("/api/sessions")',
    'response = client.post("/api/sessions", headers=_auth_headers())'
)

code = code.replace(
    'response = client.post("/api/sessions", params={"ttl_seconds": one_year_seconds})',
    'response = client.post("/api/sessions", params={"ttl_seconds": one_year_seconds}, headers=_auth_headers())'
)

with open(path, "w") as f:
    f.write(code)
