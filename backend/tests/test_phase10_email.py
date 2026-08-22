import pytest
from unittest.mock import patch, MagicMock
from app.tools.email import email_read_handler, email_send_handler
from app.tools.models import ExecutionContext


def _ctx(principal="user1"):
    return ExecutionContext(principal_id=principal, session_id="sess1")


@pytest.fixture
def mock_service():
    with patch("app.tools.email._get_gmail_service") as mock_get_service:
        service = MagicMock()
        mock_get_service.return_value = service
        yield service


@pytest.mark.asyncio
async def test_email_read_untrusted_content(mock_service):
    msg_mock = MagicMock()
    msg_mock.execute.return_value = {"id": "123", "snippet": "Hello world!"}
    mock_service.users().messages().get.return_value = msg_mock
    result = await email_read_handler(_ctx(), {"message_id": "123"})
    assert result["success"] is True
    assert result["is_untrusted_data"] is True
    assert "UNTRUSTED_EXTERNAL_CONTENT START" in result["content"]


@pytest.mark.asyncio
async def test_email_send_requires_idempotency_key(mock_service):
    result = await email_send_handler(_ctx(), {"to": "x@y.com", "subject": "hi", "body": "test"})
    assert result["success"] is False
    assert "idempotency_key" in result["error"]


@pytest.mark.asyncio
async def test_email_send_persistent_idempotency(mock_service):
    from app.core.database import create_all_for_tests, SessionLocal, IdempotencyRecord
    create_all_for_tests()
    msg_mock = MagicMock()
    msg_mock.execute.return_value = {"id": "msg_sent_abc"}
    mock_service.users().messages().send.return_value = msg_mock
    args = {"to": "test@example.com", "subject": "Test", "body": "Hello", "idempotency_key": "key-persist-1"}
    result1 = await email_send_handler(_ctx(), args)
    assert result1["success"] is True
    result2 = await email_send_handler(_ctx(), args)
    assert result2["success"] is True
    assert result2["status"] == "deduplicated"
    db = SessionLocal()
    rec = db.get(IdempotencyRecord, "user1:key-persist-1")
    assert rec is not None
    assert rec.status == "completed"
    assert rec.provider_message_id == "msg_sent_abc"
    db.close()


@pytest.mark.asyncio
async def test_email_send_restart_safety():
    from app.core.database import create_all_for_tests, SessionLocal, IdempotencyRecord
    create_all_for_tests()
    db = SessionLocal()
    rec = IdempotencyRecord(
        idempotency_key="user1:key-crash-1", principal_id="user1",
        tool_name="email_send", request_fingerprint="abc", status="pending",
    )
    db.add(rec)
    db.commit()
    db.close()
    args = {"to": "test@example.com", "subject": "Test", "body": "Hello", "idempotency_key": "key-crash-1"}
    result = await email_send_handler(_ctx(), args)
    assert result["success"] is False
    assert "pending" in result.get("status", "") or "pending" in result.get("error", "").lower()


@pytest.mark.asyncio
async def test_email_error_sanitization():
    with patch("app.tools.email._get_gmail_service") as mock_get:
        mock_get.side_effect = Exception("oauth2client secret token=sk-xxx")
        result = await email_read_handler(_ctx(), {"message_id": "123"})
        assert result["success"] is False
        assert "sk-xxx" not in result["error"]
