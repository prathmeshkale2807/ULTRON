"""
Phase 10 Hardening regression tests.
"""
import pytest
from typing import Any
from app.tools.models import ExecutionContext, RESERVED_INTERNAL_KEYS, ConfirmationTier


def test_execution_context_is_immutable():
    ctx = ExecutionContext(principal_id="alice", session_id="s1")
    with pytest.raises(AttributeError):
        ctx.principal_id = "bob"


def test_execution_context_has_request_id():
    ctx = ExecutionContext(principal_id="alice")
    assert ctx.request_id
    ctx2 = ExecutionContext(principal_id="alice")
    assert ctx.request_id != ctx2.request_id


def test_reserved_internal_keys():
    assert "_principal_id" in RESERVED_INTERNAL_KEYS
    assert "_session_id" in RESERVED_INTERNAL_KEYS
    assert "_task_id" in RESERVED_INTERNAL_KEYS
    assert "_request_id" in RESERVED_INTERNAL_KEYS


def test_reserved_keys_are_stripped():
    ai_args = {"query": "hello", "_principal_id": "attacker", "_session_id": "evil", "_task_id": "x", "normal": "ok"}
    clean = {k: v for k, v in ai_args.items() if k not in RESERVED_INTERNAL_KEYS}
    assert "_principal_id" not in clean
    assert "_session_id" not in clean
    assert "_task_id" not in clean
    assert clean["query"] == "hello"
    assert clean["normal"] == "ok"


def test_email_send_is_always_ask():
    from app.tools.email import EMAIL_TOOLS
    send_tool = next(t for t in EMAIL_TOOLS if t.name == "email_send")
    assert send_tool.confirmation_tier == ConfirmationTier.ALWAYS_ASK


def test_email_schemas_have_additional_properties_false():
    from app.tools.email import EMAIL_TOOLS
    for tool in EMAIL_TOOLS:
        assert tool.input_schema.get("additionalProperties") is False, f"{tool.name}"


def test_calendar_schemas_have_additional_properties_false():
    from app.tools.calendar import CALENDAR_TOOLS
    for tool in CALENDAR_TOOLS:
        assert tool.input_schema.get("additionalProperties") is False, f"{tool.name}"


def test_calendar_create_requires_timezone_in_schema():
    from app.tools.calendar import CALENDAR_TOOLS
    create_tool = next(t for t in CALENDAR_TOOLS if t.name == "calendar_create_event")
    assert "timezone" in create_tool.input_schema.get("required", [])


def test_no_internal_fields_in_tool_schemas():
    from app.tools.email import EMAIL_TOOLS
    from app.tools.calendar import CALENDAR_TOOLS
    for tool in EMAIL_TOOLS + CALENDAR_TOOLS:
        props = tool.input_schema.get("properties", {})
        for reserved in RESERVED_INTERNAL_KEYS:
            assert reserved not in props, f"{tool.name} schema must not include {reserved}"
