import re

with open('backend/app/permissions/store.py', 'r') as f:
    content = f.read()

# Add principal_id: str to all write/read methods
content = content.replace("def grant(\n        self,\n        category", "def grant(\n        self,\n        principal_id: str,\n        category")
content = content.replace("def revoke(\n        self,\n        category", "def revoke(\n        self,\n        principal_id: str,\n        category")
content = content.replace("def _set(\n        self,\n        category", "def _set(\n        self,\n        principal_id: str,\n        category")
content = content.replace("def check(\n        self,\n        category", "def check(\n        self,\n        principal_id: str,\n        category")
content = content.replace("def _check_persistent(\n        self,\n        category", "def _check_persistent(\n        self,\n        principal_id: str,\n        category")
content = content.replace("def clear_session(self, session_id", "def clear_session(self, principal_id: str, session_id")

# Update _set calls
content = content.replace("self._set(category", "self._set(principal_id, category")
content = content.replace("PermissionRecord(\n                category=category.value,", "PermissionRecord(\n                principal_id=principal_id,\n                category=category.value,")

# Update check calls
content = content.replace("self._check_persistent(category", "self._check_persistent(principal_id, category")

# Update queries in _check_persistent
content = content.replace("select(PermissionRecord)\n                .where(PermissionRecord.category", "select(PermissionRecord)\n                .where(PermissionRecord.principal_id == principal_id)\n                .where(PermissionRecord.category")

with open('backend/app/permissions/store.py', 'w') as f:
    f.write(content)
