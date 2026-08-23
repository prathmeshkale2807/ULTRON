# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = [('alembic', 'alembic'), ('alembic.ini', '.')]
binaries = []
hiddenimports = ['app.api.automations', 'app.api.confirmations', 'app.api.conversations', 'app.api.devices', 'app.api.emergency', 'app.api.google', 'app.api.health', 'app.api.memory', 'app.api.permissions', 'app.api.profile', 'app.api.sessions', 'app.api.tasks', 'app.api.tools', 'app.api.voice', 'alembic', 'uvicorn', 'fastapi']
tmp_ret = collect_all('app')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['D:/gta/ultron-phase4/ultron/backend/run_server.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='ultron-backend',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
