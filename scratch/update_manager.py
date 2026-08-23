with open("backend/app/sessions/manager.py", "r") as f:
    content = f.read()

content = content.replace("def create(self, *, ttl_seconds: float | None = DEFAULT_SESSION_TTL_SECONDS) -> SessionInfo:", "def create(self, principal_id: str, *, ttl_seconds: float | None = DEFAULT_SESSION_TTL_SECONDS) -> SessionInfo:")
content = content.replace("row = SessionRecord(\n            session_id=secrets.token_urlsafe(24),", "row = SessionRecord(\n            principal_id=principal_id,\n            session_id=secrets.token_urlsafe(24),")
content = content.replace("PermissionStore(self.db).clear_session(session_id)", "PermissionStore(self.db).clear_session(row.principal_id, session_id)")
content = content.replace("def is_valid(self, session_id: str) -> bool:", "def is_valid(self, session_id: str, principal_id: str | None = None) -> bool:")

with open("backend/app/sessions/manager.py", "w") as f:
    f.write(content)
