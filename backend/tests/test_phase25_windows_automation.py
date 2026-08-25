import pytest
from app.windows.automation import (
    generate_snapshot, resolve_target, click_control, select_control, focus_window,
    StaleTargetError, SecurityError, AutomationError
)
import app.windows.automation as aut_mod

def test_generate_snapshot():
    snapshot = generate_snapshot()
    assert "snapshot_id" in snapshot
    assert "controls" in snapshot
    assert snapshot["window_title"] == "Calculator"

def test_resolve_target_success(monkeypatch):
    # Setup mock tree
    mock_tree = {
        "window_title": "Calculator",
        "application_name": "CalculatorApp",
        "controls": [
            {"control_id": "btn1", "name": "1"}
        ]
    }
    monkeypatch.setattr(aut_mod, "get_ui_tree", lambda: mock_tree)
    snapshot = generate_snapshot()
    snapshot_id = snapshot["snapshot_id"]
    
    control = resolve_target(snapshot_id, "btn1", "CalculatorApp", "Calculator")
    assert control["name"] == "1"

def test_stale_target_rejection_window_mismatch(monkeypatch):
    mock_tree = {
        "window_title": "Calculator",
        "application_name": "CalculatorApp",
        "controls": [
            {"control_id": "btn1", "name": "1"}
        ]
    }
    monkeypatch.setattr(aut_mod, "get_ui_tree", lambda: mock_tree)
    snapshot = generate_snapshot()
    snapshot_id = snapshot["snapshot_id"]
    
    # Now active window changes
    monkeypatch.setattr(aut_mod, "get_active_window_info", lambda: {
        "window_title": "Notepad",
        "application_name": "NotepadApp"
    })
    
    with pytest.raises(StaleTargetError, match="Active window mismatch"):
        resolve_target(snapshot_id, "btn1", "CalculatorApp", "Calculator")

def test_sensitive_field_protection(monkeypatch):
    mock_tree = {
        "window_title": "Login",
        "application_name": "LoginApp",
        "controls": [
            {"control_id": "fld1", "is_password": True}
        ]
    }
    monkeypatch.setattr(aut_mod, "get_ui_tree", lambda: mock_tree)
    monkeypatch.setattr(aut_mod, "get_active_window_info", lambda: {
        "window_title": "Login",
        "application_name": "LoginApp"
    })
    snapshot = generate_snapshot()
    snapshot_id = snapshot["snapshot_id"]
    
    with pytest.raises(SecurityError, match="sensitive"):
        resolve_target(snapshot_id, "fld1", "LoginApp", "Login")

def test_focus_window_allowlist():
    assert focus_window("notepad", "Untitled - Notepad") == True
    
    with pytest.raises(SecurityError, match="not in the focus allowlist"):
        focus_window("cmd.exe", "Command Prompt")
