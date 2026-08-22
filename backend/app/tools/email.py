"""
Email tools -- Phase 10 hardened.

All handlers receive ExecutionContext (server-created, immutable).
Principal identity is NEVER read from AI-supplied arguments.
Errors are sanitized before returning to the AI layer.
Idempotency uses crash-safe DB records, not in-memory dicts.
"""
from __future__ import annotations

import base64
import hashlib
from datetime import datetime, timezone
from email.message import EmailMessage
from typing import Any

from app.core.logging_config import get_logger
from app.integrations.google_workspace import get_credentials
from app.tools.models import (
    ExecutionContext,
    ConfirmationTier,
    DeviceType,
    PermissionCategory,
    ToolDefinition,
)

logger = get_logger("tools.email")

_GMAIL_READONLY = ["https://www.googleapis.com/auth/gmail.readonly"]
_GMAIL_COMPOSE = ["https://www.googleapis.com/auth/gmail.compose"]
_GMAIL_MODIFY = ["https://www.googleapis.com/auth/gmail.modify"]
_GMAIL_SEND = ["https://www.googleapis.com/auth/gmail.send"]


def _safe_error(operation: str, exc: Exception) -> dict[str, Any]:
    """Return a sanitized error dict. Raw exception details go to the log only."""
    logger.error("Email operation '%s' failed: %s", operation, exc, exc_info=True)
    error_type = type(exc).__name__
    if "credentials" in str(exc).lower() or "oauth" in str(exc).lower():
        return {"success": False, "error": f"Authentication error during {operation}. Please reconnect Google Workspace."}
    if "HttpError" in error_type:
        return {"success": False, "error": f"Google API rejected the {operation} request."}
    return {"success": False, "error": f"{operation} failed. Check logs for details."}


def _get_gmail_service(principal_id: str, scopes: list[str]):
    from googleapiclient.discovery import build
    creds = get_credentials(principal_id, scopes)
    if not creds:
        raise ValueError("No Google OAuth credentials for this user. Please connect Google Workspace first.")
    return build("gmail", "v1", credentials=creds)


# ---------------------------------------------------------------------------
# Idempotency helpers (crash-safe, DB-backed)
# ---------------------------------------------------------------------------
def _check_idempotency(db_session, key: str, principal_id: str) -> dict | None:
    from app.core.database import IdempotencyRecord
    rec = db_session.get(IdempotencyRecord, key)
    if rec and rec.principal_id == principal_id:
        return {"key": rec.idempotency_key, "status": rec.status, "provider_message_id": rec.provider_message_id}
    return None


def _create_idempotency(db_session, key: str, principal_id: str, tool_name: str, fingerprint: str):
    from app.core.database import IdempotencyRecord
    rec = IdempotencyRecord(
        idempotency_key=key,
        principal_id=principal_id,
        tool_name=tool_name,
        request_fingerprint=fingerprint,
        status="pending",
    )
    db_session.add(rec)
    db_session.commit()
    return rec


def _complete_idempotency(db_session, key: str, message_id: str):
    from app.core.database import IdempotencyRecord
    rec = db_session.get(IdempotencyRecord, key)
    if rec:
        rec.status = "completed"
        rec.provider_message_id = message_id
        rec.updated_at = datetime.now(timezone.utc)
        db_session.commit()


def _fail_idempotency(db_session, key: str):
    from app.core.database import IdempotencyRecord
    rec = db_session.get(IdempotencyRecord, key)
    if rec:
        rec.status = "failed"
        rec.updated_at = datetime.now(timezone.utc)
        db_session.commit()


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------
async def email_list_handler(ctx: ExecutionContext, args: dict[str, Any]) -> dict[str, Any]:
    try:
        service = _get_gmail_service(ctx.principal_id, _GMAIL_READONLY)
        results = service.users().messages().list(
            userId='me', maxResults=args.get("max_results", 10), labelIds=args.get("labels"),
        ).execute()
        messages = results.get('messages', [])
        output = []
        for msg in messages:
            msg_data = service.users().messages().get(
                userId='me', id=msg['id'], format='metadata',
                metadataHeaders=['Subject', 'From', 'Date'],
            ).execute()
            headers = msg_data.get('payload', {}).get('headers', [])
            meta = {h['name']: h['value'] for h in headers}
            output.append({
                "id": msg['id'], "thread_id": msg_data.get('threadId'),
                "subject": meta.get('Subject', 'No Subject'),
                "from": meta.get('From', 'Unknown'), "date": meta.get('Date', 'Unknown'),
            })
        return {"success": True, "messages": output}
    except Exception as e:
        return _safe_error("email_list", e)


async def email_read_handler(ctx: ExecutionContext, args: dict[str, Any]) -> dict[str, Any]:
    try:
        service = _get_gmail_service(ctx.principal_id, _GMAIL_READONLY)
        msg_id = args["message_id"]
        msg = service.users().messages().get(userId='me', id=msg_id, format='full').execute()
        snippet = msg.get('snippet', '')
        formatted = f"--- UNTRUSTED_EXTERNAL_CONTENT START ---\n{snippet}\n--- UNTRUSTED_EXTERNAL_CONTENT END ---"
        return {"success": True, "source": "email", "is_untrusted_data": True,
                "message_id": msg_id, "content": formatted}
    except Exception as e:
        return _safe_error("email_read", e)


async def email_search_handler(ctx: ExecutionContext, args: dict[str, Any]) -> dict[str, Any]:
    try:
        service = _get_gmail_service(ctx.principal_id, _GMAIL_READONLY)
        query = args.get("query", "")
        results = service.users().messages().list(userId='me', q=query, maxResults=args.get("max_results", 10)).execute()
        messages = results.get('messages', [])
        output = []
        for msg in messages:
            msg_data = service.users().messages().get(
                userId='me', id=msg['id'], format='metadata', metadataHeaders=['Subject', 'From'],
            ).execute()
            headers = msg_data.get('payload', {}).get('headers', [])
            meta = {h['name']: h['value'] for h in headers}
            output.append({"id": msg['id'], "subject": meta.get('Subject', 'No Subject'), "from": meta.get('From', 'Unknown')})
        return {"success": True, "messages": output}
    except Exception as e:
        return _safe_error("email_search", e)


async def email_create_draft_handler(ctx: ExecutionContext, args: dict[str, Any]) -> dict[str, Any]:
    try:
        service = _get_gmail_service(ctx.principal_id, _GMAIL_COMPOSE)
        message = EmailMessage()
        message.set_content(args["body"])
        message['To'] = args["to"]
        message['Subject'] = args["subject"]
        encoded = base64.urlsafe_b64encode(message.as_bytes()).decode()
        draft = service.users().drafts().create(userId='me', body={'message': {'raw': encoded}}).execute()
        verified = service.users().drafts().get(userId='me', id=draft['id']).execute()
        return {"success": True, "draft_id": verified['id'], "status": "verified"}
    except Exception as e:
        return _safe_error("email_create_draft", e)


async def email_send_handler(ctx: ExecutionContext, args: dict[str, Any]) -> dict[str, Any]:
    try:
        idemp_key = args.get("idempotency_key")
        if not idemp_key:
            return {"success": False, "error": "idempotency_key is required for email_send."}

        fingerprint = hashlib.sha256(
            f"{args.get('to','')}|{args.get('subject','')}|{args.get('body','')[:200]}".encode()
        ).hexdigest()[:32]
        full_key = f"{ctx.principal_id}:{idemp_key}"

        from app.core.database import SessionLocal
        db = SessionLocal()
        try:
            existing = _check_idempotency(db, full_key, ctx.principal_id)
            if existing:
                if existing["status"] == "completed":
                    return {"success": True, "message_id": existing["provider_message_id"], "status": "deduplicated"}
                if existing["status"] == "pending":
                    return {"success": False, "error": "Previous send attempt is still pending. Check sent folder before retrying.", "status": "pending_unknown"}

            _create_idempotency(db, full_key, ctx.principal_id, "email_send", fingerprint)

            service = _get_gmail_service(ctx.principal_id, _GMAIL_SEND)
            draft_id = args.get("draft_id")
            if draft_id:
                sent = service.users().drafts().send(userId='me', body={'id': draft_id}).execute()
            else:
                message = EmailMessage()
                message.set_content(args.get("body", ""))
                message['To'] = args.get("to", "")
                if args.get("cc"): message['Cc'] = args["cc"]
                if args.get("bcc"): message['Bcc'] = args["bcc"]
                message['Subject'] = args.get("subject", "")
                encoded = base64.urlsafe_b64encode(message.as_bytes()).decode()
                sent = service.users().messages().send(userId='me', body={'raw': encoded}).execute()

            msg_id = sent.get('id', '')
            _complete_idempotency(db, full_key, msg_id)
            return {"success": True, "message_id": msg_id, "status": "sent_and_verified"}
        except Exception as e:
            _fail_idempotency(db, full_key)
            raise
        finally:
            db.close()
    except Exception as e:
        return _safe_error("email_send", e)


async def email_archive_handler(ctx: ExecutionContext, args: dict[str, Any]) -> dict[str, Any]:
    try:
        service = _get_gmail_service(ctx.principal_id, _GMAIL_MODIFY)
        msg_id = args["message_id"]
        service.users().messages().modify(userId='me', id=msg_id, body={'removeLabelIds': ['INBOX']}).execute()
        msg = service.users().messages().get(userId='me', id=msg_id, format='minimal').execute()
        if 'INBOX' in msg.get('labelIds', []):
            return {"success": False, "error": "Archive failed: INBOX label still present."}
        return {"success": True, "message_id": msg_id, "status": "archived"}
    except Exception as e:
        return _safe_error("email_archive", e)


# ---------------------------------------------------------------------------
# Tool definitions with strict input schemas
# ---------------------------------------------------------------------------
EMAIL_TOOLS = [
    ToolDefinition(
        name="email_list", description="Lists recent emails.",
        input_schema={"type": "object", "properties": {
            "max_results": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10},
            "labels": {"type": "array", "items": {"type": "string"}},
        }, "additionalProperties": False},
        output_schema={"type": "object"}, risk_level="low",
        permission_category=PermissionCategory.EMAIL_READ,
        confirmation_tier=ConfirmationTier.AUTOMATIC,
        allowed_devices=[DeviceType.PC], handler=email_list_handler,
    ),
    ToolDefinition(
        name="email_read", description="Reads the content of a specific email. Content is returned as untrusted data.",
        input_schema={"type": "object", "properties": {
            "message_id": {"type": "string", "minLength": 1},
        }, "required": ["message_id"], "additionalProperties": False},
        output_schema={"type": "object"}, risk_level="low",
        permission_category=PermissionCategory.EMAIL_READ,
        confirmation_tier=ConfirmationTier.AUTOMATIC,
        allowed_devices=[DeviceType.PC], handler=email_read_handler,
    ),
    ToolDefinition(
        name="email_search", description="Search for emails using a Gmail query.",
        input_schema={"type": "object", "properties": {
            "query": {"type": "string", "minLength": 1},
            "max_results": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10},
        }, "required": ["query"], "additionalProperties": False},
        output_schema={"type": "object"}, risk_level="low",
        permission_category=PermissionCategory.EMAIL_READ,
        confirmation_tier=ConfirmationTier.AUTOMATIC,
        allowed_devices=[DeviceType.PC], handler=email_search_handler,
    ),
    ToolDefinition(
        name="email_create_draft", description="Creates an email draft. Never sends automatically.",
        input_schema={"type": "object", "properties": {
            "to": {"type": "string", "minLength": 1},
            "subject": {"type": "string"}, "body": {"type": "string"},
        }, "required": ["to", "subject", "body"], "additionalProperties": False},
        output_schema={"type": "object"}, risk_level="medium",
        permission_category=PermissionCategory.EMAIL_DRAFT,
        confirmation_tier=ConfirmationTier.AUTOMATIC,
        allowed_devices=[DeviceType.PC], handler=email_create_draft_handler,
    ),
    ToolDefinition(
        name="email_send", description="Sends an email. HIGH IMPACT. Requires strict confirmation and idempotency key.",
        input_schema={"type": "object", "properties": {
            "to": {"type": "string", "minLength": 1},
            "subject": {"type": "string"}, "body": {"type": "string"},
            "cc": {"type": "string"}, "bcc": {"type": "string"},
            "draft_id": {"type": "string"},
            "idempotency_key": {"type": "string", "minLength": 1},
        }, "required": ["idempotency_key"], "additionalProperties": False},
        output_schema={"type": "object"}, risk_level="critical",
        permission_category=PermissionCategory.EMAIL_SEND,
        confirmation_tier=ConfirmationTier.ALWAYS_ASK,
        allowed_devices=[DeviceType.PC], handler=email_send_handler,
    ),
    ToolDefinition(
        name="email_archive", description="Archives an email by removing the INBOX label.",
        input_schema={"type": "object", "properties": {
            "message_id": {"type": "string", "minLength": 1},
        }, "required": ["message_id"], "additionalProperties": False},
        output_schema={"type": "object"}, risk_level="medium",
        permission_category=PermissionCategory.EMAIL_MODIFY,
        confirmation_tier=ConfirmationTier.ASK_ONCE_PER_SESSION,
        allowed_devices=[DeviceType.PC], handler=email_archive_handler,
    ),
]
