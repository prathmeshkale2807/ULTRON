"""
Calendar tools -- Phase 10 hardened.

All handlers receive ExecutionContext (server-created, immutable).
Timezone is validated against IANA. Attendee changes require ALWAYS_ASK.
Errors are sanitized.
"""
from __future__ import annotations

import datetime as _dt
from typing import Any
from zoneinfo import ZoneInfo as _ZoneInfo, ZoneInfoNotFoundError as _ZoneInfoNotFoundError

from app.core.logging_config import get_logger
from app.integrations.google_workspace import get_credentials
from app.tools.models import (
    ExecutionContext,
    ConfirmationTier,
    DeviceType,
    PermissionCategory,
    ToolDefinition,
)

logger = get_logger("tools.calendar")

_CAL_READONLY = ["https://www.googleapis.com/auth/calendar.readonly"]
_CAL_EVENTS = ["https://www.googleapis.com/auth/calendar.events"]


def _safe_error(operation: str, exc: Exception) -> dict[str, Any]:
    logger.error("Calendar operation '%s' failed: %s", operation, exc, exc_info=True)
    error_type = type(exc).__name__
    if "credentials" in str(exc).lower() or "oauth" in str(exc).lower():
        return {"success": False, "error": f"Authentication error during {operation}. Please reconnect Google Workspace."}
    if "HttpError" in error_type:
        return {"success": False, "error": f"Google API rejected the {operation} request."}
    return {"success": False, "error": f"{operation} failed. Check logs for details."}


def _validate_timezone(tz: str) -> str | None:
    """Return tz if it is a valid IANA timezone identifier, else None.

    Uses ZoneInfo() directly rather than available_timezones() because the
    latter returns an empty set on Windows without the tzdata package.
    """
    try:
        _ZoneInfo(tz)
        return tz
    except (_ZoneInfoNotFoundError, KeyError):
        return None


def _get_calendar_service(principal_id: str, scopes: list[str]):
    from googleapiclient.discovery import build
    creds = get_credentials(principal_id, scopes)
    if not creds:
        raise ValueError("No Google OAuth credentials. Please connect Google Workspace first.")
    return build("calendar", "v3", credentials=creds)


async def calendar_list_handler(ctx: ExecutionContext, args: dict[str, Any]) -> dict[str, Any]:
    try:
        service = _get_calendar_service(ctx.principal_id, _CAL_READONLY)
        now = _dt.datetime.now(_dt.timezone.utc).isoformat()
        events_result = service.events().list(
            calendarId='primary', timeMin=now,
            maxResults=args.get("max_results", 10), singleEvents=True, orderBy='startTime',
        ).execute()
        events = events_result.get('items', [])
        output = []
        for event in events:
            start = event['start'].get('dateTime', event['start'].get('date'))
            output.append({"id": event['id'], "summary": event.get('summary', 'No Title'),
                          "start": start, "timezone": event['start'].get('timeZone', 'unknown')})
        return {"success": True, "events": output}
    except Exception as e:
        return _safe_error("calendar_list", e)


async def calendar_get_event_handler(ctx: ExecutionContext, args: dict[str, Any]) -> dict[str, Any]:
    try:
        service = _get_calendar_service(ctx.principal_id, _CAL_READONLY)
        event_id = args["event_id"]
        event = service.events().get(calendarId='primary', eventId=event_id).execute()
        desc = event.get('description', '')
        formatted = f"--- UNTRUSTED_EXTERNAL_CONTENT START ---\n{desc}\n--- UNTRUSTED_EXTERNAL_CONTENT END ---"
        return {"success": True, "source": "calendar", "is_untrusted_data": True,
                "id": event_id, "summary": event.get('summary'),
                "description": formatted, "start": event.get('start'),
                "end": event.get('end'), "attendees": event.get('attendees', [])}
    except Exception as e:
        return _safe_error("calendar_get_event", e)


async def calendar_search_handler(ctx: ExecutionContext, args: dict[str, Any]) -> dict[str, Any]:
    try:
        service = _get_calendar_service(ctx.principal_id, _CAL_READONLY)
        query = args["query"]
        events_result = service.events().list(
            calendarId='primary', q=query, maxResults=args.get("max_results", 10),
            singleEvents=True, orderBy='startTime',
        ).execute()
        events = events_result.get('items', [])
        output = []
        for event in events:
            start = event['start'].get('dateTime', event['start'].get('date'))
            output.append({"id": event['id'], "summary": event.get('summary', 'No Title'),
                          "start": start, "timezone": event['start'].get('timeZone', 'unknown')})
        return {"success": True, "events": output}
    except Exception as e:
        return _safe_error("calendar_search", e)


async def calendar_create_event_handler(ctx: ExecutionContext, args: dict[str, Any]) -> dict[str, Any]:
    try:
        tz = args.get("timezone")
        if not tz:
            return {"success": False, "error": "timezone is required. Provide a valid IANA timezone (e.g. 'America/New_York')."}
        if _validate_timezone(tz) is None:
            return {"success": False, "error": f"Invalid timezone '{tz}'. Use a valid IANA timezone identifier."}
        service = _get_calendar_service(ctx.principal_id, _CAL_EVENTS)
        event_body = {
            'summary': args.get('summary', ''), 'description': args.get('description', ''),
            'start': {'dateTime': args['start_time'], 'timeZone': tz},
            'end': {'dateTime': args['end_time'], 'timeZone': tz},
        }
        if args.get('attendees'):
            event_body['attendees'] = [{'email': e} for e in args['attendees']]
        event = service.events().insert(calendarId='primary', body=event_body).execute()
        verified = service.events().get(calendarId='primary', eventId=event['id']).execute()
        return {"success": True, "event_id": verified['id'], "start": verified['start'], "status": "verified"}
    except Exception as e:
        return _safe_error("calendar_create_event", e)


async def calendar_update_event_handler(ctx: ExecutionContext, args: dict[str, Any]) -> dict[str, Any]:
    try:
        service = _get_calendar_service(ctx.principal_id, _CAL_EVENTS)
        event_id = args["event_id"]
        event = service.events().get(calendarId='primary', eventId=event_id).execute()
        if "summary" in args:
            event['summary'] = args["summary"]
        if "start_time" in args:
            tz = args.get("timezone")
            if not tz or _validate_timezone(tz) is None:
                return {"success": False, "error": "Valid IANA timezone required when changing times."}
            event['start']['dateTime'] = args["start_time"]
            event['start']['timeZone'] = tz
        if "end_time" in args:
            tz = args.get("timezone")
            if not tz or _validate_timezone(tz) is None:
                return {"success": False, "error": "Valid IANA timezone required when changing times."}
            event['end']['dateTime'] = args["end_time"]
            event['end']['timeZone'] = tz
        if "attendees" in args:
            event['attendees'] = [{'email': e} for e in args["attendees"]]
        service.events().update(calendarId='primary', eventId=event_id, body=event).execute()
        verified = service.events().get(calendarId='primary', eventId=event_id).execute()
        return {"success": True, "event_id": verified['id'], "status": "updated_and_verified"}
    except Exception as e:
        return _safe_error("calendar_update_event", e)


async def calendar_cancel_event_handler(ctx: ExecutionContext, args: dict[str, Any]) -> dict[str, Any]:
    try:
        service = _get_calendar_service(ctx.principal_id, _CAL_EVENTS)
        event_id = args["event_id"]
        service.events().delete(calendarId='primary', eventId=event_id).execute()
        try:
            service.events().get(calendarId='primary', eventId=event_id).execute()
            return {"success": False, "error": "Event still exists after deletion."}
        except Exception:
            pass
        return {"success": True, "event_id": event_id, "status": "cancelled_verified"}
    except Exception as e:
        return _safe_error("calendar_cancel_event", e)


CALENDAR_TOOLS = [
    ToolDefinition(
        name="calendar_list", description="List upcoming calendar events.",
        input_schema={"type": "object", "properties": {
            "max_results": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10},
        }, "additionalProperties": False},
        output_schema={"type": "object"}, risk_level="low",
        permission_category=PermissionCategory.CALENDAR_READ,
        confirmation_tier=ConfirmationTier.AUTOMATIC,
        allowed_devices=[DeviceType.PC], handler=calendar_list_handler,
    ),
    ToolDefinition(
        name="calendar_get_event", description="Get calendar event details.",
        input_schema={"type": "object", "properties": {
            "event_id": {"type": "string", "minLength": 1},
        }, "required": ["event_id"], "additionalProperties": False},
        output_schema={"type": "object"}, risk_level="low",
        permission_category=PermissionCategory.CALENDAR_READ,
        confirmation_tier=ConfirmationTier.AUTOMATIC,
        allowed_devices=[DeviceType.PC], handler=calendar_get_event_handler,
    ),
    ToolDefinition(
        name="calendar_search", description="Search for calendar events.",
        input_schema={"type": "object", "properties": {
            "query": {"type": "string", "minLength": 1},
            "max_results": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10},
        }, "required": ["query"], "additionalProperties": False},
        output_schema={"type": "object"}, risk_level="low",
        permission_category=PermissionCategory.CALENDAR_READ,
        confirmation_tier=ConfirmationTier.AUTOMATIC,
        allowed_devices=[DeviceType.PC], handler=calendar_search_handler,
    ),
    ToolDefinition(
        name="calendar_create_event",
        description="Create a calendar event. Requires IANA timezone. May invite attendees.",
        input_schema={"type": "object", "properties": {
            "summary": {"type": "string"}, "description": {"type": "string"},
            "start_time": {"type": "string", "description": "ISO 8601 datetime"},
            "end_time": {"type": "string", "description": "ISO 8601 datetime"},
            "timezone": {"type": "string", "minLength": 1, "description": "IANA timezone ID"},
            "attendees": {"type": "array", "items": {"type": "string", "format": "email"}},
        }, "required": ["summary", "start_time", "end_time", "timezone"], "additionalProperties": False},
        output_schema={"type": "object"}, risk_level="high",
        permission_category=PermissionCategory.CALENDAR_CREATE,
        confirmation_tier=ConfirmationTier.ALWAYS_ASK,
        allowed_devices=[DeviceType.PC], handler=calendar_create_event_handler,
    ),
    ToolDefinition(
        name="calendar_update_event", description="Update an existing calendar event.",
        input_schema={"type": "object", "properties": {
            "event_id": {"type": "string", "minLength": 1},
            "summary": {"type": "string"}, "start_time": {"type": "string"},
            "end_time": {"type": "string"}, "timezone": {"type": "string"},
            "attendees": {"type": "array", "items": {"type": "string", "format": "email"}},
        }, "required": ["event_id"], "additionalProperties": False},
        output_schema={"type": "object"}, risk_level="high",
        permission_category=PermissionCategory.CALENDAR_MODIFY,
        confirmation_tier=ConfirmationTier.ALWAYS_ASK,
        allowed_devices=[DeviceType.PC], handler=calendar_update_event_handler,
    ),
    ToolDefinition(
        name="calendar_cancel_event", description="Cancel or delete a calendar event.",
        input_schema={"type": "object", "properties": {
            "event_id": {"type": "string", "minLength": 1},
        }, "required": ["event_id"], "additionalProperties": False},
        output_schema={"type": "object"}, risk_level="high",
        permission_category=PermissionCategory.CALENDAR_CANCEL,
        confirmation_tier=ConfirmationTier.ALWAYS_ASK,
        allowed_devices=[DeviceType.PC], handler=calendar_cancel_event_handler,
    ),
]
