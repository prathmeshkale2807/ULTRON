import os
import re

def fix_file(filepath):
    if not os.path.exists(filepath):
        print(f"Not found: {filepath}")
        return
    with open(filepath, 'r') as f:
        content = f.read()

    # Generic replace for manager.get()
    content = re.sub(r'manager\.get\(([^,]+),\s*session_id=([^)]+)\)', r'manager.get(\1, session_id=\2, principal_id="local")', content)
    # Generic replace for manager.list_tasks()
    content = re.sub(r'manager\.list_tasks\(\s*session_id=([^)]+)\)', r'manager.list_tasks(session_id=\1, principal_id="local")', content)
    # Generic replace for manager.cancel()
    content = re.sub(r'manager\.cancel\(([^,]+),\s*session_id=([^,]+),\s*actor=([^)]+)\)', r'manager.cancel(\1, session_id=\2, principal_id="local", actor=\3)', content)
    # Generic replace for manager.pause()
    content = re.sub(r'manager\.pause\(([^,]+),\s*session_id=([^,]+),\s*actor=([^)]+)\)', r'manager.pause(\1, session_id=\2, principal_id="local", actor=\3)', content)
    # Generic replace for manager.resume()
    content = re.sub(r'manager\.resume\(([^,]+),\s*session_id=([^,]+),\s*actor=([^)]+)\)', r'manager.resume(\1, session_id=\2, principal_id="local", actor=\3)', content)
    
    with open(filepath, 'w') as f:
        f.write(content)

for root, dirs, files in os.walk("tests"):
    for file in files:
        if file.endswith(".py"):
            fix_file(os.path.join(root, file))
