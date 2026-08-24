import os
import subprocess
import shutil
from pathlib import Path

def build_backend():
    backend_dir = Path(__file__).parent.resolve()
    os.chdir(backend_dir)
    
    # Ensure dist and build dirs are clean
    shutil.rmtree(backend_dir / "dist", ignore_errors=True)
    shutil.rmtree(backend_dir / "build", ignore_errors=True)
    
    # Run PyInstaller
    # We use uvicorn to run our app module directly, but PyInstaller needs an entry point script.
    entry_script = backend_dir / "run_server.py"
    with open(entry_script, "w", encoding="utf-8") as f:
        f.write("import sys\n")
        f.write("if '--get-auth-token' in sys.argv:\n")
        f.write("    from app.security.local_auth import get_or_create_local_token\n")
        f.write("    print(get_or_create_local_token())\n")
        f.write("    sys.exit(0)\n")
        f.write("import uvicorn\n")
        f.write("from app.main import app\n")
        f.write("if __name__ == '__main__':\n")
        f.write("    uvicorn.run(app, host='127.0.0.1', port=8756)\n")

    import sys
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", "ultron-backend",
        "--onefile",
        "--collect-all", "app",
        "--add-data", f"alembic;alembic",
        "--add-data", f"alembic.ini;.",
        "--hidden-import", "app.api.automations",
        "--hidden-import", "app.api.confirmations",
        "--hidden-import", "app.api.conversations",
        "--hidden-import", "app.api.devices",
        "--hidden-import", "app.api.emergency",
        "--hidden-import", "app.api.google",
        "--hidden-import", "app.api.health",
        "--hidden-import", "app.api.memory",
        "--hidden-import", "app.api.permissions",
        "--hidden-import", "app.api.profile",
        "--hidden-import", "app.api.sessions",
        "--hidden-import", "app.api.tasks",
        "--hidden-import", "app.api.tools",
        "--hidden-import", "app.api.voice",
        "--hidden-import", "alembic",
        "--hidden-import", "uvicorn",
        "--hidden-import", "fastapi",
        str(entry_script)
    ]
    
    print(f"Running PyInstaller: {' '.join(cmd)}")
    subprocess.run(cmd, check=True)
    
    # Move the executable to Tauri's bin directory with the correct target name
    # We assume x86_64-pc-windows-msvc for now.
    target_name = "ultron-backend-x86_64-pc-windows-msvc.exe"
    bin_dir = backend_dir.parent / "apps" / "desktop" / "src-tauri" / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    
    src_exe = backend_dir / "dist" / "ultron-backend.exe"
    dest_exe = bin_dir / target_name
    
    print(f"Copying {src_exe} to {dest_exe}")
    shutil.copy2(src_exe, dest_exe)
    print("Build complete.")

if __name__ == "__main__":
    build_backend()
