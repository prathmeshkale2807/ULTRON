import re

path = "backend/tests/test_phase5_task_manager.py"
with open(path, "r") as f:
    code = f.read()

# Make sure we import _auth_headers
if "from tests.test_phase4_api_security import _auth_headers" not in code:
    code = code.replace("from fastapi.testclient import TestClient", "from fastapi.testclient import TestClient\n    from tests.test_phase4_api_security import _auth_headers")

# Replace _make_session
code = code.replace(
    'resp = client.post("/api/sessions")',
    'resp = client.post("/api/sessions", headers=_auth_headers())'
)

# For all test_api_* methods, add headers=_auth_headers() to client.get/post/patch where missing.
# Wait, let's just do it cleanly for specific ones.

tests = [
    "test_api_create_task_returns_201_style_200",
    "test_api_create_task_requires_valid_session",
    "test_api_get_task_own_session",
    "test_api_get_task_wrong_session_is_403",
    "test_api_list_tasks_returns_own_session_only",
    "test_api_cancel_task_transitions_to_cancelled",
    "test_api_cancel_task_wrong_session_is_403",
    "test_api_task_history_returns_audit_events",
    "test_api_task_history_wrong_session_is_403",
    "test_api_emergency_stop_cancels_queued_tasks",
    "test_api_task_pause_non_running_returns_409",
    "test_api_get_nonexistent_task_is_404"
]

# Simple heuristic: find 'client.post(', 'client.get(', 'client.patch('
# inside test methods and add headers=_auth_headers() inside the parens.
# E.g.
#    client.post(
#        "/api/tasks",
#        json={...},
#    )
# We can just match the closing `)` of the `client.something(` and insert `headers=_auth_headers()` before it.
# Actually, the AST is safer, but regex might work:

def add_headers(c):
    return re.sub(
        r'(client\.(?:post|get|patch)\([^)]+?)\s*\)',
        r'\1, headers=_auth_headers())',
        c
    )

# BUT we must skip test_api_create_task_requires_auth (it should fail 401 without auth)
# Let's split by 'def '
funcs = code.split('def ')
new_funcs = []
for f in funcs:
    if not f:
        continue
    name = f.split('(')[0]
    if name in tests:
        # replace client calls in this function
        f = add_headers(f)
    new_funcs.append(f)

code = 'def '.join(new_funcs)

with open(path, "w") as f:
    f.write(code)
