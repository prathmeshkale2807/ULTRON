import os
import re

def process_file(filepath):
    with open(filepath, 'r') as f:
        content = f.read()

    # Android /devices/ws
    content = re.sub(
        r'^(\s*)with client\.websocket_connect\((f?"/api/devices/ws\?device_id=\{?([^}&]+)\}?&credential=\{?([^}&]+)\}?")\)\s*(as [^:]+)?:',
        r'\1ticket_resp = client.post("/api/devices/ticket", json={"device_id": \3, "credential": \4})\n\1ticket = ticket_resp.json().get("ticket", "invalid")\n\1with client.websocket_connect(f"/api/devices/ws?ticket={ticket}") \5:',
        content,
        flags=re.MULTILINE
    )

    # Voice /voice/ws
    content = re.sub(
        r'^(\s*)with client\.websocket_connect\((f?"/api/voice/ws\?token=\{?([^}&]+)\}?")\)\s*(as [^:]+)?:',
        r'\1ticket_resp = client.post("/api/voice/ticket", headers={"X-Ultron-Auth": \3}, json={})\n\1ticket = ticket_resp.json().get("ticket", "invalid")\n\1with client.websocket_connect(f"/api/voice/ws?ticket={ticket}") \4:',
        content,
        flags=re.MULTILINE
    )
    
    content = re.sub(
        r'^(\s*)ws = client\.websocket_connect\((f?"/api/voice/ws\?token=\{?([^}&]+)\}?")\)',
        r'\1ticket_resp = client.post("/api/voice/ticket", headers={"X-Ultron-Auth": \3}, json={})\n\1ticket = ticket_resp.json().get("ticket", "invalid")\n\1ws = client.websocket_connect(f"/api/voice/ws?ticket={ticket}")',
        content,
        flags=re.MULTILINE
    )
    
    # Voice with device_id
    content = re.sub(
        r'^(\s*)with client\.websocket_connect\((f?"/api/voice/ws\?device_id=\{?([^}&]+)\}?&credential=\{?([^}&]+)\}?")\)\s*(as [^:]+)?:',
        r'\1ticket_resp = client.post("/api/voice/ticket", json={"device_id": \3, "credential": \4})\n\1ticket = ticket_resp.json().get("ticket", "invalid")\n\1with client.websocket_connect(f"/api/voice/ws?ticket={ticket}") \5:',
        content,
        flags=re.MULTILINE
    )
    
    with open(filepath, 'w') as f:
        f.write(content)

for root, dirs, files in os.walk("backend/tests"):
    for file in files:
        if file.endswith(".py"):
            process_file(os.path.join(root, file))
