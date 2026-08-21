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

logger = get_logger("tools.calendar")

def _get_calendar_service(principal_id: str, scopes: List[str]):
    creds = get_credentials(principal_id, scopes)
    if not creds:
        raise ValueError("Missing or insufficient Google OAuth credentials.")
    return build("calendar", "v3", credentials=creds)

async def calendar_list_handler(args: dict[str, Any]) -> dict[str, Any]:
    try:
        principal_id = args.get("_principal_id", "local")
        service = _get_calendar_service(principal_id, ["https://www.googleapis.com/auth/calendar.readonly"])
        now = datetime.datetime.utcnow().isoformat() + 'Z'
        events_result = service.events().list(
            calendarId='primary', timeMin=now,
            maxResults=args.get("max_results", 10), singleEvents=True,
            orderBy='startTime'
        ).execute()
        events = events_result.get('items', [])
        
        output = []
        for event in events:
            start = event['start'].get('dateTime', event['start'].get('date'))
            output.append({
                "id": event['id'],
                "summary": event.get('summary', 'No Title'),
                "start": start,
                "timezone": event['start'].get('timeZone', 'UTC')
            })
            
        return {"success": True, "events": output}
    except Exception as e:
        return {"success": False, "error": str(e)}

async def calendar_get_event_handler(args: dict[str, Any]) -> dict[str, Any]:
    try:
        principal_id = args.get("_principal_id", "local")
        service = _get_calendar_service(principal_id, ["https://www.googleapis.com/auth/calendar.readonly"])
        event_id = args.get("event_id")
        event = service.events().get(calendarId='primary', eventId=event_id).execute()
        
        desc = event.get('description', '')
        formatted_desc = f"--- UNTRUSTED_EXTERNAL_CONTENT START ---\n{desc}\n--- UNTRUSTED_EXTERNAL_CONTENT END ---"
        
        return {
            "success": True,
            "source": "calendar",
            "is_untrusted_data": True,
            "id": event_id,
            "summary": event.get('summary'),
            "description": formatted_desc,
            "start": event.get('start'),
            "end": event.get('end'),
            "attendees": event.get('attendees', [])
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

async def calendar_search_handler(args: dict[str, Any]) -> dict[str, Any]:
    try:
        principal_id = args.get("_principal_id", "local")
        service = _get_calendar_service(principal_id, ["https://www.googleapis.com/auth/calendar.readonly"])
        query = args.get("query", "")
        events_result = service.events().list(
            calendarId='primary', q=query,
            maxResults=args.get("max_results", 10), singleEvents=True,
            orderBy='startTime'
        ).execute()
        events = events_result.get('items', [])
        
        output = []
        for event in events:
            start = event['start'].get('dateTime', event['start'].get('date'))
            output.append({
                "id": event['id'],
                "summary": event.get('summary', 'No Title'),
                "start": start,
                "timezone": event['start'].get('timeZone', 'UTC')
            })
            
        return {"success": True, "events": output}
    except Exception as e:
        return {"success": False, "error": str(e)}

async def calendar_create_event_handler(args: dict[str, Any]) -> dict[str, Any]:
    try:
        principal_id = args.get("_principal_id", "local")
        service = _get_calendar_service(principal_id, ["https://www.googleapis.com/auth/calendar.events"])
        
        timezone = args.get("timezone", "UTC")
        event_body = {
            'summary': args.get('summary', ''),
            'description': args.get('description', ''),
            'start': {
                'dateTime': args.get('start_time'),
                'timeZone': timezone,
            },
            'end': {
                'dateTime': args.get('end_time'),
                'timeZone': timezone,
            },
            'attendees': [{'email': email} for email in args.get('attendees', [])]
        }
        
        event = service.events().insert(calendarId='primary', body=event_body).execute()
        
        verified = service.events().get(calendarId='primary', eventId=event['id']).execute()
        
        return {
            "success": True,
            "event_id": verified['id'], 
            "start": verified['start'],
            "status": "verified"
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

async def calendar_update_event_handler(args: dict[str, Any]) -> dict[str, Any]:
    try:
        principal_id = args.get("_principal_id", "local")
        service = _get_calendar_service(principal_id, ["https://www.googleapis.com/auth/calendar.events"])
        event_id = args.get("event_id")
        
        event = service.events().get(calendarId='primary', eventId=event_id).execute()
        
        if "summary" in args:
            event['summary'] = args["summary"]
        if "start_time" in args:
            event['start']['dateTime'] = args["start_time"]
            if "timezone" in args: event['start']['timeZone'] = args["timezone"]
        if "end_time" in args:
            event['end']['dateTime'] = args["end_time"]
            if "timezone" in args: event['end']['timeZone'] = args["timezone"]
        if "attendees" in args:
            event['attendees'] = [{'email': email} for email in args["attendees"]]
            
        updated_event = service.events().update(calendarId='primary', eventId=event_id, body=event).execute()
        
        verified = service.events().get(calendarId='primary', eventId=event_id).execute()
        
        return {"success": True, "event_id": verified['id'], "status": "updated_and_verified"}
    except Exception as e:
        return {"success": False, "error": str(e)}

async def calendar_cancel_event_handler(args: dict[str, Any]) -> dict[str, Any]:
    try:
        principal_id = args.get("_principal_id", "local")
        service = _get_calendar_service(principal_id, ["https://www.googleapis.com/auth/calendar.events"])
        event_id = args.get("event_id")
        
        service.events().delete(calendarId='primary', eventId=event_id).execute()
        
        try:
            service.events().get(calendarId='primary', eventId=event_id).execute()
            return {"success": False, "error": "Event still exists after deletion."}
        except HttpError as err:
            if err.resp.status == 404 or err.resp.status == 410:
                pass 
            else:
                raise
                
        return {"success": True, "event_id": event_id, "status": "cancelled_verified"}
    except Exception as e:
        return {"success": False, "error": str(e)}

CALENDAR_TOOLS = [
    ToolDefinition(
        name="calendar_list",
        description="List upcoming calendar events.",
        input_schema={"type": "object"}, output_schema={"type": "object"},
        risk_level="low",
        permission_category=PermissionCategory.CALENDAR_READ,
        confirmation_tier=ConfirmationTier.AUTOMATIC,
        allowed_devices=[DeviceType.PC],
        handler=calendar_list_handler
    ),
    ToolDefinition(
        name="calendar_get_event",
        description="Get calendar event details.",
        input_schema={"type": "object"}, output_schema={"type": "object"},
        risk_level="low",
        permission_category=PermissionCategory.CALENDAR_READ,
        confirmation_tier=ConfirmationTier.AUTOMATIC,
        allowed_devices=[DeviceType.PC],
        handler=calendar_get_event_handler
    ),
    ToolDefinition(
        name="calendar_search",
        description="Search for calendar events.",
        input_schema={"type": "object"}, output_schema={"type": "object"},
        risk_level="low",
        permission_category=PermissionCategory.CALENDAR_READ,
        confirmation_tier=ConfirmationTier.AUTOMATIC,
        allowed_devices=[DeviceType.PC],
        handler=calendar_search_handler
    ),
    ToolDefinition(
        name="calendar_create_event",
        description="Create a calendar event. Requires appropriate timezone.",
        input_schema={"type": "object"}, output_schema={"type": "object"},
        risk_level="medium",
        permission_category=PermissionCategory.CALENDAR_CREATE,
        confirmation_tier=ConfirmationTier.ASK_ONCE_PER_SESSION,
        allowed_devices=[DeviceType.PC],
        handler=calendar_create_event_handler
    ),
    ToolDefinition(
        name="calendar_update_event",
        description="Update an existing calendar event (e.g. changing attendees).",
        input_schema={"type": "object"}, output_schema={"type": "object"},
        risk_level="high",
        permission_category=PermissionCategory.CALENDAR_MODIFY,
        confirmation_tier=ConfirmationTier.ALWAYS_ASK,
        allowed_devices=[DeviceType.PC],
        handler=calendar_update_event_handler
    ),
    ToolDefinition(
        name="calendar_cancel_event",
        description="Cancel or delete a calendar event.",
        input_schema={"type": "object"}, output_schema={"type": "object"},
        risk_level="high",
        permission_category=PermissionCategory.CALENDAR_CANCEL,
        confirmation_tier=ConfirmationTier.ALWAYS_ASK,
        allowed_devices=[DeviceType.PC],
        handler=calendar_cancel_event_handler
    )
]
