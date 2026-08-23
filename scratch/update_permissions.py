with open("backend/app/api/permissions.py", "r") as f:
    content = f.read()

content = content.replace(
    "def _require_valid_session_if_scoped(body: PermissionRequest, db: Session) -> None:",
    "def _require_valid_session_if_scoped(body: PermissionRequest, db: Session, principal_id: str) -> None:"
)
content = content.replace(
    "if not body.session_id or not SessionManager(db).is_valid(body.session_id):",
    "if not body.session_id or not SessionManager(db).is_valid(body.session_id, principal_id):"
)
content = content.replace(
    "_require_valid_session_if_scoped(body, db)",
    "_require_valid_session_if_scoped(body, db, principal.identity)"
)

with open("backend/app/api/permissions.py", "w") as f:
    f.write(content)
