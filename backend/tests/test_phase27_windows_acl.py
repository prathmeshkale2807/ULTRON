import os
import pytest
import subprocess
from pathlib import Path
from app.core.config import get_settings
from app.core.acl import secure_directory_windows

@pytest.mark.skipif(os.name != 'nt', reason="Windows specific ACL test")
def test_windows_directory_acls(tmp_path):
    test_dir = tmp_path / "ULTRON_TEST"
    test_dir.mkdir()
    
    # Create some files inside to ensure inheritance works
    (test_dir / "ultron.db").touch()
    (test_dir / "ultron.db-wal").touch()
    (test_dir / "ultron.db-shm").touch()
    
    # Secure the directory
    secure_directory_windows(test_dir)
    
    # Verify using icacls
    result = subprocess.run(["icacls", str(test_dir)], capture_output=True, text=True, check=True)
    
    output = result.stdout
    # Output should not have Everyone or Users
    assert "Everyone" not in output
    assert "BUILTIN\\Users" not in output or "BUILTIN\\Users:(I)" not in output # Should not have inherited Users access
    
    # Verify that inheritance is disabled
    # When inheritance is disabled, icacls doesn't show (I) for the ACEs applied
    # Actually icacls just shows the explicitly granted users
    username = os.environ.get("USERNAME")
    assert username in output
    assert "SYSTEM" in output
    assert "Administrators" in output

    # Check that a file inherits
    file_result = subprocess.run(["icacls", str(test_dir / "ultron.db-wal")], capture_output=True, text=True, check=True)
    file_output = file_result.stdout
    assert username in file_output
