"""
ULTRON Audio Device Inspection.

Provides hardware device discovery for microphones and speakers
using native Windows Multimedia APIs (winmm.dll) via ctypes.
"""

from __future__ import annotations

import os
import sys
from typing import TypedDict


class AudioDeviceInfo(TypedDict):
    available: bool
    name: str | None
    count: int


def _get_num_wave_in_devs() -> int:
    if sys.platform != "win32":
        return 0
    try:
        import ctypes
        return int(ctypes.windll.winmm.waveInGetNumDevs())
    except Exception:
        return 0


def _get_num_wave_out_devs() -> int:
    if sys.platform != "win32":
        return 0
    try:
        import ctypes
        return int(ctypes.windll.winmm.waveOutGetNumDevs())
    except Exception:
        return 0


def get_microphone_info() -> AudioDeviceInfo:
    """Inspect system recording devices without third-party dependencies."""
    num_devs = _get_num_wave_in_devs()
    if num_devs <= 0:
        return {"available": False, "name": None, "count": 0}

    dev_name = "Default Microphone"
    try:
        import ctypes
        buf = ctypes.create_string_buffer(256)
        res = ctypes.windll.winmm.waveInGetDevCapsA(0, buf, len(buf))
        if res == 0:
            extracted = buf.raw[8:40].split(b"\x00")[0].decode("ascii", errors="ignore").strip()
            if extracted:
                dev_name = extracted
    except Exception:
        pass

    return {"available": True, "name": dev_name, "count": num_devs}


def get_speaker_info() -> AudioDeviceInfo:
    """Inspect system playback devices without third-party dependencies."""
    num_devs = _get_num_wave_out_devs()
    if num_devs <= 0:
        return {"available": False, "name": None, "count": 0}

    dev_name = "Default Speakers"
    try:
        import ctypes
        buf = ctypes.create_string_buffer(256)
        res = ctypes.windll.winmm.waveOutGetDevCapsA(0, buf, len(buf))
        if res == 0:
            extracted = buf.raw[8:40].split(b"\x00")[0].decode("ascii", errors="ignore").strip()
            if extracted:
                dev_name = extracted
    except Exception:
        pass

    return {"available": True, "name": dev_name, "count": num_devs}
