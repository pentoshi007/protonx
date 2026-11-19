"""Run one tunnel operation through the Windows UAC prompt.

Starting the WireGuard tunnel needs Administrator rights, but demanding that the
user close the terminal and reopen it elevated is hostile. Instead the
unprivileged CLI writes the request to a private file, relaunches itself with
the "runas" verb -- which is what raises the UAC dialog -- and reads back the
reply the elevated child writes.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

from . import system
from .errors import TunnelError

CHILD = os.path.join(os.path.dirname(os.path.realpath(__file__)), "elevated.py")
CANCELLED = 1223
SEE_MASK_NOCLOSEPROCESS = 0x00000040
SEE_MASK_NOASYNC = 0x00000100
SEE_MASK_FLAG_NO_UI = 0x00000400
SW_HIDE = 0
WAIT_OBJECT_0 = 0
DEFAULT_TIMEOUT = 180
DECLINED = (
    "Windows did not grant administrator rights, so the tunnel was not changed. "
    "Approve the permission prompt when it appears, or run this terminal as Administrator."
)


def available():
    return system.IS_WINDOWS and os.path.exists(CHILD)


def run(operation, payload=None, timeout=DEFAULT_TIMEOUT):
    """Run ``operation`` elevated and return its result, or raise TunnelError."""
    if not system.IS_WINDOWS:
        raise TunnelError("elevation is only used on Windows")
    workdir = tempfile.mkdtemp(prefix="protonx-uac-")
    request_path = os.path.join(workdir, "request.json")
    reply_path = os.path.join(workdir, "reply.json")
    try:
        _write_json(request_path, {"operation": operation, "payload": payload})
        code = _launch([sys.executable, CHILD, request_path, reply_path], timeout)
        reply = _read_json(reply_path)
        if reply is None:
            raise TunnelError(_missing_reply(code))
        if not reply.get("ok"):
            raise TunnelError(reply.get("error") or "the elevated tunnel operation failed")
        return reply.get("result")
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def _write_json(path, payload):
    with open(path, "w") as handle:
        json.dump(payload, handle)


def _read_json(path):
    try:
        with open(path) as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def _missing_reply(code):
    return (
        "the elevated tunnel process ended without reporting a result (exit code %s). "
        "Run the terminal as Administrator to see why." % code
    )


def _launch(args, timeout=DEFAULT_TIMEOUT):
    """Start ``args`` elevated and return the child's exit code."""
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)

    class ShellExecuteInfo(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("fMask", wintypes.DWORD),
            ("hwnd", wintypes.HWND),
            ("lpVerb", wintypes.LPCWSTR),
            ("lpFile", wintypes.LPCWSTR),
            ("lpParameters", wintypes.LPCWSTR),
            ("lpDirectory", wintypes.LPCWSTR),
            ("nShow", ctypes.c_int),
            ("hInstApp", wintypes.HINSTANCE),
            ("lpIDList", ctypes.c_void_p),
            ("lpClass", wintypes.LPCWSTR),
            ("hkeyClass", wintypes.HKEY),
            ("dwHotKey", wintypes.DWORD),
            ("hIcon", wintypes.HANDLE),
            ("hProcess", wintypes.HANDLE),
        ]

    info = ShellExecuteInfo()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = SEE_MASK_NOCLOSEPROCESS | SEE_MASK_NOASYNC | SEE_MASK_FLAG_NO_UI
    info.lpVerb = "runas"
    info.lpFile = args[0]
    info.lpParameters = subprocess.list2cmdline(list(args[1:]))
    info.nShow = SW_HIDE
    shell32.ShellExecuteExW.argtypes = [ctypes.POINTER(ShellExecuteInfo)]
    shell32.ShellExecuteExW.restype = wintypes.BOOL
    if not shell32.ShellExecuteExW(ctypes.byref(info)):
        raise TunnelError(_start_error(ctypes.get_last_error()))
    if not info.hProcess:
        raise TunnelError(_missing_reply("unknown"))
    try:
        kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        if kernel32.WaitForSingleObject(info.hProcess, timeout * 1000) != WAIT_OBJECT_0:
            kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, ctypes.c_uint]
            kernel32.TerminateProcess(info.hProcess, 1)
            raise TunnelError("the elevated tunnel process did not finish within %d seconds" % timeout)
        code = wintypes.DWORD()
        kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel32.GetExitCodeProcess(info.hProcess, ctypes.byref(code))
        return int(code.value)
    finally:
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle(info.hProcess)


def _start_error(code):
    if code == CANCELLED:
        return DECLINED
    return "Windows could not start the elevated tunnel process (error %d). Try running the terminal as Administrator." % code
