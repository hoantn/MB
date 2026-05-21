from __future__ import annotations

import os
import sys
import time
import subprocess
import ctypes
from ctypes import wintypes

_SUSPICIOUS_PROCS = {
    "x64dbg.exe", "x32dbg.exe", "ida.exe", "ida64.exe", "ollydbg.exe",
    "dnspy.exe", "dnspy-x86.exe", "dnspy-x64.exe", "cheatengine.exe",
    "frida-server.exe", "frida.exe", "processhacker.exe", "procexp.exe",
    "wireshark.exe",
}

def _is_windows() -> bool:
    return os.name == "nt"

def _is_debugger_present_win() -> bool:
    try:
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        is_dbg = k32.IsDebuggerPresent
        is_dbg.restype = wintypes.BOOL
        if is_dbg():
            return True

        check = k32.CheckRemoteDebuggerPresent
        check.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)]
        check.restype = wintypes.BOOL
        flag = wintypes.BOOL(False)
        if check(k32.GetCurrentProcess(), ctypes.byref(flag)):
            return bool(flag.value)
    except Exception:
        pass
    return False

def _has_trace_hook() -> bool:
    try:
        if sys.gettrace() is not None:
            return True
    except Exception:
        pass
    for k in ("PYCHARM_HOSTED", "PYDEVD_LOAD_VALUES_ASYNC", "PYTHONINSPECT"):
        if os.environ.get(k):
            return True
    return False

def _suspicious_process_running() -> bool:
    if not _is_windows():
        return False
    try:
        out = subprocess.check_output(["tasklist"], creationflags=0x08000000)
        low = out.decode(errors="ignore").lower()
        return any(p.lower() in low for p in _SUSPICIOUS_PROCS)
    except Exception:
        return False

def detect_debugger_risk() -> tuple[bool, str]:
    if _has_trace_hook():
        return True, "TRACE_HOOK"
    if _is_windows() and _is_debugger_present_win():
        return True, "WIN_DEBUGGER_PRESENT"
    if _suspicious_process_running():
        return True, "SUSPICIOUS_PROCESS"
    return False, ""
