import pytest
from unittest.mock import patch, MagicMock
from app.tools.calendar import (
    calendar_get_event_handler, calendar_create_event_handler,
    calendar_update_event_handler, _validate_timezone,
)
from app.tools.models import ExecutionContext


def _ctx(principal="user1"):
    return ExecutionContext(principal_id=principal, session_id="sess1")


@pytest.fixture
def mock_service():
    with patch("app.tools.calendar._get_calendar_service") as mock_get_service:
        service = MagicMock()
        mock_get_service.return_value = service
        yield service


@pytest.mark.asyncio
async def test_calendar_get_event_untrusted_content(mock_service):
    event_mock = MagicMock()
    event_mock.execute.return_value = {"id": "event_123", "summary": "Meeting", "description": "Malicious payload here"}
    mock_service.events().get.return_value = event_mock
    result = await calendar_get_event_handler(_ctx(), {"event_id": "event_123"})
    assert result["success"] is True
    assert result["is_untrusted_data"] is True
    assert "UNTRUSTED_EXTERNAL_CONTENT START" in result["description"]


@pytest.mark.asyncio
async def test_calendar_create_event_timezone(mock_service):
    insert_mock = MagicMock()
    insert_mock.execute.return_value = {"id": "new_event_123"}
    mock_service.events().insert.return_value = insert_mock
    get_mock = MagicMock()
    get_mock.execute.return_value = {"id": "new_event_123", "start": {"dateTime": "2023-10-10T10:00:00", "timeZone": "America/New_York"}}
    mock_service.events().get.return_value = get_mock
    args = {"summary": "Team Sync", "start_time": "2023-10-10T10:00:00",
            "end_time": "2023-10-10T11:00:00", "timezone": "America/New_York"}
    result = await calendar_create_event_handler(_ctx(), args)
    assert result["success"] is True
    assert result["event_id"] == "new_event_123"
    called_body = mock_service.events().insert.call_args[1]["body"]
    assert called_body["start"]["timeZone"] == "America/New_York"


@pytest.mark.asyncio
async def test_calendar_rejects_missing_timezone(mock_service):
    args = {"summary": "X", "start_time": "2023-10-10T10:00:00", "end_time": "2023-10-10T11:00:00"}
    result = await calendar_create_event_handler(_ctx(), args)
    assert result["success"] is False
    assert "timezone" in result["error"].lower()


@pytest.mark.asyncio
async def test_calendar_rejects_invalid_timezone(mock_service):
    args = {"summary": "X", "start_time": "2023-10-10T10:00:00",
            "end_time": "2023-10-10T11:00:00", "timezone": "Mars/Olympus_Mons"}
    result = await calendar_create_event_handler(_ctx(), args)
    assert result["success"] is False
    assert "invalid" in result["error"].lower() or "timezone" in result["error"].lower()


def test_validate_timezone():
    assert _validate_timezone("America/New_York") == "America/New_York"
    assert _validate_timezone("UTC") == "UTC"
    assert _validate_timezone("Fake/Zone") is None


def test_calendar_create_event_always_ask():
    from app.tools.calendar import CALENDAR_TOOLS
    from app.tools.models import ConfirmationTier
    create_tool = next(t for t in CALENDAR_TOOLS if t.name == "calendar_create_event")
    assert create_tool.confirmation_tier == ConfirmationTier.ALWAYS_ASK


def test_calendar_update_event_always_ask():
    from app.tools.calendar import CALENDAR_TOOLS
    from app.tools.models import ConfirmationTier
    update_tool = next(t for t in CALENDAR_TOOLS if t.name == "calendar_update_event")
    assert update_tool.confirmation_tier == ConfirmationTier.ALWAYS_ASK


@pytest.mark.asyncio
async def test_calendar_error_sanitization():
    with patch("app.tools.calendar._get_calendar_service") as mock_get:
        mock_get.side_effect = Exception("internal oauth token=secret123")
        result = await calendar_get_event_handler(_ctx(), {"event_id": "x"})
        assert result["success"] is False
        assert "secret123" not in result["error"]
