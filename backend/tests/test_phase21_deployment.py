import pytest
import os
import sys
from pathlib import Path
from unittest.mock import patch

from app.core.config import Settings, get_default_data_dir
from app.core.database import schema_is_current

def test_localappdata_resolution_when_frozen():
    """Test that when sys.frozen is True, we resolve to LOCALAPPDATA."""
    with patch("sys.frozen", True, create=True), \
         patch.dict(os.environ, {"LOCALAPPDATA": "C:\\Users\\Test\\AppData\\Local"}):
        data_dir = get_default_data_dir()
        assert str(data_dir) == "C:\\Users\\Test\\AppData\\Local\\ULTRON\\data"

def test_localappdata_resolution_when_not_frozen():
    """Test that when sys.frozen is False, we use local ./data dir."""
    with patch("sys.frozen", False, create=True):
        data_dir = get_default_data_dir()
        assert data_dir.name == "data"
        assert "ULTRON" not in str(data_dir)

def test_schema_is_current():
    """Test the schema check returns a boolean."""
    assert isinstance(schema_is_current(), bool)

def test_env_exclusion_simulation():
    """Ensure that the build script explicitly removes/ignores .env (simulated by checking our code)"""
    build_script = Path(__file__).parents[1] / "build_windows.py"
    assert build_script.exists()
    content = build_script.read_text(encoding="utf-8")
    assert "--add-data" in content
    # .env shouldn't be added
    assert ".env" not in content
