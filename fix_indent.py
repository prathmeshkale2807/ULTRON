path = "backend/tests/test_phase5_task_manager.py"
with open(path, "r") as f:
    code = f.read()

code = code.replace("\nfrom tests.test_phase4_api_security import _auth_headers", "\n    from tests.test_phase4_api_security import _auth_headers")

with open(path, "w") as f:
    f.write(code)
