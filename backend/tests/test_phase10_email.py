import pytest
from unittest.mock import patch, MagicMock
from app.tools.email import email_read_handler, email_send_handler, _email_send_dedup

@pytest.fixture
def mock_service():
    with patch("app.tools.email._get_gmail_service") as mock_get_service:
        service = MagicMock()
        mock_get_service.return_value = service
        yield service

@pytest.mark.asyncio
async def test_email_read_untrusted_content(mock_service):
    # Mock the API response
    msg_mock = MagicMock()
    msg_mock.execute.return_value = {"id": "123", "snippet": "Hello world!"}
    mock_service.users().messages().get.return_value = msg_mock
    
    result = await email_read_handler({"message_id": "123", "_principal_id": "user1"})
    
    assert result.get("success") is True
    assert result.get("is_untrusted_data") is True
    assert "UNTRUSTED_EXTERNAL_CONTENT START" in result.get("content")
    assert "Hello world!" in result.get("content")

@pytest.mark.asyncio
async def test_email_send_idempotency(mock_service):
    # Mock the API response
    msg_mock = MagicMock()
    msg_mock.execute.return_value = {"id": "msg_sent_123"}
    mock_service.users().messages().send.return_value = msg_mock
    
    args = {
        "to": "test@example.com",
        "subject": "Test",
        "body": "Hello",
        "idempotency_key": "unique-uuid-1",
        "_principal_id": "user1"
    }
    
    # First send
    result1 = await email_send_handler(args)
    assert result1.get("success") is True
    assert result1.get("message_id") == "msg_sent_123"
    assert result1.get("status") == "verified"
    
    # Second send with same idempotency key
    result2 = await email_send_handler(args)
    assert result2.get("success") is True
    assert result2.get("message_id") == "msg_sent_123"
    assert result2.get("status") == "deduplicated"
    
    # Ensure API was only called once
    assert mock_service.users().messages().send.call_count == 1
