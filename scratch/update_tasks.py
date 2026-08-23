with open("backend/app/api/tasks.py", "r") as f:
    content = f.read()

content = content.replace(
    "def _require_valid_session(session_id: str, db: Session) -> None:",
    "def _require_valid_session(session_id: str, db: Session, principal_id: str) -> None:"
)
content = content.replace(
    "if not SessionManager(db).is_valid(session_id):",
    "if not SessionManager(db).is_valid(session_id, principal_id):"
)
content = content.replace(
    "_require_valid_session(body.session_id, db)",
    "_require_valid_session(body.session_id, db, principal.identity)"
)

with open("backend/app/api/tasks.py", "w") as f:
    f.write(content)
