from typing import Any, Dict, List
import datetime
import asyncio
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from app.integrations.google_workspace import get_credentials
from app.tools.models import (
    ToolDefinition,
    ToolHandler,
    PermissionCategory,
    ConfirmationTier,
    DeviceType,
)
from app.core.logging_config import get_logger

logger = get_logger("tools.email")

# In-memory deduplication cache: idempotency_key -> message_id
_email_send_dedup: Dict[str, str] = {}

def _get_gmail_service(principal_id: str, scopes: List[str]):
    creds = get_credentials(principal_id, scopes)
    if not creds:
        raise ValueError("Missing or insufficient Google OAuth credentials.")
    return build("gmail", "v1", credentials=creds)

async def email_list_handler(args: dict[str, Any]) -> dict[str, Any]:
    try:
        principal_id = args.get("_principal_id", "local")
        service = _get_gmail_service(principal_id, ["https://www.googleapis.com/auth/gmail.readonly"])
        
        # In a real app we'd await an executor or use aiogoogle, but for the mock this is fine.
        results = service.users().messages().list(userId='me', maxResults=args.get("max_results", 10), labelIds=args.get("labels")).execute()
        messages = results.get('messages', [])
        
        output = []
        for msg in messages:
            msg_data = service.users().messages().get(userId='me', id=msg['id'], format='metadata', metadataHeaders=['Subject', 'From', 'Date']).execute()
            headers = msg_data.get('payload', {}).get('headers', [])
            meta = {h['name']: h['value'] for h in headers}
            output.append({
                "id": msg['id'],
                "thread_id": msg_data.get('threadId'),
                "subject": meta.get('Subject', 'No Subject'),
                "from": meta.get('From', 'Unknown'),
                "date": meta.get('Date', 'Unknown')
            })
            
        return {"success": True, "messages": output}
    except Exception as e:
        return {"success": False, "error": str(e)}

async def email_read_handler(args: dict[str, Any]) -> dict[str, Any]:
    try:
        principal_id = args.get("_principal_id", "local")
        service = _get_gmail_service(principal_id, ["https://www.googleapis.com/auth/gmail.readonly"])
        msg_id = args.get("message_id")
        msg = service.users().messages().get(userId='me', id=msg_id, format='full').execute()
        
        snippet = msg.get('snippet', '')
        formatted_content = f"--- UNTRUSTED_EXTERNAL_CONTENT START ---\n{snippet}\n--- UNTRUSTED_EXTERNAL_CONTENT END ---"
        
        return {
            "success": True,
            "source": "email",
            "is_untrusted_data": True,
            "message_id": msg_id,
            "content": formatted_content
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

async def email_search_handler(args: dict[str, Any]) -> dict[str, Any]:
    try:
        principal_id = args.get("_principal_id", "local")
        service = _get_gmail_service(principal_id, ["https://www.googleapis.com/auth/gmail.readonly"])
        query = args.get("query", "")
        results = service.users().messages().list(userId='me', q=query, maxResults=args.get("max_results", 10)).execute()
        
        messages = results.get('messages', [])
        output = []
        for msg in messages:
            msg_data = service.users().messages().get(userId='me', id=msg['id'], format='metadata', metadataHeaders=['Subject', 'From']).execute()
            headers = msg_data.get('payload', {}).get('headers', [])
            meta = {h['name']: h['value'] for h in headers}
            output.append({
                "id": msg['id'],
                "subject": meta.get('Subject', 'No Subject'),
                "from": meta.get('From', 'Unknown')
            })
            
        return {"success": True, "messages": output}
    except Exception as e:
        return {"success": False, "error": str(e)}

async def email_create_draft_handler(args: dict[str, Any]) -> dict[str, Any]:
    try:
        principal_id = args.get("_principal_id", "local")
        service = _get_gmail_service(principal_id, ["https://www.googleapis.com/auth/gmail.compose"])
        import base64
        from email.message import EmailMessage
        
        message = EmailMessage()
        message.set_content(args.get("body", ""))
        message['To'] = args.get("to", "")
        message['Subject'] = args.get("subject", "")
        
        encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
        create_message = {'message': {'raw': encoded_message}}
        
        draft = service.users().drafts().create(userId='me', body=create_message).execute()
        
        # Verify
        verified = service.users().drafts().get(userId='me', id=draft['id']).execute()
        
        return {"success": True, "draft_id": verified['id'], "status": "verified"}
    except Exception as e:
        return {"success": False, "error": str(e)}

async def email_send_handler(args: dict[str, Any]) -> dict[str, Any]:
    try:
        principal_id = args.get("_principal_id", "local")
        idemp_key = f"{principal_id}_{args.get('idempotency_key', '')}"
        
        if args.get('idempotency_key') and idemp_key in _email_send_dedup:
            return {"success": True, "message_id": _email_send_dedup[idemp_key], "status": "deduplicated"}
            
        service = _get_gmail_service(principal_id, ["https://www.googleapis.com/auth/gmail.send"])
        
        draft_id = args.get("draft_id")
        if draft_id:
            sent = service.users().drafts().send(userId='me', body={'id': draft_id}).execute()
        else:
            import base64
            from email.message import EmailMessage
            message = EmailMessage()
            message.set_content(args.get("body", ""))
            message['To'] = args.get("to", "")
            if args.get("cc"): message['Cc'] = args.get("cc")
            if args.get("bcc"): message['Bcc'] = args.get("bcc")
            message['Subject'] = args.get("subject", "")
            
            encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
            sent = service.users().messages().send(userId='me', body={'raw': encoded_message}).execute()
            
        if args.get('idempotency_key'):
            _email_send_dedup[idemp_key] = sent['id']
            
        return {"success": True, "message_id": sent['id'], "status": "verified"}
    except Exception as e:
        return {"success": False, "error": str(e)}

async def email_archive_handler(args: dict[str, Any]) -> dict[str, Any]:
    try:
        principal_id = args.get("_principal_id", "local")
        service = _get_gmail_service(principal_id, ["https://www.googleapis.com/auth/gmail.modify"])
        msg_id = args.get("message_id")
        
        body = {'removeLabelIds': ['INBOX']}
        service.users().messages().modify(userId='me', id=msg_id, body=body).execute()
        
        msg = service.users().messages().get(userId='me', id=msg_id, format='minimal').execute()
        labels = msg.get('labelIds', [])
        if 'INBOX' in labels:
            return {"success": False, "error": "Failed to archive: INBOX label still present."}
            
        return {"success": True, "message_id": msg_id, "status": "archived"}
    except Exception as e:
        return {"success": False, "error": str(e)}

EMAIL_TOOLS = [
    ToolDefinition(
        name="email_list",
        description="Lists recent emails.",
        input_schema={"type": "object"}, output_schema={"type": "object"},
        risk_level="low",
        permission_category=PermissionCategory.EMAIL_READ,
        confirmation_tier=ConfirmationTier.AUTOMATIC,
        allowed_devices=[DeviceType.PC],
        handler=email_list_handler
    ),
    ToolDefinition(
        name="email_read",
        description="Reads the content of a specific email. Content is returned as untrusted data.",
        input_schema={"type": "object"}, output_schema={"type": "object"},
        risk_level="low",
        permission_category=PermissionCategory.EMAIL_READ,
        confirmation_tier=ConfirmationTier.AUTOMATIC,
        allowed_devices=[DeviceType.PC],
        handler=email_read_handler
    ),
    ToolDefinition(
        name="email_search",
        description="Search for emails using a query.",
        input_schema={"type": "object"}, output_schema={"type": "object"},
        risk_level="low",
        permission_category=PermissionCategory.EMAIL_READ,
        confirmation_tier=ConfirmationTier.AUTOMATIC,
        allowed_devices=[DeviceType.PC],
        handler=email_search_handler
    ),
    ToolDefinition(
        name="email_create_draft",
        description="Creates an email draft. Never sends automatically.",
        input_schema={"type": "object"}, output_schema={"type": "object"},
        risk_level="medium",
        permission_category=PermissionCategory.EMAIL_DRAFT,
        confirmation_tier=ConfirmationTier.AUTOMATIC,
        allowed_devices=[DeviceType.PC],
        handler=email_create_draft_handler
    ),
    ToolDefinition(
        name="email_send",
        description="Sends an email. HIGH IMPACT. Requires strict confirmation.",
        input_schema={"type": "object"}, output_schema={"type": "object"},
        risk_level="critical",
        permission_category=PermissionCategory.EMAIL_SEND,
        confirmation_tier=ConfirmationTier.ALWAYS_ASK,
        allowed_devices=[DeviceType.PC],
        handler=email_send_handler
    ),
    ToolDefinition(
        name="email_archive",
        description="Archives an email by removing the INBOX label.",
        input_schema={"type": "object"}, output_schema={"type": "object"},
        risk_level="medium",
        permission_category=PermissionCategory.EMAIL_MODIFY,
        confirmation_tier=ConfirmationTier.ASK_ONCE_PER_SESSION,
        allowed_devices=[DeviceType.PC],
        handler=email_archive_handler
    )
]
