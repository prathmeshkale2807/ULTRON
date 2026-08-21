import pytest
from unittest.mock import patch, MagicMock
from app.tools.calendar import calendar_get_event_handler, calendar_create_event_handler

@pytest.fixture
def mock_service():
    with patch("app.tools.calendar._get_calendar_service") as mock_get_service:
        service = MagicMock()
        mock_get_service.return_value = service
        yield service

@pytest.mark.asyncio
async def test_calendar_get_event_untrusted_content(mock_service):
    event_mock = MagicMock()
    event_mock.execute.return_value = {
        "id": "event_123",
        "summary": "Meeting",
        "description": "Malicious payload here"
    }
    mock_service.events().get.return_value = event_mock
    
    result = await calendar_get_event_handler({"event_id": "event_123", "_principal_id": "user1"})
    
    assert result.get("success") is True
    assert result.get("is_untrusted_data") is True
    assert "UNTRUSTED_EXTERNAL_CONTENT START" in result.get("description")
    assert "Malicious payload here" in result.get("description")

@pytest.mark.asyncio
async def test_calendar_create_event_timezone(mock_service):
    insert_mock = MagicMock()
    insert_mock.execute.return_value = {"id": "new_event_123"}
    mock_service.events().insert.return_value = insert_mock
    
    get_mock = MagicMock()
    get_mock.execute.return_value = {"id": "new_event_123", "start": {"dateTime": "2023-10-10T10:00:00", "timeZone": "America/New_York"}}
    mock_service.events().get.return_value = get_mock
    
    args = {
        "summary": "Team Sync",
        "start_time": "2023-10-10T10:00:00",
        "end_time": "2023-10-10T11:00:00",
        "timezone": "America/New_York",
        "_principal_id": "user1"
    }
    
    result = await calendar_create_event_handler(args)
    
    assert result.get("success") is True
    assert result.get("event_id") == "new_event_123"
    assert result.get("status") == "verified"
    
    # Check that insert was called with the timezone
    called_body = mock_service.events().insert.call_args[1]["body"]
    assert called_body["start"]["timeZone"] == "America/New_York"
    assert called_body["end"]["timeZone"] == "America/New_York"
