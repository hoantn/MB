from __future__ import annotations

import hashlib
import os
import platform
import subprocess
import ctypes
from ctypes import wintypes

try:
    import winreg  # type: ignore
except Exception:
    winreg = None

def _read_machine_guid() -> str:
    if winreg is None:
        return ""
    try:
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography")
        val, _ = winreg.QueryValueEx(key, "MachineGuid")
        return str(val)
    except Exception:
        return ""

def _read_windows_uuid() -> str:
    try:
        out = subprocess.check_output(["wmic", "csproduct", "get", "uuid"], creationflags=0x08000000)
        lines = [l.strip() for l in out.decode(errors="ignore").splitlines() if l.strip()]
        if len(lines) >= 2:
            return lines[1]
    except Exception:
        pass
    return ""

def _get_volume_serial() -> str:
    if os.name != "nt":
        return ""
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        GetVolumeInformationW = kernel32.GetVolumeInformationW
        GetVolumeInformationW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.LPWSTR, wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
            ctypes.POINTER(wintypes.DWORD),
            ctypes.POINTER(wintypes.DWORD),
            wintypes.LPWSTR, wintypes.DWORD,
        ]
        GetVolumeInformationW.restype = wintypes.BOOL

        vol_name = ctypes.create_unicode_buffer(261)
        fs_name = ctypes.create_unicode_buffer(261)
        serial = wintypes.DWORD()
        max_comp = wintypes.DWORD()
        fs_flags = wintypes.DWORD()

        ok = GetVolumeInformationW(
            "C:\\",
            vol_name, 260,
            ctypes.byref(serial),
            ctypes.byref(max_comp),
            ctypes.byref(fs_flags),
            fs_name, 260
        )
        if ok:
            return str(serial.value)
    except Exception:
        pass
    return ""

def get_fingerprint_raw() -> str:
    parts = [
        platform.system(),
        platform.release(),
        platform.machine(),
        platform.node(),
        _read_machine_guid(),
        _read_windows_uuid(),
        _get_volume_serial(),
    ]
    return "|".join([p for p in parts if p])

def get_fingerprint_hash() -> str:
    raw = get_fingerprint_raw().encode("utf-8", errors="ignore")
    return hashlib.sha256(raw).hexdigest()
